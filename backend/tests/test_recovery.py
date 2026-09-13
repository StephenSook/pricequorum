"""Recovery after an ambiguous Stripe failure identifies the exact object this run wrote. A price that
merely shares the amount must never be adopted as ours."""

from __future__ import annotations

from pricequorum.adapters.faults import EnvFaultInjector
from pricequorum.adapters_factory import AdapterSet
from pricequorum.config import Settings
from pricequorum.orchestrator import Orchestrator
from pricequorum.ports import Money
from tests.fakes import world
from tests.runlog import outcome, payloads

CREATE_KEY = "pq:pro:usd-month-2500:create_price"


def run_now(orchestrator: Orchestrator, text: str) -> str:
    run_id = orchestrator.create_run(text, approval_mode="sandbox_auto")
    orchestrator.execute(run_id)
    return run_id


def test_a_create_that_never_landed_is_retried_instead_of_adopting_a_same_amount_price(settings: Settings) -> None:
    stripe, notion, airtable = world()
    product = stripe.product_for("pro")
    decoy = stripe.add_price(product, Money(2500, "usd"))
    stripe.fail_next_create = True
    run_id = run_now(Orchestrator(settings, AdapterSet(stripe, notion, airtable, None)), "raise Pro to $25/month")

    recovery = payloads(run_id, "readback.recovery")[0]
    assert recovery["found_landed"] is False and recovery["external_object_id"] is None
    assert outcome(run_id)["outcome"] == "SUCCESS"
    default = stripe.products[product]["default_price"]
    assert default != decoy and stripe.prices[default]["key"] == CREATE_KEY
    assert stripe.creates == 1


def test_a_create_that_landed_is_found_by_its_idempotency_key_not_by_its_amount(settings: Settings) -> None:
    stripe, notion, airtable = world(stripe_faults=EnvFaultInjector("timeout_after_commit"))
    product = stripe.product_for("pro")
    decoy = stripe.add_price(product, Money(2500, "usd"))
    run_id = run_now(Orchestrator(settings, AdapterSet(stripe, notion, airtable, None)), "raise Pro to $25/month")

    recovery = payloads(run_id, "readback.recovery")[0]
    assert recovery["found_landed"] is True
    assert recovery["external_object_id"] == stripe.keys[CREATE_KEY] != decoy
    assert stripe.products[product]["default_price"] == stripe.keys[CREATE_KEY]
    assert stripe.creates == 1 and outcome(run_id)["outcome"] == "SUCCESS"


def test_archive_proof_reads_the_exact_old_price_not_any_price_at_the_old_amount(settings: Settings) -> None:
    stripe, notion, airtable = world(stripe_faults=EnvFaultInjector("timeout@stripe.price.update"))
    product = stripe.product_for("pro")
    old_price = stripe.products[product]["default_price"]
    other_at_old_amount = stripe.add_price(product, Money(2000, "usd"))
    run_id = run_now(Orchestrator(settings, AdapterSet(stripe, notion, airtable, None)), "raise Pro to $25/month")

    recovery = payloads(run_id, "readback.recovery")[0]
    assert (recovery["call_site"], recovery["found_landed"], recovery["external_object_id"]) == (
        "stripe.price.update",
        True,
        old_price,
    )
    archived = next(p for p in payloads(run_id, "invariant.result") if p["name"] == "old_price_archived")
    assert archived["ok"] is True and old_price in archived["detail"]
    assert stripe.prices[old_price]["active"] is False and stripe.prices[other_at_old_amount]["active"] is True
    assert outcome(run_id)["outcome"] == "SUCCESS"
