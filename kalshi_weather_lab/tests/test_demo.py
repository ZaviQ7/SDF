from kalshi_weather_lab.demo import run_demo


def test_demo_runs():
    result = run_demo()
    assert abs(sum(row["raw_yes"] for row in result["probabilities"]) - 1.0) < 1e-12
    assert "outcome_wealth" in result
