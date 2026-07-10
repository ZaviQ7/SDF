from datetime import date

from kalshi_weather_lab.contracts import parse_contract_rule
from kalshi_weather_lab.domain import ForecastBundle, ModelForecast, TemperatureType
from kalshi_weather_lab.probability import event_probabilities


def test_probabilities_are_deterministic_and_sum_to_one():
    rules = [
        parse_contract_rule("79 or below"),
        parse_contract_rule("80 to 81"),
        parse_contract_rule("82 to 83"),
        parse_contract_rule("84 or above"),
    ]
    bundle = ForecastBundle(
        "X",
        date(2026, 7, 9),
        TemperatureType.HIGH,
        8,
        (
            ModelForecast("ecmwf", (81.5, 82.5, 83.0)),
            ModelForecast("hrrr", (82.0,), deterministic=True),
        ),
    )
    first, n1 = event_probabilities(rules, bundle)
    second, n2 = event_probabilities(rules, bundle)
    assert first == second
    assert n1 == n2
    assert abs(sum(first) - 1.0) < 1e-12


def test_observed_high_eliminates_lower_outcomes():
    rules = [
        parse_contract_rule("79 or below"),
        parse_contract_rule("80 to 81"),
        parse_contract_rule("82 to 83"),
        parse_contract_rule("84 or above"),
    ]
    bundle = ForecastBundle(
        "X",
        date(2026, 7, 9),
        TemperatureType.HIGH,
        3,
        (ModelForecast("hrrr", (83.0,), deterministic=True),),
        observed_extreme=84.0,
    )
    probs, _ = event_probabilities(rules, bundle)
    assert probs[:3] == (0.0, 0.0, 0.0)
    assert probs[3] == 1.0
