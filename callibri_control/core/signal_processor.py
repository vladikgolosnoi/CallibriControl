import math
from typing import Dict, Tuple

import numpy as np
from scipy import signal


class SignalProcessor:
    """
    Обработка EMG (полосовой + notch + envelope) и MEMS (сглаживание + комплементарный фильтр).
    """

    def __init__(
        self,
        fs: int = 500,
        notch: int = 50,
        band=(20, 450),
        envelope_cutoff: int = 10,
        mems_fs: int = 100,
        mems_cutoff: float = 5.0,
        complementary_alpha: float = 0.98,
    ) -> None:
        # EMG фильтры
        self.fs = fs
        nyq = fs / 2
        low = max(1.0, band[0]) / nyq
        high = min(band[1], nyq * 0.9) / nyq
        self.b_band, self.a_band = signal.butter(4, [low, high], btype="band")
        self.b_notch, self.a_notch = signal.iirnotch(notch / nyq, 30.0)
        self.b_env, self.a_env = signal.butter(2, envelope_cutoff / nyq, btype="low")

        # MEMS фильтры/параметры
        self.mems_fs = mems_fs
        self.dt = 1.0 / float(mems_fs)
        self.complementary_alpha = complementary_alpha
        # коэффициент для простого экспоненциального сглаживания акселерометра
        rc = 1.0 / (2 * math.pi * mems_cutoff)
        self._mems_alpha = self.dt / (rc + self.dt)
        self._acc_state = np.zeros(3, dtype=float)
        self._gyro_bias = np.zeros(3, dtype=float)
        self._pitch = 0.0
        self._roll = 0.0
        self._yaw = 0.0

    # ------------------------------- EMG
    def process_emg(self, samples: np.ndarray) -> Dict[str, np.ndarray | float]:
        """Возвращает полосовой/ноутч/оболочку и RMS."""
        if samples.size == 0:
            return {"filtered": samples, "envelope": samples, "rms": 0.0}
        detr = samples - np.mean(samples)
        band = signal.lfilter(self.b_band, self.a_band, detr)
        notch = signal.lfilter(self.b_notch, self.a_notch, band)
        rect = np.abs(notch)
        env = signal.lfilter(self.b_env, self.a_env, rect)
        rms = float(np.sqrt(np.mean(env**2)))
        return {"filtered": notch, "envelope": env, "rms": rms}

    # ------------------------------- MEMS
    def process_mems(self, acc: Tuple[float, float, float], gyro: Tuple[float, float, float]) -> Dict[str, float]:
        """
        Сглаживание MEMS и комплементарный фильтр: оценивает pitch/roll/yaw.
        gyro — угл. скорость (рад/с или deg/s в зависимости от SDK), используется как есть.
        """
        acc_arr = np.asarray(acc, dtype=float)
        gyro_arr = np.asarray(gyro, dtype=float)

        # НЧ сглаживание акселерометра (экспоненциальное)
        self._acc_state = self._acc_state + self._mems_alpha * (acc_arr - self._acc_state)

        # Простая компенсация дрейфа гироскопа (скользящее смещение)
        self._gyro_bias = 0.999 * self._gyro_bias + 0.001 * gyro_arr
        gyro_corr = gyro_arr - self._gyro_bias

        # Оценка углов по акселерометру
        ax, ay, az = self._acc_state
        pitch_acc = math.degrees(math.atan2(ax, math.sqrt(ay * ay + az * az)))
        roll_acc = math.degrees(math.atan2(ay, az))

        # Комплементарный фильтр
        self._pitch = self.complementary_alpha * (self._pitch + gyro_corr[1] * self.dt) + (1 - self.complementary_alpha) * pitch_acc
        self._roll = self.complementary_alpha * (self._roll + gyro_corr[0] * self.dt) + (1 - self.complementary_alpha) * roll_acc
        self._yaw = self._yaw + gyro_corr[2] * self.dt  # без коррекции, будет дрейфовать

        acc_mag = float(math.sqrt(ax * ax + ay * ay + az * az))
        return {
            "acc_x": float(self._acc_state[0]),
            "acc_y": float(self._acc_state[1]),
            "acc_z": float(self._acc_state[2]),
            "gyro_x": float(gyro_corr[0]),
            "gyro_y": float(gyro_corr[1]),
            "gyro_z": float(gyro_corr[2]),
            "acc_magnitude": acc_mag,
            "pitch": self._pitch,
            "roll": self._roll,
            "yaw": self._yaw,
        }

    def reset_orientation(self) -> None:
        self._pitch = 0.0
        self._roll = 0.0
        self._yaw = 0.0
