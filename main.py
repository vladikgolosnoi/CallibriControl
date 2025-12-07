import argparse
import logging
import sys
import time
import contextlib
import os
from typing import Optional

from callibri_control.core.calibration import Calibration
from callibri_control.core.data_stream import DataStream
from callibri_control.core.sensor_manager import SensorManager
from callibri_control.utils.config_manager import ConfigManager
from callibri_control.detection.adaptive_thresholds import AdaptiveThresholds
from callibri_control.detection.fatigue_monitor import FatigueMonitor
from callibri_control.detection.gesture_detector import GestureDetector, DetectorConfig


def configure_logging(level: str) -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def pick_target(devices, address: Optional[str]):
    target = None
    if address:
        for dev in devices:
            if dev["address"].lower() == address.lower():
                target = dev["sensor_info"]
                break
    if target is None and devices:
        target = devices[0]["sensor_info"]
    return target


def configure_emg_device(device) -> None:
    """Единые настройки EMG (как в примерах SDK): тип сигнала, вход, усиление, частота."""
    import ctypes
    from neurosdk.neuro_lib_load import _neuro_lib
    from neurosdk.callibri_sensor import (
        CallibriSignalType,
        SensorExternalSwitchInput,
        SensorSamplingFrequency,
        SensorADCInput,
        SensorGain,
    )
    from neurosdk.__cmn_types import OpStatus

    with contextlib.suppress(Exception):
        device.signal_type = CallibriSignalType.EMG
    with contextlib.suppress(Exception):
        status = OpStatus()
        _neuro_lib.setSignalSettingsCallibri(device.sensor_ptr, CallibriSignalType.EMG.value, ctypes.byref(status))  # type: ignore[arg-type]
    with contextlib.suppress(Exception):
        device.ext_sw_input = SensorExternalSwitchInput.Electrodes
    with contextlib.suppress(Exception):
        device.adc_input = SensorADCInput.Electrodes
    with contextlib.suppress(Exception):
        device.gain = SensorGain.Gain12  # высокое усиление для чувствительности без ошибок параметров
    with contextlib.suppress(Exception):
        device.sampling_frequency = SensorSamplingFrequency.FrequencyHz500


def run_scan(manager: SensorManager) -> int:
    devices = []
    for _ in range(3):
        devices = manager.scan_devices()
        if devices:
            break
        time.sleep(1.0)
    if not devices:
        print("Callibri devices not found.")
        return 1
    print("Found devices:")
    for idx, dev in enumerate(devices, start=1):
        print(f"{idx}. {dev['name']} ({dev['address']}) RSSI={dev['rssi']} dBm")
    return 0


def run_connect(manager: SensorManager, address: Optional[str]) -> int:
    devices = manager.scan_devices()
    if not devices:
        print("Callibri devices not found.")
        return 1
    target = pick_target(devices, address)
    if target is None:
        print("No target device.")
        return 1
    if not manager.connect(target, wait=True, timeout=manager.scan_timeout + 5):
        print("Не удалось подключиться к устройству.")
        return 1
    info = manager.get_device_info()
    if not info:
        print("Не удалось получить информацию об устройстве.")
        return 1
    print("Подключено:")
    print(f"  Name: {info.get('name', 'n/a')}")
    print(f"  Address: {info.get('address', 'n/a')}")
    print(f"  Serial: {info.get('serial', 'n/a')}")
    print(f"  Battery: {info.get('battery', 'n/a')}")
    print(f"  Firmware: {info.get('firmware', 'n/a')}")
    print("Следим за состоянием (Ctrl+C для выхода)...")
    try:
        while True:
            status = "connected" if manager.is_connected() else "disconnected"
            print(f"State: {status}    ", end="\r", flush=True)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nОтключение...")
    finally:
        manager.disconnect()
    return 0


def run_stream(manager: SensorManager, address: Optional[str], use_envelope: bool, enable_orientation: bool) -> int:
    import ctypes
    import math
    import collections
    from neurosdk.neuro_lib_load import _neuro_lib
    from neurosdk.__cmn_types import (
        SignalCallbackCallibri,
        CallibriSignalDataListenerHandle,
        EnvelopeDataCallbackCallibri,
        CallibriEnvelopeDataListenerHandle,
        OpStatus,
    )
    from neurosdk.cmn_types import SensorFamily, SensorCommand
    from neurosdk.scanner import Scanner

    # Повторяем скан до 3 раз, если устройство не сразу видимо
    devices = []
    for _ in range(3):
        devices = manager.scan_devices()
        if devices:
            break
        time.sleep(1.0)
    if not devices:
        print("Callibri devices not found.")
        return 1
    target = pick_target(devices, address)
    if target is None:
        print("No target device.")
        return 1

    scanner = Scanner([SensorFamily.LECallibri, SensorFamily.LEKolibri])
    device = scanner.create_sensor(target)
    device.connect()
    configure_emg_device(device)

    status = OpStatus()
    samples = collections.deque(maxlen=1000)

    if use_envelope:
        handle = CallibriEnvelopeDataListenerHandle()

        @EnvelopeDataCallbackCallibri
        def _env_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    samples.append(float(data[i].Sample))
            except Exception:
                pass

        _neuro_lib.addEnvelopeDataCallbackCallibri(
            device.sensor_ptr,
            _env_cb,
            ctypes.byref(handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartEnvelope)
        stream_name = "envelope"
    else:
        handle = CallibriSignalDataListenerHandle()

        @SignalCallbackCallibri
        def _sig_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    pkt = data[i]
                    n = int(pkt.SzSamples)
                    if n <= 0 or n > 256 or not pkt.Samples:
                        continue
                    try:
                        arr = ctypes.cast(pkt.Samples, ctypes.POINTER(ctypes.c_double * n)).contents
                        limit = min(n, 32)  # читаем до 32 отсчётов, чтобы RMS реагировал
                        samples.extend(arr[j] for j in range(limit))
                    except Exception:
                        continue
            except Exception:
                pass

        _neuro_lib.addSignalCallbackCallibri(
            device.sensor_ptr,
            _sig_cb,
            ctypes.byref(handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartSignal)
        stream_name = "raw signal"

    print(f"Стриминг EMG ({stream_name}). Ctrl+C для выхода.")
    try:
        while True:
            if samples:
                window = list(samples)[-200:]  # ~0.4 с для более быстрой реакции
                mean_val = sum(window) / len(window)
                rms = math.sqrt(sum((x - mean_val) ** 2 for x in window) / len(window))
                vmin, vmax = min(window), max(window)
            else:
                rms = 0.0
                mean_val = 0.0
                vmin = vmax = 0.0
            print(
                f"EMG RMS: {rms:6.4f} | mean: {mean_val:6.4f} | min/max: {vmin:6.4f}/{vmax:6.4f} | samples={len(samples)}",
                end="\r",
                flush=True,
            )
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nОстановка стрима...")
    finally:
        with contextlib.suppress(Exception):
            if use_envelope:
                device.exec_command(SensorCommand.StopEnvelope)
            else:
                device.exec_command(SensorCommand.StopSignal)
        with contextlib.suppress(Exception):
            device.disconnect()
    return 0


def run_calibrate(manager: SensorManager, address: Optional[str], use_envelope: bool, enable_orientation: bool) -> int:
    devices = manager.scan_devices()
    if not devices:
        print("Callibri devices not found.")
        return 1
    target = pick_target(devices, address)
    if target is None:
        print("No target device.")
        return 1
    if not manager.connect(target, wait=True, timeout=manager.scan_timeout + 5):
        print("Не удалось подключиться к устройству.")
        return 1
    device = manager.get_device()
    if device is None:
        print("Failed to create device.")
        return 1

    stream = DataStream(
        device,
        use_envelope=use_envelope,
        enable_mems=False,
        enable_orientation=False,
        rms_window_sec=0.1,
    )
    stream.start()
    calib = Calibration(stream)
    time.sleep(1.0)
    try:
        mems_result = calib.calibrate_mems()
        stream.set_orientation_offsets(mems_result.baseline_pitch, mems_result.baseline_roll, mems_result.baseline_yaw)
        stream.set_acc_offset(*mems_result.acc_bias)

        result = calib.calibrate_emg()
        print("Калибровка завершена:")
        print(f"baseline={result.baseline:.2f}, mvc={result.mvc:.2f}")
        print("Thresholds:")
        for k, v in result.thresholds.items():
            print(f"  {k}: {v:.2f}")
    finally:
        stream.stop()
        manager.disconnect()
    return 0


def run_detect(
    manager: SensorManager,
    address: Optional[str],
    use_envelope: bool,
    enable_orientation: bool,
    profile: str,
) -> int:
    import ctypes
    import collections
    import math
    from neurosdk.neuro_lib_load import _neuro_lib
    from neurosdk.__cmn_types import (
        SignalCallbackCallibri,
        CallibriSignalDataListenerHandle,
        EnvelopeDataCallbackCallibri,
        CallibriEnvelopeDataListenerHandle,
        OpStatus,
    )
    from neurosdk.cmn_types import SensorFamily, SensorCommand
    from neurosdk.scanner import Scanner

    devices = manager.scan_devices()
    if not devices:
        print("Callibri devices not found.")
        return 1
    target = pick_target(devices, address)
    if target is None:
        print("No target device.")
        return 1

    scanner = Scanner([SensorFamily.LECallibri, SensorFamily.LEKolibri])
    device = scanner.create_sensor(target)
    device.connect()
    configure_emg_device(device)

    status = OpStatus()
    samples = collections.deque(maxlen=1200)
    mems_state = {"pitch": 0.0, "roll": 0.0, "acc_mag": 0.0}
    deadzone_deg = 5.0
    angle_max = 45.0
    speed_max = 35  # пикселей за тик при сильном наклоне
    pitch_offset = 0.0
    roll_offset = 0.0

    if use_envelope:
        handle = CallibriEnvelopeDataListenerHandle()

        @EnvelopeDataCallbackCallibri
        def _env_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    samples.append(float(data[i].Sample))
            except Exception:
                pass

        _neuro_lib.addEnvelopeDataCallbackCallibri(
            device.sensor_ptr,
            _env_cb,
            ctypes.byref(handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartEnvelope)
        stream_name = "envelope"
    else:
        handle = CallibriSignalDataListenerHandle()

        @SignalCallbackCallibri
        def _sig_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    pkt = data[i]
                    n = int(pkt.SzSamples)
                    if n <= 0 or n > 256 or not pkt.Samples:
                        continue
                    arr = ctypes.cast(pkt.Samples, ctypes.POINTER(ctypes.c_double * n)).contents
                    limit = min(n, 64)
                    samples.extend(arr[j] for j in range(limit))
            except Exception:
                pass

        _neuro_lib.addSignalCallbackCallibri(
            device.sensor_ptr,
            _sig_cb,
            ctypes.byref(handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartSignal)
        stream_name = "raw signal"

    # MEMS для наклонов
    try:
        def _mems_cb(_sensor, packets):  # noqa: ANN001
            if not packets:
                return
            pkt = packets[-1]
            ax, ay, az = pkt.Accelerometer.X, pkt.Accelerometer.Y, pkt.Accelerometer.Z
            acc_mag = math.sqrt(ax * ax + ay * ay + az * az)
            pitch = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az)))
            roll = math.degrees(math.atan2(ay, az))
            mems_state["pitch"] = pitch
            mems_state["roll"] = roll
            mems_state["acc_mag"] = acc_mag

        device.memsDataReceived = _mems_cb
        if device.is_supported_command(SensorCommand.StartMEMS):
            device.exec_command(SensorCommand.StartMEMS)
    except Exception:
        pass

    thresholds = AdaptiveThresholds(mvc=0.2, baseline=0.0)  # ниже стартовых порогов
    fatigue = FatigueMonitor(fs=500)
    det_cfg = DetectorConfig(profile=profile.upper())
    if tilt_deg is not None:
        det_cfg.tilt_deg = float(tilt_deg)
    detector = GestureDetector(thresholds, fatigue, det_cfg)

    print(f"Детектор жестов: {stream_name}. Ctrl+C для выхода. Порог профиль: {profile.upper()}")

    # ----------------------- Калибровка: расслабь / сильное сжатие
    def compute_metrics():
        if samples:
            window = list(samples)[-60:]  # ~0.12 с для мгновенной реакции
            mean_val = sum(window) / len(window)
            rms_raw = math.sqrt(sum(x * x for x in window) / len(window))
            rms_centered = math.sqrt(sum((x - mean_val) ** 2 for x in window) / len(window))
            vmin, vmax = min(window), max(window)
            p2p = vmax - vmin
            rms = max(rms_raw, rms_centered, p2p)
        else:
            rms = rms_raw = rms_centered = mean_val = vmin = vmax = p2p = 0.0
        return rms, rms_raw, rms_centered, p2p, vmin, vmax

    def phase(duration, label, collect_list):
        t_end = time.time() + duration
        while time.time() < t_end:
            rms, rms_raw, rms_centered, p2p, vmin, vmax = compute_metrics()
            collect_list.append(rms)
            print(
                f"[{label}] RMS={rms:6.4f} raw={rms_raw:6.4f} cRMS={rms_centered:6.4f} p2p={p2p:6.4f} "
                f"min/max={vmin:6.4f}/{vmax:6.4f}",
                end="\r",
                flush=True,
            )
            time.sleep(0.05)
        print()  # newline после фазы

    print("Калибровка: расслабь руку 2 с...")
    baseline_samples: list[float] = []
    mvc_samples: list[float] = []
    phase(2.0, "RELAX", baseline_samples)
    print("Калибровка: сильно сожми руку 2 с...")
    phase(2.0, "MAX", mvc_samples)

    baseline_val = max(0.0, sum(baseline_samples) / len(baseline_samples)) if baseline_samples else 0.0
    mvc_val = max(baseline_val + 0.01, sum(mvc_samples) / len(mvc_samples)) if mvc_samples else baseline_val + 0.05
    gain = 12.0  # усиливаем чувствительность детектора
    baseline_g = baseline_val * gain
    mvc_g = mvc_val * gain
    thresholds.update_calibration(mvc=mvc_g, baseline=baseline_g)
    th_preview = thresholds.thresholds_for_profile(profile.upper())
    print(
        f"[Calibrated] baseline={baseline_g:.4f}, mvc={mvc_g:.4f}, on={th_preview.on:.4f}, off={th_preview.off:.4f} "
        f"(raw baseline={baseline_val:.4f}, mvc={mvc_val:.4f}, gain={gain:.1f}x)"
    )

    last_level = "LOW"
    def _mid_high(profile_name: str) -> tuple[float, float]:
        name = profile_name.upper()
        if name == "ULTRA_SENSITIVE":
            return 0.15, 0.35
        if name == "SENSITIVE":
            return 0.25, 0.5
        return 0.35, 0.7

    mid_ratio, high_ratio = _mid_high(profile)
    try:
        while True:
            rms, rms_raw, rms_centered, p2p, vmin, vmax = compute_metrics()
            rms_det = max(0.0, rms * gain)
            th = thresholds.thresholds_for_profile(profile.upper())
            metrics = {
                "emg_rms": rms_det,
                "pitch": mems_state["pitch"],
                "roll": mems_state["roll"],
                "yaw": mems_state.get("yaw", 0.0),
                "acc_magnitude": mems_state["acc_mag"],
            }
            events = detector.process_metrics(metrics)
            # Дополнительные уровни силы: слабое / среднее / сильное
            span = max(mvc_g - baseline_g, 1e-6)
            mid = baseline_g + span * mid_ratio
            high = baseline_g + span * high_ratio
            level = "LOW"
            if rms_det >= high:
                level = "HIGH"
            elif rms_det >= mid:
                level = "MED"
            if level != last_level and level != "LOW":
                events.append({"type": f"MUSCLE_{level}", "value": rms_det, "timestamp": time.time(), "duration_ms": 0})
            last_level = level

            if events:
                for ev in events:
                    print(
                        f"{ev['type']:<15} val={ev['value']:.3f} "
                        f"dur={ev.get('duration_ms', 0)}ms t={ev['timestamp']:.3f}"
                    )
            indicator = ">" if rms_det >= th.on else " "
            if rms_det >= high:
                indicator = ">>"
            elif rms_det >= mid:
                indicator = "> "
            print(
                f"{indicator} RMS(det)={rms_det:6.4f} RMS={rms:6.4f} raw={rms_raw:6.4f} cRMS={rms_centered:6.4f} "
                f"p2p={p2p:6.4f} min/max={vmin:6.4f}/{vmax:6.4f} "
                f"baseline={baseline_g:6.4f} mvc={mvc_g:6.4f} on/off={th.on:6.4f}/{th.off:6.4f} "
                f"mid/high={mid:6.4f}/{high:6.4f} level={level}"
            )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("Остановка детектора...")
    finally:
        with contextlib.suppress(Exception):
            if use_envelope:
                device.exec_command(SensorCommand.StopEnvelope)
            else:
                device.exec_command(SensorCommand.StopSignal)
        with contextlib.suppress(Exception):
            device.disconnect()
    return 0


def run_diag_emg(
    manager: SensorManager,
    address: Optional[str],
    use_envelope: bool,
    enable_orientation: bool,
    seconds: float = 3.0,
) -> int:
    import ctypes
    import statistics
    import contextlib
    import math
    from neurosdk.neuro_lib_load import _neuro_lib
    from neurosdk.cmn_types import SensorFamily, SensorCommand
    from neurosdk.__cmn_types import (
        CallibriEnvelopeDataListenerHandle,
        CallibriSignalDataListenerHandle,
        EnvelopeDataCallbackCallibri,
        OpStatus,
        SignalCallbackCallibri,
    )
    from neurosdk.scanner import Scanner

    scanner = Scanner([SensorFamily.LECallibri, SensorFamily.LEKolibri])
    devices = manager.scan_devices()
    if not devices:
        print("Callibri devices not found.")
        return 1
    target = pick_target(devices, address)
    if target is None:
        print("No target device.")
        return 1
    device = scanner.create_sensor(target)
    device.connect()
    configure_emg_device(device)

    samples = []
    status = OpStatus()
    cb_handle = None

    if use_envelope:
        cb_handle = CallibriEnvelopeDataListenerHandle()

        @EnvelopeDataCallbackCallibri
        def _env_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    samples.append(float(data[i].Sample))
            except Exception:
                pass

        _neuro_lib.addEnvelopeDataCallbackCallibri(
            device.sensor_ptr,
            _env_cb,
            ctypes.byref(cb_handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartEnvelope)
        stream_name = "envelope"
    else:
        cb_handle = CallibriSignalDataListenerHandle()

        @SignalCallbackCallibri
        def _sig_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    pkt = data[i]
                    count = int(pkt.SzSamples)
                    if count <= 0 or count > 256 or not pkt.Samples:
                        continue
                    try:
                        arr = ctypes.cast(pkt.Samples, ctypes.POINTER(ctypes.c_double * count)).contents
                        limit = min(count, 32)
                        samples.extend(arr[j] for j in range(limit))
                    except Exception:
                        continue
            except Exception:
                pass

        _neuro_lib.addSignalCallbackCallibri(
            device.sensor_ptr,
            _sig_cb,
            ctypes.byref(cb_handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartSignal)
        stream_name = "raw signal"

    print(f"Диагностика EMG ({stream_name}), {seconds} с...")
    time.sleep(seconds)

    with contextlib.suppress(Exception):
        if use_envelope:
            device.exec_command(SensorCommand.StopEnvelope)
        else:
            device.exec_command(SensorCommand.StopSignal)
    with contextlib.suppress(Exception):
        device.disconnect()

    if not samples:
        print("Нет данных EMG.")
        return 1

    rms = math.sqrt(sum(x * x for x in samples) / len(samples))
    print(f"EMG samples: {len(samples)}, min={min(samples):.4f}, max={max(samples):.4f}, mean={statistics.mean(samples):.4f}, rms={rms:.4f}")
    return 0


def run_control(
    manager: SensorManager,
    address: Optional[str],
    use_envelope: bool,
    enable_orientation: bool,
    profile: str,
    control_profile: str,
    mouse_speed: Optional[float] = None,
    mouse_deadzone: Optional[float] = None,
    mouse_angle_max: Optional[float] = None,
    invert_x: bool = False,
    invert_y: bool = False,
    swap_axes: bool = False,
    mouse_use_yaw: bool = False,
    move_threshold: Optional[float] = None,
    move_gate: float = 1.0,
    move_hold_ms: int = 50,
    tilt_deg: Optional[float] = None,
    sensor_reversed: bool = False,
) -> int:
    # Lazy imports to avoid requiring pynput when не используем управление
    from callibri_control.control.profiles import ProfileManager
    from callibri_control.control.keyboard_emulator import KeyboardEmulator
    from callibri_control.control.mouse_emulator import MouseEmulator, MouseAction
    from callibri_control.core.data_stream import quaternion_to_euler_deg

    import ctypes
    import collections
    import math
    from neurosdk.neuro_lib_load import _neuro_lib
    from neurosdk.__cmn_types import (
        SignalCallbackCallibri,
        CallibriSignalDataListenerHandle,
        EnvelopeDataCallbackCallibri,
        CallibriEnvelopeDataListenerHandle,
        OpStatus,
    )
    from neurosdk.cmn_types import SensorFamily, SensorCommand
    from neurosdk.scanner import Scanner

    devices = manager.scan_devices()
    if not devices:
        print("Callibri devices not found.")
        return 1
    target = pick_target(devices, address)
    if target is None:
        print("No target device.")
        return 1

    scanner = Scanner([SensorFamily.LECallibri, SensorFamily.LEKolibri])
    device = scanner.create_sensor(target)
    device.connect()

    configure_emg_device(device)

    status = OpStatus()
    samples = collections.deque(maxlen=1200)
    mems_state = {"pitch": 0.0, "roll": 0.0, "yaw": 0.0, "acc_mag": 0.0, "orientation": "acc", "updated": False}
    deadzone_deg = mouse_deadzone if mouse_deadzone is not None else 6.0
    angle_max = mouse_angle_max if mouse_angle_max is not None else 35.0
    speed_max = int(mouse_speed) if mouse_speed is not None else 35  # мягче по скорости

    if use_envelope:
        handle = CallibriEnvelopeDataListenerHandle()

        @EnvelopeDataCallbackCallibri
        def _env_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    samples.append(float(data[i].Sample))
            except Exception:
                pass

        _neuro_lib.addEnvelopeDataCallbackCallibri(
            device.sensor_ptr,
            _env_cb,
            ctypes.byref(handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartEnvelope)
        stream_name = "envelope"
    else:
        handle = CallibriSignalDataListenerHandle()

        @SignalCallbackCallibri
        def _sig_cb(ptr, data, sz, user_data):  # noqa: ANN001
            try:
                for i in range(sz):
                    pkt = data[i]
                    n = int(pkt.SzSamples)
                    if n <= 0 or n > 256 or not pkt.Samples:
                        continue
                    arr = ctypes.cast(pkt.Samples, ctypes.POINTER(ctypes.c_double * n)).contents
                    limit = min(n, 64)
                    samples.extend(arr[j] for j in range(limit))
            except Exception:
                pass

        _neuro_lib.addSignalCallbackCallibri(
            device.sensor_ptr,
            _sig_cb,
            ctypes.byref(handle),
            ctypes.py_object(device),
            ctypes.byref(status),
        )
        device.exec_command(SensorCommand.StartSignal)
        stream_name = "raw signal"

    # MEMС/ориентация для наклонов/движения курсора
    try:
        last_mems_ts = time.time()

        def _mems_cb(_sensor, packets):  # noqa: ANN001
            if not packets:
                return
            pkt = packets[-1]
            ax, ay, az = pkt.Accelerometer.X, pkt.Accelerometer.Y, pkt.Accelerometer.Z
            acc_mag = math.sqrt(ax * ax + ay * ay + az * az)
            pitch = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az)))
            roll = math.degrees(math.atan2(ay, az))
            mems_state["pitch"] = pitch
            mems_state["roll"] = roll
            mems_state["acc_mag"] = acc_mag
            mems_state["orientation"] = "acc"
            mems_state["updated"] = True
            nonlocal last_mems_ts
            last_mems_ts = time.time()

        device.memsDataReceived = _mems_cb
        if device.is_supported_command(SensorCommand.StartMEMS):
            device.exec_command(SensorCommand.StartMEMS)

        if enable_orientation and hasattr(device, "quaternionDataReceived"):
            def _quat_cb(_sensor, packets):  # noqa: ANN001
                if not packets:
                    return
                pkt = packets[-1]
                pitch, roll, yaw = quaternion_to_euler_deg(pkt.W, pkt.X, pkt.Y, pkt.Z)
                mems_state["pitch"] = pitch
                mems_state["roll"] = roll
                mems_state["yaw"] = yaw
                mems_state["orientation"] = "quat"
                mems_state["updated"] = True

            device.quaternionDataReceived = _quat_cb
            if device.is_supported_command(SensorCommand.StartAngle):
                device.exec_command(SensorCommand.StartAngle)
    except Exception:
        pass

    thresholds = AdaptiveThresholds(mvc=0.2, baseline=0.0)
    fatigue = FatigueMonitor(fs=500)
    det_cfg = DetectorConfig(profile=profile.upper(), tilt_deg=tilt_deg if tilt_deg is not None else 25.0)
    detector = GestureDetector(thresholds, fatigue, det_cfg)
    profiles = ProfileManager()
    kb = KeyboardEmulator()
    mouse = MouseEmulator()

    print(f"Контроль: профиль жестов={profile.upper()}, профиль действий={control_profile}, источник={stream_name}")
    print("Калибровка: расслабь 2с, затем сильно сожми 2с.")

    # Сбрасываем буфер и ждём первых данных, чтобы калибровка была по реальным значениям
    samples.clear()
    wait_start = time.time()
    while len(samples) < 100 and time.time() - wait_start < 2.0:
        time.sleep(0.01)
    if len(samples) < 20:
        print("Нет свежих EMG данных для калибровки (проверь контакт или попробуй --envelope).")
        return 1

    def compute_metrics():
        if samples:
            window = list(samples)[-60:]  # ~0.12 с
            mean_val = sum(window) / len(window)
            rms_raw = math.sqrt(sum(x * x for x in window) / len(window))
            rms_centered = math.sqrt(sum((x - mean_val) ** 2 for x in window) / len(window))
            vmin, vmax = min(window), max(window)
            p2p = vmax - vmin
            rms = max(rms_raw, rms_centered, p2p)
        else:
            rms = rms_raw = rms_centered = mean_val = vmin = vmax = p2p = 0.0
        return rms, rms_raw, rms_centered, p2p, vmin, vmax

    def phase(duration, label, collect_list):
        t_end = time.time() + duration
        while time.time() < t_end:
            rms, rms_raw, rms_centered, p2p, vmin, vmax = compute_metrics()
            collect_list.append(rms)
            print(
                f"[{label}] RMS={rms:6.4f} raw={rms_raw:6.4f} cRMS={rms_centered:6.4f} p2p={p2p:6.4f} "
                f"min/max={vmin:6.4f}/{vmax:6.4f}",
                end="\r",
                flush=True,
            )
            time.sleep(0.05)
        print()

    baseline_samples: list[float] = []
    mvc_samples: list[float] = []
    phase(2.0, "RELAX", baseline_samples)
    phase(2.0, "MAX", mvc_samples)
    baseline_val = max(0.0, (sum(baseline_samples) / len(baseline_samples)) if baseline_samples else 0.0)
    mvc_peak = max(mvc_samples) if mvc_samples else baseline_val
    mvc_val = max(mvc_peak, baseline_val + 0.01)  # берем пиковое значение, чтобы уловить даже короткие всплески
    span_raw = mvc_val - baseline_val
    if span_raw < 0.005:
        span_raw = 0.01
        mvc_val = baseline_val + span_raw

    # Проверка качества калибровки: если амплитуда почти нулевая, предупреждаем и выходим
    if span_raw < 1e-4:
        print("Калибровка провалилась: EMG не меняется. Проверь контакт/электроды или запусти с --envelope.")
        return 1

    # Фиксированный gain (как в рабочем варианте курсора)
    gain = 12.0

    baseline_g = baseline_val * gain
    mvc_g = mvc_val * gain
    thresholds.update_calibration(mvc=mvc_g, baseline=baseline_g)
    th_preview = thresholds.thresholds_for_profile(profile.upper())
    print(
        f"[Calibrated] baseline={baseline_g:.4f}, mvc={mvc_g:.4f}, on={th_preview.on:.4f}, off={th_preview.off:.4f} "
        f"(raw baseline={baseline_val:.4f}, mvc={mvc_val:.4f}, gain={gain:.1f}x)"
    )

    try:
        profiles.set_active(control_profile)
    except Exception:
        print(f"Профиль {control_profile} не найден, используем DEFAULT")
        profiles.set_active("DEFAULT")

    def _mid_high(profile_name: str) -> tuple[float, float]:
        name = profile_name.upper()
        if name == "ULTRA_SENSITIVE":
            return 0.15, 0.35
        if name == "SENSITIVE":
            return 0.25, 0.5
        return 0.35, 0.7

    mid_ratio, high_ratio = _mid_high(profile)
    move_thr = move_threshold if move_threshold is not None else 0.015  # более чувствительный порог (рабочий вариант)
    last_level = "LOW"
    smoothed_dx = 0.0
    smoothed_dy = 0.0
    smooth_alpha = 0.15  # более плавное сглаживание движения курсора
    # Временно отключаем EMG-гейтинг движения: курсор всегда готов двигаться по MEMS
    move_enabled = True
    move_gate_started: Optional[float] = None

    # Калибровка нейтральной ориентации (после EMG): усредняем наклон за 1с
    print("Ориентация: направь руку в нейтральную позу (как укажешь курсор) и замри на 1с...")
    ori_samples = []
    t_wait = time.time() + 3.0
    # ждём первого пакета MEMS
    while not mems_state.get("updated") and time.time() < t_wait:
        time.sleep(0.01)
    t_end_ori = time.time() + 1.2
    while time.time() < t_end_ori:
        ori_samples.append((mems_state["pitch"], mems_state["roll"], mems_state.get("yaw", 0.0)))
        time.sleep(0.02)
    if ori_samples:
        pitch_offset = sum(p for p, _, _ in ori_samples) / len(ori_samples)
        roll_offset = sum(r for _, r, _ in ori_samples) / len(ori_samples)
        yaw_offset = sum(y for _, _, y in ori_samples) / len(ori_samples)
    else:
        pitch_offset = mems_state["pitch"]
        roll_offset = mems_state["roll"]
        yaw_offset = mems_state["yaw"]
    print(f"[Orientation] pitch0={pitch_offset:.2f} roll0={roll_offset:.2f}")
    if swap_axes:
        roll_offset, pitch_offset = pitch_offset, roll_offset

    # Выбор осей для X/Y: по умолчанию roll->X, pitch->Y; при явном флаге можно брать yaw для X
    try:
        while True:
            rms, rms_raw, rms_centered, p2p, vmin, vmax = compute_metrics()
            rms_det = rms * gain
            th = thresholds.thresholds_for_profile(profile.upper())
            metrics = {
                "emg_rms": rms_det,
                "pitch": mems_state["pitch"],
                "roll": mems_state["roll"],
                "acc_magnitude": mems_state["acc_mag"],
            }
            span = max(mvc_g - baseline_g, 1e-6)
            mid = baseline_g + span * mid_ratio
            high = baseline_g + span * high_ratio
            level = "LOW"
            if rms_det >= high:
                level = "HIGH"
            elif rms_det >= mid:
                level = "MED"
            if level != last_level and level != "LOW":
                events_level = [{"type": f"MUSCLE_{level}", "value": rms_det, "timestamp": time.time(), "duration_ms": 0}]
            else:
                events_level = []
            last_level = level

            # EMG-гейтинг отключен: курсор всегда активен (управление только MEMS)
            move_enabled = True

            events = detector.process_metrics(metrics) + events_level
            for ev in events:
                action = profiles.get_action(ev["type"])
                if not action:
                    continue
                if action.get("type") == "macro":
                    for step in action.get("steps", []):
                        if step.get("type") == "keyboard":
                            kb.execute(profiles.mapper.to_keyboard_action(step))  # type: ignore[arg-type]
                        elif step.get("type") == "mouse":
                            mouse.execute(profiles.mapper.to_mouse_action(step))  # type: ignore[arg-type]
                        time.sleep(step.get("delay", 0) / 1000 if isinstance(step, dict) else 0)
                elif action.get("type") == "keyboard":
                    kb.execute(profiles.mapper.to_keyboard_action(action))  # type: ignore[arg-type]
                elif action.get("type") == "mouse":
                    mouse.execute(profiles.mapper.to_mouse_action(action))  # type: ignore[arg-type]
                print(f"{ev['type']} -> {action}")

            # Плавное движение курсора, только когда move_enabled=True и MEMS свежий
            if control_profile.upper() == "MOUSE_CONTROL" and move_enabled and mems_state.get("updated"):
                def _axis(angle: float, offset: float) -> int:
                    angle -= offset
                    if abs(angle) <= deadzone_deg:
                        return 0
                    sign = 1 if angle > 0 else -1
                    norm = min((abs(angle) - deadzone_deg) / max(angle_max - deadzone_deg, 1e-3), 1.0)
                    return int(sign * speed_max * norm)

                roll_angle = mems_state["roll"]
                pitch_angle = mems_state["pitch"]
                yaw_angle = mems_state.get("yaw", 0.0)
                orient_src = mems_state.get("orientation", "acc")
                if swap_axes:
                    roll_angle, pitch_angle = pitch_angle, roll_angle

                if sensor_reversed:
                    roll_angle = -roll_angle
                    pitch_angle = -pitch_angle
                    yaw_angle = -yaw_angle

                use_yaw = mouse_use_yaw and orient_src == "quat"
                dx_angle = yaw_angle if use_yaw else roll_angle
                dx_off = yaw_offset if use_yaw else roll_offset
                dx = _axis(dx_angle, dx_off)
                dy = -_axis(pitch_angle, pitch_offset)  # наклон вперёд = движение вверх

                if invert_x:
                    dx = -dx
                if invert_y:
                    dy = -dy

                smoothed_dx = smoothed_dx * (1 - smooth_alpha) + dx * smooth_alpha
                smoothed_dy = smoothed_dy * (1 - smooth_alpha) + dy * smooth_alpha
                move_dx = int(round(smoothed_dx))
                move_dy = int(round(smoothed_dy))
                # вторичный deadzone после сглаживания, чтобы убрать дрейф
                if abs(move_dx) < 1:
                    move_dx = 0
                if abs(move_dy) < 1:
                    move_dy = 0

                if move_dx or move_dy:
                    mouse.execute(MouseAction(kind="MOVE", delta=(move_dx, move_dy)))

            indicator = ">" if rms_det >= th.on else " "
            if rms_det >= high:
                indicator = ">>"
            elif rms_det >= mid:
                indicator = "> "
            print(
                f"{indicator} RMS(det)={rms_det:6.4f} RMS={rms:6.4f} raw={rms_raw:6.4f} cRMS={rms_centered:6.4f} "
                f"p2p={p2p:6.4f} min/max={vmin:6.4f}/{vmax:6.4f} "
                f"baseline={baseline_g:6.4f} mvc={mvc_g:6.4f} on/off={th.on:6.4f}/{th.off:6.4f} "
                f"mid/high={mid:6.4f}/{high:6.4f} level={level} move={'ON' if move_enabled else 'OFF'}"
            )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("Остановка контроля...")
    finally:
        with contextlib.suppress(Exception):
            if use_envelope:
                device.exec_command(SensorCommand.StopEnvelope)
            else:
                device.exec_command(SensorCommand.StopSignal)
        with contextlib.suppress(Exception):
            device.exec_command(SensorCommand.StopMEMS)
        with contextlib.suppress(Exception):
            if enable_orientation and device.is_supported_command(SensorCommand.StopAngle):
                device.exec_command(SensorCommand.StopAngle)
    with contextlib.suppress(Exception):
        device.disconnect()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="CallibriControl entry point (SDK baseline + stream)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan", action="store_true", help="Scan for Callibri devices")
    mode.add_argument("--connect", action="store_true", help="Connect to a Callibri device")
    mode.add_argument("--stream", action="store_true", help="Stream EMG RMS (raw or envelope)")
    mode.add_argument("--calibrate", action="store_true", help="Run simple EMG calibration (baseline/MVC)")
    mode.add_argument("--detect", action="store_true", help="Debug gesture detector (prints detected gestures)")
    mode.add_argument("--diag-emg", action="store_true", help="Diagnose EMG stream stats (raw or envelope)")
    mode.add_argument("--control", action="store_true", help="Run control loop: detect gestures and execute actions")
    parser.add_argument("--gui", action="store_true", help="Запуск GUI")
    parser.add_argument("--web", action="store_true", help="Запуск веб-интерфейса (SSE + статика)")
    parser.add_argument("--demo", action="store_true", help="Демо-режим без реального датчика (можно совместно с --web/--gui)")
    parser.add_argument("--address", help="Specific device address for connection")
    parser.add_argument("--envelope", action="store_true", help="Use envelope stream instead of raw signal")
    parser.add_argument(
        "--quaternion",
        action="store_true",
        help="Use quaternion stream (StartAngle). Отключено по умолчанию для стабильности.",
    )
    parser.add_argument(
        "--profile",
        default="ULTRA_SENSITIVE",
        help="Sensitivity profile for detector (ULTRA_SENSITIVE/SENSITIVE/NORMAL/GAMING/PRECISE)",
    )
    parser.add_argument("--control-profile", default="DEFAULT", help="Control profile name (DEFAULT/GAMING_WASD/etc.)")
    parser.add_argument("--mouse-speed", type=float, help="Максимальная скорость курсора (px/tick) при наклоне")
    parser.add_argument("--mouse-deadzone", type=float, help="Мёртвая зона наклона (градусы)")
    parser.add_argument("--mouse-angle-max", type=float, help="Наклон (градусы) для достижения максимальной скорости")
    parser.add_argument("--mouse-use-yaw", action="store_true", help="Использовать yaw (StartAngle/--quaternion) для оси X")
    parser.add_argument("--tilt-deg", type=float, help="Порог наклона (градусы) для жестов TILT_*")
    parser.add_argument("--move-threshold", type=float, help="Порог движения курсора как доля (0..1) от диапазона MVC (пример: 0.1 = 10%)")
    parser.add_argument("--move-gate", type=float, default=1.0, help="Множитель порога EMG для включения движения курсора (меньше = чувствительнее)")
    parser.add_argument("--move-hold-ms", type=int, default=50, help="Время удержания EMG выше порога перед включением движения")
    parser.add_argument("--invert-x", action="store_true", help="Инвертировать ось X (ролл вправо -> влево)")
    parser.add_argument("--invert-y", action="store_true", help="Инвертировать ось Y (наклон вперёд -> вниз)")
    parser.add_argument("--swap-axes", action="store_true", help="Поменять местами pitch/roll для управления курсором")
    parser.add_argument("--sensor-reversed", action="store_true", help="Датчик развернут (попой вперёд): инвертировать ориентацию по осям")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--profiles", default="profiles.json", help="Path to profiles.json")
    parser.add_argument("--keybindings", default="keybindings.json", help="Path to keybindings.json")
    parser.add_argument("--web-port", type=int, default=8765, help="Порт веб-интерфейса (по умолчанию 8765)")
    parser.add_argument("--web-host", default="0.0.0.0", help="Адрес привязки веб-сервера")

    args = parser.parse_args()

    # Простая проверка на конфликт режимов: одновременно можно только один "основной" (cli/web/gui)
    primary = [args.web, args.gui, args.scan, args.connect, args.stream, args.calibrate, args.detect, args.diag_emg, args.control]
    if sum(bool(x) for x in primary) > 1:
        parser.error("Выберите один режим: --web / --gui / --scan / --connect / --stream / --calibrate / --detect / --diag-emg / --control")

    # Убираем спам Qt emoji в stdout
    os.environ.setdefault("QT_LOGGING_RULES", "qt.text.emojisegmenter=false;qt.text=false")

    cfg = ConfigManager(args.config, args.profiles, args.keybindings)
    configure_logging(cfg.config.get("general", {}).get("log_level", "INFO"))

    general_cfg = cfg.config.get("general", {})
    manager = SensorManager(
        scan_timeout=general_cfg.get("scan_timeout", 5),
        reconnect=general_cfg.get("reconnect", True),
        reconnect_interval=general_cfg.get("reconnect_interval", 3),
    )

    if args.scan:
        return run_scan(manager)
    if args.connect:
        return run_connect(manager, args.address)
    if args.stream:
        return run_stream(manager, args.address, use_envelope=args.envelope, enable_orientation=args.quaternion)
    if args.calibrate:
        return run_calibrate(manager, args.address, use_envelope=args.envelope, enable_orientation=args.quaternion)
    if args.detect:
        return run_detect(
            manager,
            args.address,
            use_envelope=args.envelope,  # по умолчанию raw для большей чувствительности
            enable_orientation=False,
            profile=args.profile,
        )
    if args.diag_emg:
        return run_diag_emg(manager, args.address, use_envelope=args.envelope, enable_orientation=args.quaternion)
    if args.control:
        return run_control(
            manager,
            args.address,
            use_envelope=args.envelope,
            enable_orientation=args.quaternion,
            profile=args.profile,
            control_profile=args.control_profile,
            mouse_speed=args.mouse_speed,
            mouse_deadzone=args.mouse_deadzone,
            mouse_angle_max=args.mouse_angle_max,
            invert_x=args.invert_x,
            invert_y=args.invert_y,
            swap_axes=args.swap_axes,
            mouse_use_yaw=args.mouse_use_yaw,
            move_threshold=args.move_threshold,
            move_gate=args.move_gate,
            move_hold_ms=args.move_hold_ms,
            tilt_deg=args.tilt_deg,
            sensor_reversed=args.sensor_reversed,
        )
    if args.web:
        try:
            from callibri_control.web_server import serve_web
        except ImportError as exc:  # noqa: BLE001
            logging.error("Не удалось запустить веб-интерфейс: %s", exc)
            return 1
        if args.demo:
            cfg.config.setdefault("general", {})["demo_mode"] = True
        return serve_web(cfg, None if args.demo else manager, host=args.web_host, port=args.web_port, address=args.address)
    if args.gui:
        try:
            from callibri_control.ui.main_window import run_gui
        except ImportError as exc:  # noqa: BLE001
            logging.error("Не удалось запустить GUI: %s", exc)
            return 1
        if args.demo:
            cfg.config.setdefault("general", {})["demo_mode"] = True
        return run_gui(config=cfg, manager=None if args.demo else manager)
    if args.demo:
        cfg.config.setdefault("general", {})["demo_mode"] = True
        try:
            from callibri_control.ui.main_window import run_gui
        except ImportError as exc:  # noqa: BLE001
            logging.error("Не удалось запустить GUI: %s", exc)
            return 1
        return run_gui(config=cfg, manager=None)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
