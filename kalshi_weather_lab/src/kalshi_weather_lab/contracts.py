from __future__ import annotations

import re
from collections.abc import Sequence

from .domain import ContractRule

_NUM = r"(-?\d+)"


def parse_contract_rule(text: str) -> ContractRule:
    clean = text.replace("°F", "").replace("°", "").replace("&deg;", "")
    clean = re.sub(r"\s+", " ", clean).strip()

    patterns: list[tuple[str, callable]] = [
        # Symbol forms used by current Kalshi weather titles, such as ">96°".
        (rf">=\s*{_NUM}", lambda m: (int(m.group(1)), None)),
        (rf"<=\s*{_NUM}", lambda m: (None, int(m.group(1)))),
        (rf">\s*{_NUM}", lambda m: (int(m.group(1)) + 1, None)),
        (rf"<\s*{_NUM}", lambda m: (None, int(m.group(1)) - 1)),
        (rf"{_NUM}\s*(?:to|through|[-–—])\s*{_NUM}", lambda m: (int(m.group(1)), int(m.group(2)))),
        (rf"{_NUM}\s*(?:or|and)\s*(?:below|lower|less)", lambda m: (None, int(m.group(1)))),
        (rf"{_NUM}\s*(?:or|and)\s*(?:above|higher|more)", lambda m: (int(m.group(1)), None)),
        (rf"(?:less than|below|under)\s*{_NUM}", lambda m: (None, int(m.group(1)) - 1)),
        (rf"(?:greater than|above|over)\s*{_NUM}", lambda m: (int(m.group(1)) + 1, None)),
        (rf"(?:at least)\s*{_NUM}", lambda m: (int(m.group(1)), None)),
        (rf"(?:at most|no more than)\s*{_NUM}", lambda m: (None, int(m.group(1)))),
        (rf"(?:between)\s*{_NUM}\s*(?:and|to)\s*{_NUM}", lambda m: (int(m.group(1)), int(m.group(2)))),
    ]
    lower_text = clean.lower()
    for pattern, converter in patterns:
        match = re.search(pattern, lower_text, flags=re.IGNORECASE)
        if match:
            lower, upper = converter(match)
            if lower is not None and upper is not None and lower > upper:
                lower, upper = upper, lower
            return ContractRule(lower=lower, upper=upper, label=clean)
    raise ValueError(f"Unable to parse temperature contract rule from: {text!r}")


def validate_partition(rules: Sequence[ContractRule]) -> tuple[bool, str]:
    if not rules:
        return False, "no rules"
    ordered = sorted(rules, key=lambda r: float("-inf") if r.lower is None else r.lower)
    if ordered[0].lower is not None:
        return False, "partition has no lower open-ended bracket"
    if ordered[-1].upper is not None:
        return False, "partition has no upper open-ended bracket"
    previous = ordered[0]
    for current in ordered[1:]:
        if previous.upper is None:
            return False, "an open-ended upper bracket appears before the final bracket"
        if current.lower is None:
            return False, "multiple lower open-ended brackets"
        if current.lower <= previous.upper:
            return False, f"overlap between {previous.label!r} and {current.label!r}"
        if current.lower != previous.upper + 1:
            return False, f"gap between {previous.label!r} and {current.label!r}"
        previous = current
    return True, "ok"
