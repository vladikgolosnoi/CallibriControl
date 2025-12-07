import contextlib
import ctypes
import logging
import math
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

import numpy as np

from neurosdk.cmn_types import SensorCommand, SensorSamplingFrequency
from neurosdk.__cmn_types import (
    CallibriEnvelopeDataListenerHandle,
    CallibriSignalDataListenerHandle,
    EnvelopeDataCallbackCallibri,
    NativeCallibriEnvelopeData,
    NativeCallibriSignalData,
    OpStatus,
    SignalCallbackCallibri,
)
from neurosdk.neuro_lib_load import _neuro_lib


Callback = Callable[[Dict], None]


def quaternion_to_euler_deg(w: float, x: float, y: float, z: float) -> Tuple[float, float, float]:
    """Преобразует кватернион в углы Эйлера (pitch, roll, yaw) в градусах."""
    # нормализация на случай дрейфа масштаба
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0:
        return 0.0, 0.0, 0.0
    w, x, y, z = w / norm, x / norm, y / norm, z / norm

    # roll (x-ось)
    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = math.degrees(math.atan2(sinr_cosp, cosr_cosp))

    # pitch (y-ось)
    sinp = 2 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.degrees(math.copysign(math.pi / 2, sinp))  # clamp at 90°
    else:
        pitch = math.degrees(math.asin(sinp))

    # yaw (z-ось)
    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = math.degrees(math.atan2(siny_cosp, cosy_cosp))
    return pitch, roll, yaw


class DataStream:
    """
    Поток данных через SDK коллбеки (Signal/Envelope + MEMS + кватернионы).
    Делает кольцевые буферы, считает RMS и базовые метрики MEMS/ориентации.
    """

    def __init__(
        self,
        device,
        emg_rate: int = 500,
        emg_buffer_sec: float = 5.0,
        mems_rate: int = 100,
        rms_window_sec: float = 0.15,
        use_envelope: bool = False,
        enable_mems: bool = True,
        enable_orientation: bool = True,
    ) -> None:
        self.device = device
        self.emg_rate = emg_rate
        self.mems_rate = mems_rate
        self.use_envelope = use_envelope
        self.enable_mems = enable_mems
        self.enable_orientation = enable_orientation

        self.emg_buffer: Deque[float] = deque(maxlen=int(emg_rate * emg_buffer_sec))
        self.acc_buffer: Deque[Tuple[float, float, float]] = deque(maxlen=int(mems_rate * 2))
        self.gyro_buffer: Deque[Tuple[float, float, float]] = deque(maxlen=int(mems_rate * 2))
        self.quat_buffer: Deque[Tuple[float, float, float, float]] = deque(maxlen=int(mems_rate * 2))

        self._callbacks: Dict[str, List[Callback]] = {"emg": [], "mems": [], "orientation": [], "stats": []}
        self._lock = threading.RLock()
        self._running = False
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._logger = logging.getLogger(__name__)
        self._latest: Dict[str, float] = {}
        self.rms_window_sec = rms_window_sec
        self._signal_handle: Optional[CallibriSignalDataListenerHandle] = None
        self._envelope_handle: Optional[CallibriEnvelopeDataListenerHandle] = None
        self._signal_cb = None
        self._envelope_cb = None
        self._emg_samples_total = 0
        self._last_emg_warn = 0.0
        self._emg_mode = "envelope" if use_envelope else "signal"
        self._emg_started_at = 0.0
        self._using_sdk_signal = False
        self._using_sdk_envelope = False

        # калибровочные смещения MEMS/ориентации
        self.pitch_offset = 0.0
        self.roll_offset = 0.0
        self.yaw_offset = 0.0
        self.acc_offset = (0.0, 0.0, 0.0)

    # Public API ------------------------------------------------------------
    def add_callback(self, event: str, cb: Callback) -> None:
        self._callbacks.setdefault(event, []).append(cb)

    def set_orientation_offsets(self, pitch: float, roll: float, yaw: float = 0.0) -> None:
        """Устанавливает базовые смещения ориентации после калибровки."""
        self.pitch_offset = pitch
        self.roll_offset = roll
        self.yaw_offset = yaw

    def set_acc_offset(self, x: float, y: float, z: float) -> None:
        self.acc_offset = (x, y, z)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._attach_callbacks()
        self._start_streams()
        self._worker = None

    def stop(self) -> None:
        self._stop.set()
        self._running = False
        self._detach_callbacks()
        self._stop_streams()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=1.0)

    def latest_metrics(self) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        with self._lock:
            rms = self._compute_rms()
            metrics["emg_rms"] = rms
            metrics["emg_mode"] = self._emg_mode

            if self.acc_buffer:
                acc = self.acc_buffer[-1]
                acc_mag = math.sqrt(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2)
                metrics.update({"acc_x": acc[0], "acc_y": acc[1], "acc_z": acc[2], "acc_magnitude": acc_mag})

            if self.quat_buffer:
                quat = self.quat_buffer[-1]
                pitch, roll, yaw = quaternion_to_euler_deg(*quat)
                metrics.update({"pitch": pitch - self.pitch_offset, "roll": roll - self.roll_offset, "yaw": yaw - self.yaw_offset, "orientation_source": "quat"})
            elif self.acc_buffer:
                ax, ay, az = self.acc_buffer[-1]
                pitch = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az))) - self.pitch_offset
                roll = math.degrees(math.atan2(ay, az)) - self.roll_offset
                metrics.update({"pitch": pitch, "roll": roll, "yaw": 0.0, "orientation_source": "acc"})

            self._latest.update(metrics)
            emg_empty = self._emg_samples_total == 0
        if emg_empty and time.time() - self._last_emg_warn > 5.0:
            self._logger.warning("Нет EMG данных: проверьте подключение/электроды или попробуйте --envelope")
            self._last_emg_warn = time.time()
        return dict(self._latest)

    def emg_preview(self, count: int = 120) -> list[float]:
        """Возвращает последние N EMG отсчётов для визуализации."""
        with self._lock:
            if not self.emg_buffer:
                return []
            return list(self.emg_buffer)[-count:]

    # Internal --------------------------------------------------------------
    def _configure_sampling(self) -> None:
        sf_map = {
            250: SensorSamplingFrequency.FrequencyHz250,
            500: SensorSamplingFrequency.FrequencyHz500,
            1000: SensorSamplingFrequency.FrequencyHz1000,
        }
        desired = sf_map.get(self.emg_rate)
        if desired:
            with contextlib.suppress(Exception):
                self.device.sampling_frequency = desired

    def _attach_callbacks(self) -> None:
        if self.use_envelope:
            self._register_envelope_callback()
        else:
            self._register_signal_callback()

        if self.enable_mems and hasattr(self.device, "memsDataReceived"):
            self.device.memsDataReceived = self._on_mems

        if self.enable_orientation and hasattr(self.device, "quaternionDataReceived"):
            self.device.quaternionDataReceived = self._on_quaternion

    def _detach_callbacks(self) -> None:
        # Стабильность > агрессивная очистка: на macOS remove/unset иногда падает с SIGBUS/SIGSEGV.
        # Сбрасываем Python-коллбеки, остальное очистит disconnect().
        with contextlib.suppress(Exception):
            self.device.signalDataReceived = None
            self.device.envelopeDataReceived = None
            self.device.memsDataReceived = None
            if hasattr(self.device, "quaternionDataReceived"):
                self.device.quaternionDataReceived = None

        self._signal_handle = None
        self._envelope_handle = None
        self._signal_cb = None
        self._envelope_cb = None
        self._using_sdk_signal = False
        self._using_sdk_envelope = False

    def _start_streams(self) -> None:
        try:
            if self.use_envelope and self.device.is_supported_command(SensorCommand.StartEnvelope):
                self.device.exec_command(SensorCommand.StartEnvelope)
                self._emg_mode = "envelope"
            elif self.device.is_supported_command(SensorCommand.StartSignal):
                self.device.exec_command(SensorCommand.StartSignal)
                self._emg_mode = "signal"
            self._emg_started_at = time.time()
            if self.enable_mems and self.device.is_supported_command(SensorCommand.StartMEMS):
                self.device.exec_command(SensorCommand.StartMEMS)
            if self.enable_orientation and self.device.is_supported_command(SensorCommand.StartAngle):
                self.device.exec_command(SensorCommand.StartAngle)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Start streams failed: %s", exc)

    def _stop_streams(self) -> None:
        # Останавливаем через disconnect, чтобы избежать сбоев exec_command на некоторых системах.
        self._emg_mode = "signal" if not self.use_envelope else "envelope"

    def _register_signal_callback(self) -> None:
        """Регистрирует обработчик EMG через прямой _neuro_lib (стабильнее, чем set_signal_callbacks)."""
        self._using_sdk_signal = False
        status = OpStatus()

        @SignalCallbackCallibri
        def _cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                samples: List[float] = []
                for i in range(sz):
                    pkt = data[i]
                    count = int(pkt.SzSamples)
                    if count <= 0 or count > 256:
                        continue
                    raw_ptr = pkt.Samples
                    if not raw_ptr:
                        continue
                    try:
                        arr = ctypes.cast(raw_ptr, ctypes.POINTER(ctypes.c_double * count)).contents
                        limit = min(count, 32)
                        samples.extend([arr[j] for j in range(limit)])
                    except Exception as exc_inner:  # noqa: BLE001
                        self._logger.debug("signal pkt parse fail: %s", exc_inner)
                        continue
                if samples:
                    with self._lock:
                        self.emg_buffer.extend(samples)
                        self._emg_samples_total += len(samples)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("signal callback failed: %s", exc)

        handle = CallibriSignalDataListenerHandle()
        try:
            _neuro_lib.addSignalCallbackCallibri(
                self.device.sensor_ptr,
                _cb,
                ctypes.byref(handle),
                ctypes.py_object(self.device),
                ctypes.byref(status),
            )
            self._signal_cb = _cb
            self._signal_handle = handle
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to add signal callback: %s", exc)

    def _register_envelope_callback(self) -> None:
        try:
            self.device.envelopeDataReceived = self._on_envelope_sdk  # type: ignore[assignment]
            if hasattr(self.device, "set_envelope_callbacks"):
                self.device.set_envelope_callbacks()
            self._using_sdk_envelope = True
            return
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("set_envelope_callbacks failed, fallback to direct: %s", exc)
            self._using_sdk_envelope = False

        status = OpStatus()

        @EnvelopeDataCallbackCallibri
        def _cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                with self._lock:
                    for i in range(sz):
                        self.emg_buffer.append(float(data[i].Sample))
                        self._emg_samples_total += 1
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("envelope callback failed: %s", exc)

        handle = CallibriEnvelopeDataListenerHandle()
        try:
            _neuro_lib.addEnvelopeDataCallbackCallibri(
                self.device.sensor_ptr,
                _cb,
                ctypes.byref(handle),
                ctypes.py_object(self.device),
                ctypes.byref(status),
            )
            self._envelope_cb = _cb
            self._envelope_handle = handle
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to add envelope callback: %s", exc)

    # Callbacks -------------------------------------------------------------
    def _on_signal_sdk(self, sensor, packets) -> None:  # noqa: ANN001
        self._handle_signal_packets(packets)

    def _on_envelope_sdk(self, sensor, packets) -> None:  # noqa: ANN001
        self._handle_envelope_packets(packets)

    def _handle_signal_packets(self, packets) -> None:
        try:
            if not self._running or not packets:
                return
            samples: List[float] = []
            for packet in packets:
                count = int(getattr(packet, "SzSamples", 0))
                if count <= 0 or count > 512:
                    continue
                raw_samples = getattr(packet, "Samples", None)
                if raw_samples is None:
                    continue
                try:
                    if isinstance(raw_samples, (list, tuple)):
                        samples.extend(list(raw_samples)[:count])
                        continue
                    samples_ptr = ctypes.cast(raw_samples, ctypes.POINTER(ctypes.c_double * count))
                    if not samples_ptr:
                        continue
                    arr = samples_ptr.contents
                    samples.extend([arr[i] for i in range(count)])
                except Exception as exc:  # noqa: BLE001
                    self._logger.debug("signal parse failed: %s", exc)
                    continue
            if samples:
                with self._lock:
                    self.emg_buffer.extend(samples)
                    self._emg_samples_total += len(samples)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("on_signal processing failed: %s", exc)

    def _handle_envelope_packets(self, packets) -> None:
        try:
            if not self._running or not packets:
                return
            samples = []
            for p in packets:
                if hasattr(p, "Sample"):
                    try:
                        samples.append(float(p.Sample))
                    except Exception:
                        continue
            if samples:
                with self._lock:
                    self.emg_buffer.extend(samples)
                    self._emg_samples_total += len(samples)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("on_envelope processing failed: %s", exc)

    def _on_mems(self, _sensor, packets) -> None:
        if not self._running or not packets:
            return
        last = packets[-1]
        acc = (
            last.Accelerometer.X - self.acc_offset[0],
            last.Accelerometer.Y - self.acc_offset[1],
            last.Accelerometer.Z - self.acc_offset[2],
        )
        gyro = (last.Gyroscope.X, last.Gyroscope.Y, last.Gyroscope.Z)
        with self._lock:
            self.acc_buffer.append(acc)
            self.gyro_buffer.append(gyro)

    def _on_quaternion(self, _sensor, packets) -> None:
        if not self._running or not packets:
            return
        last = packets[-1]
        quat = (last.W, last.X, last.Y, last.Z)
        with self._lock:
            self.quat_buffer.append(quat)

    # Worker ----------------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            metrics: Dict[str, float] = {}
            with self._lock:
                rms = self._compute_rms()
                metrics["emg_rms"] = rms
                self._emit("emg", {"rms": rms})
                # предупреждение, если EMG не приходит
                if self._emg_samples_total == 0:
                    now = time.time()
                    if now - self._last_emg_warn > 5.0:
                        self._logger.warning(
                            "Нет EMG данных: проверьте подключение/электроды или попробуйте --envelope"
                        )
                        self._last_emg_warn = now

                acc = self.acc_buffer[-1] if self.acc_buffer else None
                gyro = self.gyro_buffer[-1] if self.gyro_buffer else None
                quat = self.quat_buffer[-1] if self.quat_buffer else None

                if acc:
                    acc_mag = math.sqrt(acc[0] ** 2 + acc[1] ** 2 + acc[2] ** 2)
                    metrics.update({"acc_x": acc[0], "acc_y": acc[1], "acc_z": acc[2], "acc_magnitude": acc_mag})
                    self._emit("mems", {"acc": acc, "gyro": gyro, "acc_mag": acc_mag})

                if quat:
                    pitch, roll, yaw = quaternion_to_euler_deg(*quat)
                    pitch -= self.pitch_offset
                    roll -= self.roll_offset
                    yaw -= self.yaw_offset
                    metrics.update({"pitch": pitch, "roll": roll, "yaw": yaw, "orientation_source": "quat"})
                    self._emit("orientation", {"pitch": pitch, "roll": roll, "yaw": yaw, "source": "quat"})
                elif acc:
                    # упрощённая ориентация по акселерометру
                    ax, ay, az = acc
                    pitch = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az))) - self.pitch_offset
                    roll = math.degrees(math.atan2(ay, az)) - self.roll_offset
                    metrics.update({"pitch": pitch, "roll": roll, "yaw": 0.0, "orientation_source": "acc"})
                    self._emit("orientation", {"pitch": pitch, "roll": roll, "yaw": 0.0, "source": "acc"})

                self._latest.update(metrics)
                self._emit("stats", metrics)
            time.sleep(0.1)

    def _compute_rms(self) -> float:
        window_samples = int(self.rms_window_sec * self.emg_rate)
        if window_samples <= 0 or len(self.emg_buffer) < window_samples:
            return 0.0
        data = np.fromiter(list(self.emg_buffer)[-window_samples:], dtype=float)
        return float(np.sqrt(np.mean(data ** 2)))

    def _emit(self, event: str, payload: Dict) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb(payload)
            except Exception as exc:  # noqa: BLE001
                self._logger.debug("callback %s failed: %s", event, exc)
