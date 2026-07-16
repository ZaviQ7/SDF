from __future__ import annotations

from math import erf, floor, sqrt
from collections.abc import Sequence

from .calibration import ResidualCalibrator, conservative_probability
from .contracts import validate_partition
from .domain import ContractRule, ForecastBundle, ProbabilityEstimate, TemperatureType, ensure_probability_vector


def normal_cdf(value: float, mean: float, sigma: float) -> float:
    sigma = max(1e-9, sigma)
    return 0.5 * (1.0 + erf((value - mean) / (sigma * sqrt(2.0))))


def rule_probability_normal(rule: ContractRule, mean: float, sigma: float) -> float:
    # Integer settlement bins use half-degree continuity boundaries.
    lower_prob = 0.0 if rule.lower is None else normal_cdf(rule.lower - 0.5, mean, sigma)
    upper_prob = 1.0 if rule.upper is None else normal_cdf(rule.upper + 0.5, mean, sigma)
    return max(0.0, min(1.0, upper_prob - lower_prob))


def default_model_weights(hours_to_target: float, models: set[str]) -> dict[str, float]:
    base = {"ecmwf": 0.40, "gfs": 0.35, "icon": 0.15, "gem": 0.10}
    hrrr_weight = 0.0
    if "hrrr" in models:
        # Once the expected daily peak has arrived or passed, the observed
        # station extreme and short-range HRRR guidance should dominate.
        # Global ensembles can otherwise preserve an unrealistic warm tail.
        if hours_to_target <= 0:
            # After the expected peak, global ensemble members can retain
            # stale warm tails from earlier runs. Use nearly all weight on
            # short-range guidance, which has already been conditioned on
            # the observed station extreme.
            hrrr_weight = 0.95
        elif hours_to_target <= 3:
            hrrr_weight = 0.65
        elif hours_to_target <= 6:
            hrrr_weight = 0.55
        elif hours_to_target <= 12:
            hrrr_weight = 0.45
        elif hours_to_target <= 24:
            hrrr_weight = 0.30
        elif hours_to_target <= 36:
            hrrr_weight = 0.15
        elif hours_to_target <= 48:
            hrrr_weight = 0.05
    if hrrr_weight:
        base = {key: value * (1.0 - hrrr_weight) for key, value in base.items()}
        base["hrrr"] = hrrr_weight
    active = {key: value for key, value in base.items() if key in models}
    missing = models - set(active)
    for model in missing:
        active[model] = 0.05
    total = sum(active.values())
    return {key: value / total for key, value in active.items()}


def _fallback_sigma(model: str, hours_to_target: float, deterministic: bool) -> float:
    lead_component = min(2.5, max(0.0, hours_to_target) * 0.025)
    base = 1.35 if model.lower() == "hrrr" else 1.10
    if deterministic:
        base += 0.45
    return base + lead_component


def event_probabilities(
    rules: Sequence[ContractRule],
    bundle: ForecastBundle,
    calibrator: ResidualCalibrator | None = None,
) -> tuple[tuple[float, ...], float]:
    ok, reason = validate_partition(rules)
    if not ok:
        raise ValueError(f"Markets do not form an exhaustive partition: {reason}")
    calibrator = calibrator or ResidualCalibrator()
    models = {forecast.model.lower() for forecast in bundle.forecasts if forecast.values}
    weights = default_model_weights(bundle.hours_to_target, models)
    probabilities = [0.0 for _ in rules]
    effective_n_inverse = 0.0

    for forecast in bundle.forecasts:
        if not forecast.values:
            continue
        model = forecast.model.lower()
        model_weight = weights.get(model, 0.0)
        if model_weight <= 0:
            continue
        error = calibrator.estimate(
            bundle.city_code,
            bundle.temp_type.value,
            model,
            bundle.hours_to_target,
            fallback_sigma=_fallback_sigma(
                model,
                bundle.hours_to_target,
                forecast.deterministic,
            ),
        )

        sigma = error.sigma

        # For same-day nowcasts, forecast values have already been rebuilt
        # from the observed station extreme plus only the remaining hours.
        # Once the expected peak is near or past, the ordinary full-day
        # residual spread is too wide and creates unrealistic warm/cold tails.
        if bundle.observed_extreme is not None:
            if bundle.hours_to_target <= 0:
                sigma = min(
                    sigma,
                    0.75 if model == "hrrr" else 1.00,
                )
            elif bundle.hours_to_target <= 3:
                sigma = min(
                    sigma,
                    1.00 if model == "hrrr" else 1.25,
                )
            elif bundle.hours_to_target <= 6:
                sigma = min(
                    sigma,
                    1.20 if model == "hrrr" else 1.50,
                )

        member_weight = model_weight / len(forecast.values)
        for value in forecast.values:
            corrected_mean = value + error.bias
            for idx, rule in enumerate(rules):
                probabilities[idx] += (
                    member_weight
                    * rule_probability_normal(
                        rule,
                        corrected_mean,
                        sigma,
                    )
                )
        # Kish-like effective sample size; model correlation prevents treating all members as independent.
        model_effective_members = 1.0 if forecast.deterministic else min(10.0, sqrt(len(forecast.values)))
        effective_n_inverse += (model_weight * model_weight) / model_effective_members

    if sum(probabilities) <= 0:
        raise ValueError("No usable forecast probabilities")

    # Apply hard same-day physical constraints from observed station extrema.
    if bundle.observed_extreme is not None:
        # NWS/Kalshi integer-temperature bins use half-degree boundaries.
        # Do not use Python round(), which applies banker's rounding:
        # round(82.5) == 82. Half degrees must move to the next integer.
        observed_rounded = int(floor(bundle.observed_extreme + 0.5))
        for idx, rule in enumerate(rules):
            if bundle.temp_type is TemperatureType.HIGH:
                # Final high cannot land below the high already observed.
                if rule.upper is not None and rule.upper < observed_rounded:
                    probabilities[idx] = 0.0
            else:
                # Final low cannot land above the low already observed.
                if rule.lower is not None and rule.lower > observed_rounded:
                    probabilities[idx] = 0.0

    normalized = ensure_probability_vector(probabilities)
    effective_n = 1.0 / effective_n_inverse if effective_n_inverse > 0 else 1.0
    return normalized, effective_n


def estimate_markets(
    tickers: Sequence[str],
    rules: Sequence[ContractRule],
    bundle: ForecastBundle,
    calibrator: ResidualCalibrator | None = None,
    *,
    calibration_error_floor: float = 0.035,
    confidence_z: float = 1.0,
) -> tuple[ProbabilityEstimate, ...]:
    probs, effective_n = event_probabilities(rules, bundle, calibrator)
    results = []
    for ticker, probability in zip(tickers, probs, strict=True):
        conservative, penalty = conservative_probability(
            probability,
            effective_n,
            calibration_error_floor=calibration_error_floor,
            confidence_z=confidence_z,
        )
        results.append(
            ProbabilityEstimate(
                ticker=ticker,
                raw_yes=probability,
                conservative_yes=conservative,
                effective_sample_size=effective_n,
                uncertainty_penalty=penalty,
            )
        )
    return tuple(results)
