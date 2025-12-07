import contextlib
import ctypes
import logging
import threading
import time
from typing import Dict, List, Optional

from neurosdk.callibri_sensor import (
    CallibriSignalType,
    SensorDataOffset,
    SensorExternalSwitchInput,
    SensorGain,
    SensorADCInput,
    SensorSamplingFrequency,
)
from neurosdk.cmn_types import SensorFamily, SensorInfo, SensorState
from neurosdk.scanner import Scanner
from neurosdk.neuro_lib_load import _neuro_lib
from neurosdk.__cmn_types import OpStatus


class SensorManager:
    """
    Обёртка над SDK: сканирование, подключение и автопереподключение Callibri.
    Все операции подключения выполняются в отдельном потоке, чтобы не блокировать UI.
    """

    def __init__(
        self,
        scan_timeout: int = 5,
        reconnect: bool = True,
        reconnect_interval: int = 3,
        families: Optional[List[SensorFamily]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.scan_timeout = scan_timeout
        self.reconnect = reconnect
        self.reconnect_interval = reconnect_interval
        self._logger = logger or logging.getLogger(__name__)
        self._families = families or [SensorFamily.LECallibri, SensorFamily.LEKolibri]
        self._scanner = Scanner(self._families)

        self._device = None
        self._device_info: Optional[SensorInfo] = None
        self._target_info: Optional[SensorInfo] = None
        self._state: Optional[SensorState] = None
        self._electrode_state: Optional[str] = None

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._connect_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ Public API
    def scan_devices(self, timeout: Optional[int] = None) -> List[Dict[str, str]]:
        """Ищет доступные Callibri по BLE и возвращает список словарей."""
        duration = timeout or self.scan_timeout
        try:
            self._scanner.start()
        except Exception as exc:  # noqa: BLE001
            self._logger.error("Не удалось запустить сканер: %s", exc)
            return []

        time.sleep(max(duration, 0.5))
        devices: List[Dict[str, str]] = []
        try:
            for sensor in self._scanner.sensors():
                devices.append(
                    {
                        "name": sensor.Name,
                        "address": sensor.Address,
                        "rssi": sensor.RSSI,
                        "sensor_info": sensor,
                    }
                )
        finally:
            with contextlib.suppress(Exception):
                self._scanner.stop()
        return devices

    def connect(self, target: SensorInfo, wait: bool = False, timeout: Optional[float] = None) -> bool:
        """
        Подключается синхронно (стабильно для macOS), возвращает успех/неуспех.
        """
        with self._lock:
            self._target_info = target
            self._device_info = target
            self._stop_event.clear()
            self._connected_event.clear()

        try:
            device = self._scanner.create_sensor(target)
            self._logger.info("Подключение к %s (%s)...", target.Name, target.Address)
            device.sensorStateChanged = self._on_state_change
            if hasattr(device, "electrodeStateChanged"):
                device.electrodeStateChanged = self._on_electrode_state
            device.connect()
            self._configure_callibri(device)
            if hasattr(device, "set_electrode_callbacks"):
                with contextlib.suppress(Exception):
                    device.set_electrode_callbacks()
            with self._lock:
                self._device = device
                self._state = SensorState.StateInRange
            self._connected_event.set()
            return True
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Не удалось подключиться: %s", exc)
            with self._lock:
                self._device = None
                self._state = SensorState.StateOutOfRange
            return False

    def wait_for_connection(self, timeout: Optional[float] = None) -> bool:
        """Блокирует поток до подключения или таймаута."""
        return self._connected_event.wait(timeout)

    def disconnect(self) -> None:
        """Корректно отключает устройство и останавливает попытки переподключения."""
        self._stop_event.set()
        self._connected_event.clear()
        with self._lock:
            device = self._device
            self._device = None
            self._state = SensorState.StateOutOfRange
            thread = self._connect_thread
        if device is not None:
            with contextlib.suppress(Exception):
                device.disconnect()
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    def is_connected(self) -> bool:
        with self._lock:
            return self._state == SensorState.StateInRange

    def get_device(self):
        with self._lock:
            return self._device

    def get_device_info(self) -> Optional[Dict[str, str]]:
        with self._lock:
            device = self._device
            info = self._device_info
        if device is None or info is None:
            return None

        result = {
            "name": info.Name,
            "address": info.Address,
            "serial": info.SerialNumber,
        }
        try:
            result["battery"] = str(device.batt_power)
        except Exception:
            result["battery"] = "n/a"
        try:
            version = device.version
            result["firmware"] = f"{version.FwMajor}.{version.FwMinor}.{version.FwPatch}"
        except Exception:
            result["firmware"] = "n/a"
        return result

    def get_electrode_state(self) -> Optional[str]:
        with self._lock:
            return self._electrode_state

    # ------------------------------------------------------------------ Internal
    def _connect_loop(self) -> None:
        while not self._stop_event.is_set():
            target = self._target_info
            if target is None:
                return

            try:
                device = self._scanner.create_sensor(target)
                self._logger.info("Подключение к %s (%s)...", target.Name, target.Address)
                device.sensorStateChanged = self._on_state_change
                if hasattr(device, "electrodeStateChanged"):
                    device.electrodeStateChanged = self._on_electrode_state
                device.connect()
                self._configure_callibri(device)
                if hasattr(device, "set_electrode_callbacks"):
                    with contextlib.suppress(Exception):
                        device.set_electrode_callbacks()
                with self._lock:
                    self._device = device
                    self._state = SensorState.StateInRange
                self._connected_event.set()
                return
            except Exception as exc:  # noqa: BLE001
                self._logger.warning("Не удалось подключиться: %s", exc)
                with self._lock:
                    self._device = None
            if not self.reconnect:
                return
            if self._stop_event.wait(self.reconnect_interval):
                return

    def _on_state_change(self, sensor, state: SensorState) -> None:
        self._logger.info("Состояние датчика: %s", state)
        with self._lock:
            self._state = state
            if state == SensorState.StateInRange:
                self._device = sensor
                self._connected_event.set()
            else:
                self._device = None
                self._connected_event.clear()

        if state == SensorState.StateOutOfRange and not self._stop_event.is_set() and self.reconnect:
            self._logger.info("Потеря связи. Пытаемся переподключиться через %s с", self.reconnect_interval)
            self._start_reconnect()

    def _on_electrode_state(self, sensor, state) -> None:  # noqa: ANN001
        try:
            name = getattr(state, "name", str(state))
        except Exception:
            name = str(state)
        with self._lock:
            self._electrode_state = name
        self._logger.info("Состояние электродов: %s", name)

    def _start_reconnect(self) -> None:
        with self._lock:
            already_running = self._connect_thread and self._connect_thread.is_alive()
        if already_running:
            return
        self._connect_thread = threading.Thread(target=self._connect_loop, daemon=True)
        self._connect_thread.start()

    def _configure_callibri(self, device) -> None:
        """Базовая конфигурация; оставляем заводские настройки для стабильности."""
        try:
            with contextlib.suppress(Exception):
                device.signal_type = CallibriSignalType.EMG
            with contextlib.suppress(Exception):
                device.ext_sw_input = SensorExternalSwitchInput.Electrodes
            with contextlib.suppress(Exception):
                device.adc_input = SensorADCInput.Electrodes
            with contextlib.suppress(Exception):
                device.gain = SensorGain.Gain12
            with contextlib.suppress(Exception):
                device.sampling_frequency = SensorSamplingFrequency.FrequencyHz500
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("Не удалось применить настройки Callibri: %s", exc)
