from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median



@dataclass(frozen=True, slots=True)
class ErrorEstimate:
    bias: float
    sigma: float
    count: int


class ResidualCalibrator:
    """Robust model-error estimator backed by historical forecast residuals."""

    def __init__(self, residuals: dict[tuple[str, str, str, str], list[float]] | None = None):
        self.residuals = residuals or {}

    @staticmethod
    def lead_bucket(hours_to_target: float) -> str:
        if hours_to_target <= 6:
            return "0-6"
        if hours_to_target <= 12:
            return "6-12"
        if hours_to_target <= 24:
            return "12-24"
        if hours_to_target <= 48:
            return "24-48"
        return "48+"

    def estimate(
        self,
        city_code: str,
        temp_type: str,
        model: str,
        hours_to_target: float,
        *,
        fallback_sigma: float,
        min_samples: int = 20,
    ) -> ErrorEstimate:
        key = (city_code, temp_type, model.lower(), self.lead_bucket(hours_to_target))
        values = list(self.residuals.get(key, []))
        if len(values) < min_samples:
            return ErrorEstimate(0.0, fallback_sigma, len(values))
        bias = float(median(values))
        abs_dev = [abs(x - bias) for x in values]
        robust_sigma = max(0.75, 1.4826 * float(median(abs_dev)))
        return ErrorEstimate(bias, robust_sigma, len(values))


def conservative_probability(
    probability: float,
    effective_sample_size: float,
    *,
    calibration_error_floor: float = 0.035,
    confidence_z: float = 1.0,
) -> tuple[float, float]:
    p = min(1.0, max(0.0, probability))
    n_eff = max(1.0, effective_sample_size)
    sampling = confidence_z * sqrt(max(0.0, p * (1.0 - p)) / n_eff)
    penalty = min(0.25, calibration_error_floor + sampling)
    return max(0.0, p - penalty), penalty


def load_residual_rows(rows: list[dict]) -> dict[tuple[str, str, str, str], list[float]]:
    grouped: dict[tuple[str, str, str, str], list[float]] = {}
    for row in rows:
        key = (row["city_code"], row["temp_type"], row["model"].lower(), row["lead_bucket"])
        grouped.setdefault(key, []).append(float(row["residual_f"]))
    return grouped
