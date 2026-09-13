"""Fault injection for evaluations and the judge sandbox.

A fault is raised right AFTER the real request was sent, so it models the dangerous case: the
write may have landed but the caller never heard back. Every injected fault carries
injected=True, and the run events say so.
"""

from __future__ import annotations

import threading

from pricequorum.ports import AdapterFault, FaultKind

# Named scenarios map to (call site, fault kind).
FAULT_PLANS: dict[str, tuple[str, FaultKind]] = {
    "timeout_after_commit": ("stripe.price.create", "timeout"),
    "idempotency_409": ("stripe.price.create", "conflict_409"),
    "stripe_5xx": ("stripe.product.update", "server_5xx"),
    "half_landed": ("notion.page.update", "timeout"),
    "server_5xx": ("notion.page.update", "server_5xx"),
    "rate_limit": ("airtable.upsert", "rate_limit"),
    "rate_limit_429": ("airtable.upsert", "rate_limit"),
}

_KINDS: tuple[FaultKind, ...] = ("timeout", "rate_limit", "conflict_409", "server_5xx")


class NoFaults:
    """The injector used for normal runs."""

    def after(self, call_site: str) -> None:
        return None


class EnvFaultInjector:
    """Armed from a fault name (PQ_FAULT) or an explicit "kind@call_site". Fires once."""

    def __init__(self, fault: str) -> None:
        self.name = fault
        if fault in FAULT_PLANS:
            self.call_site, self.kind = FAULT_PLANS[fault]
        elif "@" in fault:
            kind, call_site = fault.split("@", 1)
            if kind not in _KINDS or not call_site:
                raise ValueError(f"Unknown fault {fault!r}. Use kind@call_site with kind in {', '.join(_KINDS)}.")
            self.kind = kind  # type: ignore[assignment]
            self.call_site = call_site
        else:
            raise ValueError(f"Unknown fault {fault!r}. Known faults: {', '.join(sorted(FAULT_PLANS))}.")
        self._armed = True
        self._lock = threading.Lock()

    @property
    def armed(self) -> bool:
        return self._armed

    def rearm(self) -> None:
        with self._lock:
            self._armed = True

    def after(self, call_site: str) -> None:
        with self._lock:
            if not self._armed or call_site != self.call_site:
                return
            self._armed = False
        raise AdapterFault(self.kind, call_site, injected=True, detail=f"injected by fault {self.name}")


def injector_for(fault: str | None) -> NoFaults | EnvFaultInjector:
    return EnvFaultInjector(fault) if fault else NoFaults()
