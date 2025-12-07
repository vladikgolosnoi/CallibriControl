"""Простой веб-сервер для Callibri Control с SSE-стримом метрик/жестов.

Запускается из CLI (`python main.py --web`) и:
- пытается подключиться к Callibri через SensorManager;
- транслирует EMG/MEMS метрики, жесты и состояние в EventSource (`/events`);
- отдаёт статические файлы из папки `web/` и простой REST (`/api/state`, `/api/start`, `/api/calibrate`, `/api/profile`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from callibri_control.core.data_stream import DataStream
from callibri_control.core.sensor_manager import SensorManager
from callibri_control.detection.adaptive_thresholds import AdaptiveThresholds
from callibri_control.detection.fatigue_monitor import FatigueMonitor
from callibri_control.detection.gesture_detector import DetectorConfig, GestureDetector
from callibri_control.utils.config_manager import ConfigManager

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
LOGGER = logging.getLogger("web")


class EventBroker:
    """Мини-шина для SSE: очередь на клиента, fan-out publish."""

    def __init__(self) -> None:
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def publish(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                with contextlib.suppress(Exception):
                    q.get_nowait()
                with contextlib.suppress(Exception):
                    q.put_nowait(payload)


class WebDataPump:
    """Фоновая нитка: подключение к датчику или демо, публикация снапшотов."""

    def __init__(self, cfg: ConfigManager, manager: Optional[SensorManager], address: Optional[str] = None) -> None:
        self.cfg = cfg
        self.manager = manager
        self.address = address
        self.thresholds = AdaptiveThresholds(mvc=0.3, baseline=0.02)
        self.detector = GestureDetector(
            self.thresholds,
            fatigue=FatigueMonitor(fs=int(cfg.config.get("sensor", {}).get("emg_sampling_rate", 500))),
            config=DetectorConfig(profile=cfg.config.get("recognition", {}).get("sensitivity_profile", "NORMAL")),
        )
        self.events = EventBroker()
        self._snapshot: Dict[str, Any] = {
            "state": "idle",
            "mode": "demo" if cfg.config.get("general", {}).get("demo_mode") else "device",
            "streaming": False,
            "device": {},
            "metrics": {},
            "gesture": None,
            "gesture_history": [],
            "profile": {"gesture": self.detector.config.profile, "control": cfg.config.get("control", {}).get("profile", "DEFAULT")},
            "session_ms": 0,
        }
        self._snapshot_lock = threading.Lock()
        self._gesture_history: list[Dict[str, Any]] = []
        self._stop: Optional[threading.Event] = None
        self._worker: Optional[threading.Thread] = None
        self._prefer_demo = bool(cfg.config.get("general", {}).get("demo_mode", False))
        self._current_stream: Optional[DataStream] = None
        self._session_started_at: Optional[float] = None
        self._calibration_requested = False
        self._last_emg_mode = "signal"

    # --------------------------- lifecycle
    def start(self, force_demo: Optional[bool] = None) -> None:
        if force_demo is not None:
            self._prefer_demo = force_demo
        if not self._prefer_demo:
            self._ensure_manager()
            # если задан адрес устройства, не переключаемся самопроизвольно в демо
            if self.address:
                self._prefer_demo = False
        self.stop()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._loop, args=(self._stop,), daemon=True)
        self._worker.start()

    def stop(self) -> None:
        if self._stop:
            self._stop.set()
        if self._current_stream:
            with contextlib.suppress(Exception):
                self._current_stream.stop()
        if self.manager:
            with contextlib.suppress(Exception):
                self.manager.disconnect()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.5)

    def restart(self, force_demo: Optional[bool] = None) -> None:
        self.start(force_demo=force_demo)

    def _ensure_manager(self) -> None:
        if self.manager is not None:
            return
        try:
            general_cfg = self.cfg.config.get("general", {})
            self.manager = SensorManager(
                scan_timeout=general_cfg.get("scan_timeout", 5),
                reconnect=general_cfg.get("reconnect", True),
                reconnect_interval=general_cfg.get("reconnect_interval", 3),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.error("Не удалось создать SensorManager: %s", exc)
            self.manager = None

    def request_calibration(self) -> None:
        self._calibration_requested = True

    def set_profile(self, profile: str) -> str:
        profile_norm = (profile or "").upper() or "NORMAL"
        self.detector.config.profile = profile_norm
        with self._snapshot_lock:
            self._snapshot["profile"]["gesture"] = profile_norm
        return profile_norm

    # --------------------------- public data
    def snapshot(self) -> Dict[str, Any]:
        with self._snapshot_lock:
            return dict(self._snapshot)

    # --------------------------- internals
    def _loop(self, stop_event: threading.Event) -> None:
        try:
            mode = "demo" if self._prefer_demo or self.manager is None else "device"
            if mode == "demo":
                self._loop_demo(stop_event)
                return
            connected_once = self._loop_device(stop_event)
            if not connected_once and not stop_event.is_set():
                LOGGER.warning("Не удалось подключиться к Callibri, переключаемся в демо.")
                self._prefer_demo = True
                self._loop_demo(stop_event)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Поток веб-данных упал: %s. Переключаемся в демо.", exc)
            self._publish_status(state="error", mode="device", device={}, streaming=False)
            self._prefer_demo = True
            if not stop_event.is_set():
                self._loop_demo(stop_event)

    def _loop_device(self, stop_event: threading.Event) -> bool:
        connected_once = False
        first_attempt_at = time.time()
        while not stop_event.is_set():
            self._publish_status(state="connecting", mode="device", device={}, streaming=False)
            if self.manager is None:
                break
            device_info = self._connect()
            if device_info is None:
                # если указан адрес — продолжаем ждать нужный датчик, не уходим в демо
                if not connected_once and not self.address and time.time() - first_attempt_at > 8.0:
                    return False
                if stop_event.wait(1.2):
                    break
                continue
            connected_once = True
            device = self.manager.get_device()
            if device is None:
                self._publish_status(state="error", mode="device", device={}, streaming=False)
                if stop_event.wait(1.0):
                    break
                continue

            stream = DataStream(
                device,
                emg_rate=int(self.cfg.config.get("sensor", {}).get("emg_sampling_rate", 500)),
                # по умолчанию используем сырой сигнал (стабильнее, чем envelope)
                use_envelope=bool(self.cfg.config.get("sensor", {}).get("use_envelope", False)),
                enable_mems=True,
                enable_orientation=False,  # кватернионы иногда падают в SDK, оставляем акселерометр для стабильности
                rms_window_sec=0.12,
            )
            self._current_stream = stream
            stream.start()
            self._session_started_at = time.time()
            self._auto_calibrate(stream, stop_event)
            self._publish_status(state="active", mode="device", device=device_info, streaming=True)

            try:
                while not stop_event.is_set() and (self.manager.is_connected() if self.manager else False):
                    metrics = stream.latest_metrics()
                    events = self.detector.process_metrics(metrics)
                    if self._calibration_requested:
                        self._auto_calibrate(stream, stop_event)
                        self._calibration_requested = False
                    self._push_snapshot(metrics, events, device_info, mode="device", emg_preview=stream.emg_preview(120))
                    time.sleep(0.05)
            finally:
                with contextlib.suppress(Exception):
                    stream.stop()
                if self.manager:
                    with contextlib.suppress(Exception):
                        self.manager.disconnect()
                self._publish_status(state="disconnected", mode="device", device=device_info, streaming=False)
                self._current_stream = None
                self._session_started_at = None
            if stop_event.wait(1.0):
                break
        return connected_once

    def _loop_demo(self, stop_event: threading.Event) -> None:
        LOGGER.info("Старт демо-потока для веб-интерфейса.")
        self.thresholds.update_calibration(mvc=0.7, baseline=0.06)
        t = 0.0
        device_info = {"name": "Callibri (demo)", "battery": "100", "firmware": "demo"}
        self._publish_status(state="demo", mode="demo", device=device_info, streaming=True)
        while not stop_event.is_set():
            emg = 0.08 + 0.05 * np.sin(t) + np.random.uniform(0, 0.04)
            if np.random.rand() > 0.96:
                emg += 0.35
            pitch = 18 * np.sin(t / 1.6)
            roll = 14 * np.sin(t / 1.1 + 0.8)
            acc = 1.0 + abs(np.sin(t)) * 0.8
            metrics = {"emg_rms": float(emg), "pitch": float(pitch), "roll": float(roll), "yaw": 0.0, "acc_magnitude": float(acc), "orientation_source": "sim"}
            events = self.detector.process_metrics(metrics)
            self._push_snapshot(metrics, events, device_info, mode="demo", emg_preview=self._fake_emg_preview(emg))
            t += 0.08
            time.sleep(0.05)

    def _connect(self) -> Optional[Dict[str, str]]:
        if self.manager is None:
            return None
        devices = self.manager.scan_devices()
        if not devices:
            LOGGER.warning("Callibri не найдены поблизости.")
            return None
        target = None
        if self.address:
            target = next((d["sensor_info"] for d in devices if d["address"].lower() == self.address.lower()), None)
        if target is None:
            target = devices[0]["sensor_info"]
        if not self.manager.connect(target, wait=True, timeout=self.manager.scan_timeout + 5):
            LOGGER.warning("Не удалось подключиться к %s", target)
            return None
        info = self.manager.get_device_info()
        if info is None:
            LOGGER.warning("Нет информации об устройстве.")
            return None
        return info

    def _auto_calibrate(self, stream: DataStream, stop_event: threading.Event) -> None:
        """Собираем окно RMS, вычисляем baseline/MVC."""
        rms_samples: list[float] = []
        t_end = time.time() + 2.5
        while time.time() < t_end and not stop_event.is_set():
            metrics = stream.latest_metrics()
            rms_samples.append(float(metrics.get("emg_rms", 0.0) or 0.0))
            time.sleep(0.05)
        if not rms_samples:
            return
        baseline = float(np.percentile(rms_samples, 25))
        mvc = float(np.percentile(rms_samples, 98))
        # Минимальный зазор адаптивный для мелких значений
        min_gap = max(0.005, baseline * 4)
        mvc = max(mvc, baseline + min_gap)
        self.thresholds.update_calibration(mvc=mvc, baseline=baseline)

    def _push_snapshot(self, metrics: Dict[str, Any], events, device_info: Dict[str, Any], mode: str, emg_preview: Optional[list[float]]) -> None:
        rms = float(metrics.get("emg_rms", 0.0) or 0.0)
        span = max(self.thresholds.mvc - self.thresholds.baseline, 1e-6)
        strength = max(0.0, min((rms - self.thresholds.baseline) / span, 1.5))
        strength_vis = max(strength, rms * 80)  # усиливаем визуализацию слабых сигналов
        fatigue_state = self.detector.fatigue_state()
        fatigue_idx = float(fatigue_state.index) if fatigue_state else 0.0
        gesture_payload = None
        if events:
            gesture_payload = dict(events[-1])
            threshold = self.thresholds.thresholds_for_profile(self.detector.config.profile).on
            g_val = abs(float(gesture_payload.get("value", 0.0)))
            gesture_payload["confidence"] = max(0.05, min(g_val / max(threshold, 1e-3), 2.0))
            self._gesture_history.append(
                {"type": gesture_payload["type"], "ts": gesture_payload.get("timestamp", time.time())}
            )
            self._gesture_history = self._gesture_history[-18:]

        payload = {
            "ts": time.time(),
            "state": "active" if mode == "device" else mode,
            "mode": mode,
            "streaming": True,
            "device": device_info,
            "metrics": {
                "emg": rms,
                "strength": strength,
                "strength_vis": strength_vis,
                "fatigue_index": fatigue_idx,
                "fatigue_trend": fatigue_state.trend if fatigue_state else "",
                "pitch": float(metrics.get("pitch", 0.0) or 0.0),
                "roll": float(metrics.get("roll", 0.0) or 0.0),
                "yaw": float(metrics.get("yaw", 0.0) or 0.0),
                "acc": float(metrics.get("acc_magnitude", 0.0) or 0.0),
                "orientation_source": metrics.get("orientation_source", ""),
                "emg_mode": self._last_emg_mode,
            },
            "gesture": gesture_payload,
            "gesture_history": list(self._gesture_history),
            "profile": {
                "gesture": self.detector.config.profile,
                "control": self.cfg.config.get("control", {}).get("profile", "DEFAULT"),
            },
            "session_ms": self._session_ms(),
            "signal_quality": self._signal_quality(),
            "emg_preview": emg_preview or [],
        }
        self._last_emg_mode = metrics.get("emg_mode", self._last_emg_mode)
        with self._snapshot_lock:
            self._snapshot = payload
        self.events.publish(payload)

    def _publish_status(self, state: str, mode: str, device: Dict[str, Any], streaming: bool) -> None:
        payload = {
            "ts": time.time(),
            "state": state,
            "mode": mode,
            "streaming": streaming,
            "device": device,
            "metrics": {},
            "gesture": None,
            "gesture_history": list(self._gesture_history),
            "profile": {
                "gesture": self.detector.config.profile,
                "control": self.cfg.config.get("control", {}).get("profile", "DEFAULT"),
            },
            "session_ms": self._session_ms(),
            "signal_quality": self._signal_quality(),
            "emg_preview": [],
        }
        with self._snapshot_lock:
            self._snapshot = payload
        self.events.publish(payload)

    def _session_ms(self) -> int:
        if not self._session_started_at:
            return 0
        return int((time.time() - self._session_started_at) * 1000)

    def _signal_quality(self) -> str:
        if not self.manager:
            return ""
        with contextlib.suppress(Exception):
            state = self.manager.get_electrode_state()
            return state or ""
        return ""

    def _fake_emg_preview(self, latest: float, count: int = 90) -> list[float]:
        base = getattr(self, "_demo_preview", [0.0] * count)
        series = base[1:] + [latest]
        self._demo_preview = series
        return series


class _Handler(SimpleHTTPRequestHandler):
    """HTTP + API + SSE."""

    def __init__(self, *args, directory: str, backend: WebDataPump, **kwargs) -> None:
        self.backend = backend
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, fmt: str, *args) -> None:  # noqa: D401
        LOGGER.debug(fmt, *args)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/state"):
            return self._json(self.backend.snapshot())
        if self.path.startswith("/events"):
            return self._sse()
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/start"):
            data = self._json_body()
            force_demo = bool(data.get("demo")) if isinstance(data, dict) else None
            self.backend.restart(force_demo=force_demo)
            return self._json({"ok": True, "mode": self.backend.snapshot().get("mode")})
        if self.path.startswith("/api/calibrate"):
            self.backend.request_calibration()
            return self._json({"ok": True, "calibrating": True})
        if self.path.startswith("/api/profile"):
            data = self._json_body() or {}
            name = str(data.get("gesture", "") or "NORMAL")
            active = self.backend.set_profile(name)
            return self._json({"ok": True, "profile": active})
        if self.path.startswith("/api/hud"):
            return self._json({"ok": True})
        return self._not_found()

    # ---------------------- helpers
    def _json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        with contextlib.suppress(Exception):
            return json.loads(raw.decode("utf-8"))
        return {}

    def _json(self, payload: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _not_found(self) -> None:
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _sse(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.backend.events.subscribe()
        try:
            while True:
                try:
                    payload = q.get(timeout=15)
                    data = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self.backend.events.unsubscribe(q)


def serve_web(cfg: ConfigManager, manager: Optional[SensorManager], host: str = "0.0.0.0", port: int = 8765, address: Optional[str] = None) -> int:
    """Запускает веб-сервер и блокирует поток до Ctrl+C."""
    backend = WebDataPump(cfg, manager, address=address)
    backend.start()
    handler = lambda *args, **kwargs: _Handler(*args, directory=str(WEB_ROOT), backend=backend, **kwargs)  # noqa: E731
    httpd = ThreadingHTTPServer((host, port), handler)
    LOGGER.info("Веб-интерфейс запущен: http://%s:%s", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Остановка веб-сервера...")
    finally:
        backend.stop()
        httpd.server_close()
    return 0
