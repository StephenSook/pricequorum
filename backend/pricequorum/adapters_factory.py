"""Builds the adapter set the orchestrator uses. A missing credential or a missing adapters package
leaves that app unconfigured, and the API reports it by name instead of starting with fakes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pricequorum.ports import ApprovalPort, DerivedPort, StripePort

log = logging.getLogger("pricequorum.adapters_factory")


@dataclass
class AdapterSet:
    stripe: StripePort | None = None
    notion: DerivedPort | None = None
    airtable: DerivedPort | None = None
    approval: ApprovalPort | None = None
    errors: dict[str, str] = field(default_factory=dict)

    def missing_apps(self) -> list[str]:
        return [name for name in ("stripe", "notion", "airtable") if getattr(self, name) is None]


def build_adapter_set(settings: object, scenario: str | None = None) -> AdapterSet:
    """Real adapters from pricequorum.adapters. A fault scenario arms a fresh injector for that run only."""
    try:
        from pricequorum.adapters import build_adapters, injector_for
    except ImportError as exc:
        return AdapterSet(errors={"adapters": f"The adapters package could not be imported: {exc}"})
    try:
        built = build_adapters(settings, faults=injector_for(scenario) if scenario else None)
    except Exception as exc:  # noqa: BLE001 - a bad credential must not stop the API from starting
        log.warning("adapters could not be built: %s", exc)
        return AdapterSet(errors={"adapters": str(exc)})
    return AdapterSet(stripe=built.stripe, notion=built.notion, airtable=built.airtable, approval=built.approval)
