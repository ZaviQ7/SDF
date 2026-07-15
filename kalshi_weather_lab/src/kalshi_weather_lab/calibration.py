from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import median


@dataclass(frozen=True, slots=True)
class ErrorEstimate:
    bias: float
    sigma: float
    count: int
    pooled_count: int = 0
    level: str = "fallback"


class ResidualCalibrator:
    """Hierarchical robust model-error estimator.

    Residuals are stored at the exact level
    (city, temperature type, model, lead bucket), but estimates borrow strength
    from broader groups until enough city-specific history accumulates.
    """

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

    @staticmethod
    def _robust_summary(values: list[float], prior_sigma: float) -> tuple[float, float]:
        center = float(median(values))
        if len(values) < 5:
            return center, prior_sigma
        abs_dev = [abs(value - center) for value in values]
        sigma = 1.4826 * float(median(abs_dev))
        return center, max(0.75, sigma)

    @staticmethod
    def _blend(
        prior_bias: float,
        prior_sigma: float,
        values: list[float],
        *,
        shrinkage: float,
    ) -> tuple[float, float, float]:
        if not values:
            return prior_bias, prior_sigma, 0.0
        sample_bias, sample_sigma = ResidualCalibrator._robust_summary(values, prior_sigma)
        weight = len(values) / (len(values) + shrinkage)
        bias = (1.0 - weight) * prior_bias + weight * sample_bias
        variance = (
            (1.0 - weight) * prior_sigma * prior_sigma
            + weight * sample_sigma * sample_sigma
            + weight * (1.0 - weight) * (sample_bias - prior_bias) ** 2
        )
        sigma = sqrt(max(0.75**2, variance))
        return bias, sigma, weight

    def _matching_values(
        self,
        *,
        city_code: str | None = None,
        temp_type: str | None = None,
        model: str | None = None,
        lead_bucket: str | None = None,
    ) -> list[float]:
        values: list[float] = []
        for (city, kind, model_name, lead), group in self.residuals.items():
            if city_code is not None and city != city_code:
                continue
            if temp_type is not None and kind != temp_type:
                continue
            if model is not None and model_name != model:
                continue
            if lead_bucket is not None and lead != lead_bucket:
                continue
            values.extend(group)
        return values

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
        del min_samples  # Hierarchical shrinkage replaces the old all-or-nothing threshold.
        model = model.lower()
        lead = self.lead_bucket(hours_to_target)
        exact_key = (city_code, temp_type, model, lead)
        exact_values = list(self.residuals.get(exact_key, []))

        global_type = self._matching_values(temp_type=temp_type)
        model_type = self._matching_values(temp_type=temp_type, model=model)
        model_lead = self._matching_values(
            temp_type=temp_type,
            model=model,
            lead_bucket=lead,
        )

        bias = 0.0
        sigma = max(0.75, float(fallback_sigma))
        level = "fallback"

        # Broad priors move slowly. More specific groups are allowed to exert
        # increasing influence as their sample counts grow.
        hierarchy = (
            ("global_type", global_type, 120.0),
            ("model_type", model_type, 80.0),
            ("model_lead", model_lead, 40.0),
            ("exact", exact_values, 12.0),
        )
        for group_level, values, shrinkage in hierarchy:
            bias, sigma, weight = self._blend(
                bias,
                sigma,
                values,
                shrinkage=shrinkage,
            )
            if values and weight > 0:
                level = group_level

        # Guardrails prevent a short run of unusual days from producing an
        # implausibly large correction or an unrealistically narrow forecast.
        bias = max(-4.0, min(4.0, bias))
        sigma = max(0.75, min(5.0, sigma))
        return ErrorEstimate(
            bias=bias,
            sigma=sigma,
            count=len(exact_values),
            pooled_count=len(model_lead),
            level=level,
        )


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
        key = (
            row["city_code"],
            row["temp_type"],
            row["model"].lower(),
            row["lead_bucket"],
        )
        grouped.setdefault(key, []).append(float(row["residual_f"]))
    return grouped
