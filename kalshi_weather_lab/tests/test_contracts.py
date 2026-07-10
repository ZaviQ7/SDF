from kalshi_weather_lab.contracts import parse_contract_rule, validate_partition


def test_common_weather_contract_phrases():
    assert parse_contract_rule("79 or below").upper == 79
    assert parse_contract_rule("80 to 81").lower == 80
    assert parse_contract_rule("greater than 95").lower == 96
    assert parse_contract_rule("less than 88").upper == 87


def test_exhaustive_partition_validation():
    rules = [
        parse_contract_rule("79 or below"),
        parse_contract_rule("80 to 81"),
        parse_contract_rule("82 to 83"),
        parse_contract_rule("84 or above"),
    ]
    assert validate_partition(rules) == (True, "ok")
