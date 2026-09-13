import pytest

from evals.stats import wilson_interval


@pytest.mark.parametrize(
    ("passed", "total", "low", "high"),
    [
        (19, 20, 0.7639, 0.9911),
        (10, 20, 0.2993, 0.7007),
        (20, 20, 0.8389, 1.0),
        (0, 5, 0.0, 0.4345),
    ],
)
def test_wilson_interval_matches_reference_values(passed, total, low, high):
    got_low, got_high = wilson_interval(passed, total)
    assert got_low == pytest.approx(low, abs=1e-4)
    assert got_high == pytest.approx(high, abs=1e-4)


def test_no_trials_carries_no_information():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_impossible_counts_are_rejected():
    with pytest.raises(ValueError):
        wilson_interval(21, 20)
    with pytest.raises(ValueError):
        wilson_interval(-1, 20)
