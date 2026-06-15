"""Shared utilities used across bots."""

import re

# Matches: $60/hr  $65-$80/hr  $70 per hour  60/hour  $55.50/hr
_RATE_PATTERN = re.compile(
    r'\$?\s*(\d{2,3}(?:\.\d{1,2})?)'          # first number  e.g. 60
    r'(?:\s*[-–]\s*\$?\s*(\d{2,3}(?:\.\d{1,2})?))?'  # optional range end e.g. 80
    r'\s*(?:/\s*(?:hr|hour)\b|per\s+hour)',    # /hr or per hour
    re.IGNORECASE,
)


def meets_rate(description: str, min_rate: float) -> bool:
    """
    Return True if the description mentions an hourly rate >= min_rate,
    OR if no rate is mentioned at all (can't filter what we can't see).

    For a range like "$40-$90/hr", checks the HIGH end ($90) so we don't
    accidentally exclude jobs whose top of range is acceptable.
    """
    if not description:
        return True

    all_rates: list[float] = []
    for m in _RATE_PATTERN.finditer(description):
        if m.group(1):
            all_rates.append(float(m.group(1)))
        if m.group(2):
            all_rates.append(float(m.group(2)))

    if not all_rates:
        return True  # no rate info in description → don't filter out

    return max(all_rates) >= min_rate
