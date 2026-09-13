"""Uncertainty for a pass rate. A bare pass rate is never reported without its interval."""

from __future__ import annotations

import math

Z_95 = 1.959963984540054


def wilson_interval(passed: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """The Wilson score interval for passed out of total. With no trials it carries no information: (0, 1)."""
    if total < 0 or passed < 0 or passed > total:
        raise ValueError(f"passed must be between 0 and total, got {passed} of {total}")
    if total == 0:
        return 0.0, 1.0
    proportion = passed / total
    z2 = z * z
    denominator = 1 + z2 / total
    centre = (proportion + z2 / (2 * total)) / denominator
    half_width = z * math.sqrt(proportion * (1 - proportion) / total + z2 / (4 * total * total)) / denominator
    return max(0.0, centre - half_width), min(1.0, centre + half_width)
