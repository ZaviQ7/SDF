from kalshi_weather_lab.calibration import ResidualCalibrator


def test_empty_history_matches_fallback():
    estimate = ResidualCalibrator().estimate(
        "PHIL", "HIGH", "ecmwf", 3, fallback_sigma=2.0
    )
    assert estimate.bias == 0.0
    assert estimate.sigma == 2.0
    assert estimate.level == "fallback"


def test_other_cities_influence_new_city_conservatively():
    residuals = {
        (f"C{i}", "HIGH", "ecmwf", "0-6"): [1.0]
        for i in range(20)
    }
    estimate = ResidualCalibrator(residuals).estimate(
        "PHIL", "HIGH", "ecmwf", 3, fallback_sigma=2.0
    )
    assert 0.0 < estimate.bias < 1.0
    assert estimate.count == 0
    assert estimate.pooled_count == 20


def test_many_exact_samples_dominate_pooled_prior():
    residuals = {
        (f"C{i}", "HIGH", "ecmwf", "0-6"): [0.0]
        for i in range(20)
    }
    residuals[("PHIL", "HIGH", "ecmwf", "0-6")] = [2.0] * 40
    estimate = ResidualCalibrator(residuals).estimate(
        "PHIL", "HIGH", "ecmwf", 3, fallback_sigma=2.0
    )
    assert estimate.bias > 1.0
    assert estimate.count == 40
    assert estimate.level == "exact"


def test_guardrails_limit_extreme_bias_and_sigma():
    residuals = {
        ("PHIL", "LOW", "gem", "0-6"): [20.0] * 100,
    }
    estimate = ResidualCalibrator(residuals).estimate(
        "PHIL", "LOW", "gem", 3, fallback_sigma=2.0
    )
    assert estimate.bias == 4.0
    assert 0.75 <= estimate.sigma <= 5.0
