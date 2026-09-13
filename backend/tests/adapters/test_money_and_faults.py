from decimal import Decimal

import pytest

from pricequorum.adapters._money import major_json_number, major_to_minor, minor_to_major
from pricequorum.adapters.faults import EnvFaultInjector, NoFaults, injector_for
from pricequorum.ports import AdapterFault


def test_float_stored_price_reads_back_as_the_intended_minor_units() -> None:
    assert major_to_minor(24.999999999999996, "usd") == 2500
    assert major_to_minor("25", "usd") == 2500
    assert major_to_minor(25.5, "usd") == 2550


def test_materially_non_integral_prices_are_unreadable_not_rounded() -> None:
    # 25.005 USD is half a cent: rounding it would falsely agree with 25.01.
    assert major_to_minor(25.005, "usd") is None
    assert major_to_minor("25.005", "usd") is None
    assert major_to_minor(25.0005, "kwd") is None
    assert major_to_minor(25.01, "usd") == 2501
    assert major_to_minor(0.1 + 0.2, "usd") == 30  # binary float noise is still accepted


def test_currency_exponents_follow_iso_4217() -> None:
    assert major_to_minor(500, "jpy") == 500
    assert major_to_minor("10.000", "kwd") == 10000
    assert minor_to_major(10000, "kwd") == Decimal("10")
    assert minor_to_major(10, "jpy") == Decimal("10")


def test_unreadable_values_are_none_not_zero() -> None:
    assert major_to_minor(None, "usd") is None
    assert major_to_minor("n/a", "usd") is None
    assert major_to_minor(True, "usd") is None


def test_json_number_is_an_int_when_whole() -> None:
    assert major_json_number(2500, "usd") == 25
    assert isinstance(major_json_number(2500, "usd"), int)
    assert major_json_number(2599, "usd") == 25.99


def test_named_fault_fires_once_on_its_call_site_only() -> None:
    faults = EnvFaultInjector("timeout_after_commit")
    faults.after("notion.page.update")
    with pytest.raises(AdapterFault) as raised:
        faults.after("stripe.price.create")
    assert raised.value.injected is True
    assert raised.value.kind == "timeout"
    faults.after("stripe.price.create")  # already fired


def test_explicit_fault_syntax_and_unknown_names() -> None:
    faults = EnvFaultInjector("server_5xx@airtable.upsert")
    with pytest.raises(AdapterFault):
        faults.after("airtable.upsert")
    with pytest.raises(ValueError):
        EnvFaultInjector("not_a_fault")
    with pytest.raises(ValueError):
        EnvFaultInjector("explode@stripe.price.create")


def test_no_fault_by_default() -> None:
    assert isinstance(injector_for(None), NoFaults)
    NoFaults().after("stripe.price.create")
