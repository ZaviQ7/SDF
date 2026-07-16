from kalshi_weather_lab.domain import TemperatureType
from kalshi_weather_lab.nws import NWSClient
from kalshi_weather_lab.probability import default_model_weights


def test_precise_metar_temperature():
    raw = (
        "KSEA 152253Z 27009KT 10SM FEW050 "
        "28/09 A3001 RMK AO2 T02780094"
    )
    values = NWSClient._raw_metar_temperatures(
        raw,
        TemperatureType.HIGH,
    )
    assert round(max(values), 2) == 82.04


def test_six_hour_maximum_temperature():
    # 29.4 C = 84.92 F, reported as the period maximum.
    raw = (
        "KSEA 142353Z 27008KT 10SM CLR "
        "RMK AO2 T02890094 10294 20189"
    )
    high_values = NWSClient._raw_metar_temperatures(
        raw,
        TemperatureType.HIGH,
    )
    low_values = NWSClient._raw_metar_temperatures(
        raw,
        TemperatureType.LOW,
    )

    assert round(max(high_values), 2) == 84.92
    assert round(min(low_values), 2) == 66.02


def test_twenty_four_hour_extremes():
    raw = "KSEA 160753Z RMK AO2 402940150"

    high_values = NWSClient._raw_metar_temperatures(
        raw,
        TemperatureType.HIGH,
    )
    low_values = NWSClient._raw_metar_temperatures(
        raw,
        TemperatureType.LOW,
    )

    assert round(max(high_values), 2) == 84.92
    assert round(min(low_values), 2) == 59.0


def test_hrrr_dominates_after_peak():
    weights = default_model_weights(
        -1.0,
        {"ecmwf", "gfs", "icon", "gem", "hrrr"},
    )

    assert weights["hrrr"] == 0.95
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_period_groups_can_be_excluded_from_running_extreme():
    # This 24-hour group contains an 84.92 F maximum, but a live same-day
    # calculation must retain only the instantaneous 82.04 F reading.
    raw = "KSEA 160753Z RMK AO2 T02780094 402940150"

    values = NWSClient._raw_metar_temperatures(
        raw,
        TemperatureType.HIGH,
        include_six_hour=False,
        include_twenty_four_hour=False,
    )

    assert round(max(values), 2) == 82.04


def test_post_peak_nowcast_concentrates_near_observed_extreme():
    from datetime import date

    from kalshi_weather_lab.domain import (
        ContractRule,
        ForecastBundle,
        ModelForecast,
    )
    from kalshi_weather_lab.probability import event_probabilities

    bundle = ForecastBundle(
        city_code="SEA",
        target_date=date(2026, 7, 15),
        temp_type=TemperatureType.HIGH,
        hours_to_target=-1.0,
        forecasts=(
            ModelForecast(
                model="hrrr",
                values=(82.94,),
                deterministic=True,
            ),
        ),
        observed_extreme=82.94,
    )

    rules = (
        ContractRule(None, 82, "82 or below"),
        ContractRule(83, 84, "83 to 84"),
        ContractRule(85, 86, "85 to 86"),
        ContractRule(87, None, "87 or above"),
    )

    probabilities, _ = event_probabilities(rules, bundle)

    assert probabilities[0] == 0.0
    assert probabilities[1] > 0.95
    assert probabilities[2] < 0.05
    assert probabilities[3] < 0.001
