import copy
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG: Dict[str, Any] = {
    "general": {
        "autoconnect": True,
        "scan_timeout": 5,
        "reconnect": True,
        "reconnect_interval": 3,
        "log_level": "INFO",
        "demo_mode": False,
        "language": "ru",
    },
    "sensor": {
        "emg_sampling_rate": 500,
        "notch_frequency": 50,
    },
    "control": {
        "profile": "DEFAULT",
    },
    "ui": {
        "theme": "dark",
    },
    "recognition": {
        "sensitivity_profile": "NORMAL",
        "debounce_ms": 250,
        "min_confidence": 0.6,
    },
    "paths": {
        "logs": "logs",
        "sessions": "sessions",
    },
}


DEFAULT_PROFILES: Dict[str, Any] = {
    "default": {
        "name": "Default",
        "mapping": "default",
        "sensitivity_profile": "NORMAL",
    }
}


DEFAULT_KEYBINDINGS: Dict[str, str] = {
    "start_stop": "ctrl+alt+s",
    "switch_profile": "ctrl+alt+p",
}


class ConfigManager:
    """
    Управление конфигурацией приложения: загрузка, валидация, автосохранение.
    Раздельные файлы: основной конфиг, профили, привязки клавиш.
    """

    def __init__(
        self,
        config_path: str = "config.json",
        profiles_path: str = "profiles.json",
        keybindings_path: str = "keybindings.json",
        autosave: bool = True,
    ) -> None:
        self.config_path = Path(config_path)
        self.profiles_path = Path(profiles_path)
        self.keybindings_path = Path(keybindings_path)
        self.autosave = autosave
        self._lock = threading.RLock()
        self._logger = logging.getLogger(__name__)

        self.config: Dict[str, Any] = {}
        self.profiles: Dict[str, Any] = {}
        self.keybindings: Dict[str, str] = {}

        self.load_all()
        self.validate_all()

    # Public API ------------------------------------------------------------
    def load_all(self) -> None:
        with self._lock:
            self.config = self._load_file(self.config_path, DEFAULT_CONFIG)
            self.profiles = self._load_file(self.profiles_path, DEFAULT_PROFILES)
            self.keybindings = self._load_file(self.keybindings_path, DEFAULT_KEYBINDINGS)

    def validate_all(self) -> None:
        """Проверяет значения конфигов и сбрасывает в дефолт, если они вне допустимых границ."""
        with self._lock:
            changed = self._validate_config()
            if self.autosave and changed:
                self.save_all()

    def save_all(self) -> None:
        with self._lock:
            self._save_file(self.config_path, self.config)
            self._save_file(self.profiles_path, self.profiles)
            self._save_file(self.keybindings_path, self.keybindings)

    def set_config_value(self, dotted_key: str, value: Any) -> None:
        self._set_nested(self.config, DEFAULT_CONFIG, dotted_key, value)
        if self.autosave:
            self._save_file(self.config_path, self.config)

    def set_profile(self, name: str, profile: Dict[str, Any]) -> None:
        with self._lock:
            defaults = DEFAULT_PROFILES.get("default", {})
            self.profiles[name] = self._merge_defaults(profile, defaults)
            if self.autosave:
                self._save_file(self.profiles_path, self.profiles)

    def set_keybinding(self, action: str, binding: str) -> None:
        with self._lock:
            self.keybindings[action] = binding
            if self.autosave:
                self._save_file(self.keybindings_path, self.keybindings)

    # Helpers ---------------------------------------------------------------
    def _load_file(self, path: Path, defaults: Dict[str, Any]) -> Dict[str, Any]:
        if not path.exists():
            data = copy.deepcopy(defaults)
            if self.autosave:
                self._save_file(path, data)
            return data

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Failed to read %s, using defaults. Error: %s", path, exc)
            return copy.deepcopy(defaults)

        if not isinstance(data, dict):
            self._logger.warning("Invalid config format in %s, expected object.", path)
            return copy.deepcopy(defaults)

        return self._merge_defaults(data, defaults)

    def _save_file(self, path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2, ensure_ascii=True)
        path.write_text(content, encoding="utf-8")

    def _merge_defaults(self, data: Dict[str, Any], defaults: Dict[str, Any]) -> Dict[str, Any]:
        merged = copy.deepcopy(defaults)
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(defaults.get(key), dict):
                merged[key] = self._merge_defaults(value, defaults[key])  # type: ignore[arg-type]
            else:
                default_value = defaults.get(key)
                if default_value is None or isinstance(value, type(default_value)):
                    merged[key] = value
                else:
                    self._logger.warning(
                        "Invalid type for '%s'. Expected %s, got %s. Using default.",
                        key,
                        type(default_value).__name__,
                        type(value).__name__,
                    )
        return merged

    def _set_nested(self, target: Dict[str, Any], defaults: Dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        with self._lock:
            node = target
            default_node = defaults
            for part in parts[:-1]:
                default_node = default_node.get(part, {})
                if not isinstance(default_node, dict):
                    raise KeyError(f"Key '{part}' not in defaults")
                if part not in node or not isinstance(node[part], dict):
                    node[part] = {}
                node = node[part]
            if parts[-1] not in default_node:
                raise KeyError(f"Key '{parts[-1]}' not in defaults")
            expected = default_node[parts[-1]]
            if expected is not None and not isinstance(value, type(expected)):
                raise TypeError(f"Expected {type(expected).__name__} for '{parts[-1]}', got {type(value).__name__}")
            node[parts[-1]] = value

    def _validate_config(self) -> bool:
        """Проверки базовых параметров (частоты, пороги). Возвращает True, если были исправления."""
        changed = False
        sensor_cfg = self.config.get("sensor", {})
        if sensor_cfg.get("emg_sampling_rate") not in (250, 500, 1000):
            sensor_cfg["emg_sampling_rate"] = DEFAULT_CONFIG["sensor"]["emg_sampling_rate"]
            changed = True
        if sensor_cfg.get("notch_frequency") not in (50, 60):
            sensor_cfg["notch_frequency"] = DEFAULT_CONFIG["sensor"]["notch_frequency"]
            changed = True

        general_cfg = self.config.get("general", {})
        if general_cfg.get("scan_timeout", 0) <= 0:
            general_cfg["scan_timeout"] = DEFAULT_CONFIG["general"]["scan_timeout"]
            changed = True
        if general_cfg.get("reconnect_interval", 0) <= 0:
            general_cfg["reconnect_interval"] = DEFAULT_CONFIG["general"]["reconnect_interval"]
            changed = True

        recognition_cfg = self.config.get("recognition", {})
        min_conf = recognition_cfg.get("min_confidence", 0.0)
        if not isinstance(min_conf, (int, float)) or not 0.0 <= min_conf <= 1.0:
            recognition_cfg["min_confidence"] = DEFAULT_CONFIG["recognition"]["min_confidence"]
            changed = True

        ui_cfg = self.config.get("ui", {})
        if ui_cfg.get("theme") not in ("dark", "light", "contrast"):
            ui_cfg["theme"] = DEFAULT_CONFIG["ui"]["theme"]
            changed = True

        control_cfg = self.config.get("control", {})
        if not isinstance(control_cfg.get("profile"), str):
            control_cfg["profile"] = DEFAULT_CONFIG["control"]["profile"]
            changed = True

        return changed
