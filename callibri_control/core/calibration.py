import time
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np


@dataclass
class EMGCalibrationResult:
    baseline: float
    mvc: float
    thresholds: Dict[str, float]


class Calibration:
    """
    Калибровка EMG и MEMS на основе метрик из DataStream.
    """

    def __init__(self, stream) -> None:
        self.stream = stream

    def calibrate_emg(self, rest_sec: int = 3, mvc_sec: int = 3) -> EMGCalibrationResult:
        print(f"Расслабьте мышцу на {rest_sec} с...")
        baseline = self._collect(rest_sec)
        print(f"Базовый уровень: {baseline:.2f}")
        input("Готовы к MVC? Нажмите Enter и напрягите мышцу...")
        mvc = self._collect(mvc_sec)
        print(f"MVC: {mvc:.2f}")
        thresholds = self._thresholds(baseline, mvc)
        return EMGCalibrationResult(baseline=baseline, mvc=mvc, thresholds=thresholds)

    def calibrate_mems(self, duration: int = 3) -> "MemsCalibrationResult":
        """
        Калибровка MEMS: фиксируем текущие углы как нейтральные и оцениваем bias акселерометра.
        Просит положить датчик на ровную поверхность.
        """
        print("Положите датчик на ровную горизонтальную поверхность и не двигайте его.")
        print(f"Сбор данных {duration} с...")
        angles: list[Tuple[float, float, float]] = []
        accs: list[Tuple[float, float, float]] = []
        end = time.time() + duration
        while time.time() < end:
            metrics = self.stream.latest_metrics()
            pitch = metrics.get("pitch", 0.0)
            roll = metrics.get("roll", 0.0)
            yaw = metrics.get("yaw", 0.0)
            acc_x = metrics.get("acc_x", 0.0)
            acc_y = metrics.get("acc_y", 0.0)
            acc_z = metrics.get("acc_z", 0.0)
            angles.append((pitch, roll, yaw))
            accs.append((acc_x, acc_y, acc_z))
            time.sleep(0.05)
        baseline_pitch, baseline_roll, baseline_yaw = np.mean(angles, axis=0) if angles else (0.0, 0.0, 0.0)
        acc_bias = tuple(np.mean(accs, axis=0)) if accs else (0.0, 0.0, 0.0)
        result = MemsCalibrationResult(
            baseline_pitch=float(baseline_pitch),
            baseline_roll=float(baseline_roll),
            baseline_yaw=float(baseline_yaw),
            acc_bias=(float(acc_bias[0]), float(acc_bias[1]), float(acc_bias[2])),
        )
        print(
            f"MEMS нейтраль: pitch={result.baseline_pitch:.2f}, roll={result.baseline_roll:.2f}, yaw={result.baseline_yaw:.2f}"
        )
        print(
            "Смещения акселерометра (используются для вычитания гравитации): "
            f"ax={result.acc_bias[0]:.3f}, ay={result.acc_bias[1]:.3f}, az={result.acc_bias[2]:.3f}"
        )
        return result

    def _collect(self, duration: int) -> float:
        values = []
        end = time.time() + duration
        while time.time() < end:
            metrics = self.stream.latest_metrics()
            rms = metrics.get("emg_rms")
            if rms:
                values.append(rms)
            time.sleep(0.05)
        return float(np.median(values) if values else 0.0)

    def _thresholds(self, baseline: float, mvc: float) -> Dict[str, float]:
        span = max(mvc - baseline, 1e-6)
        return {
            "ULTRA_SENSITIVE": baseline + span * 0.08,
            "SENSITIVE": baseline + span * 0.18,
            "NORMAL": baseline + span * 0.35,
            "GAMING": baseline + span * 0.28,
            "PRECISE": baseline + span * 0.5,
        }


@dataclass
class MemsCalibrationResult:
    baseline_pitch: float
    baseline_roll: float
    baseline_yaw: float
    acc_bias: Tuple[float, float, float]
