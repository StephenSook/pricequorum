"""Builds the vendor adapters from settings. A missing credential leaves that adapter as None,
so the API can report exactly which app is not configured instead of pretending."""

from __future__ import annotations

from dataclasses import dataclass

from pricequorum.adapters.faults import EnvFaultInjector, NoFaults, injector_for
from pricequorum.ports import ApprovalPort, DerivedPort, FaultInjector, StripePort


@dataclass
class Adapters:
    stripe: StripePort | None
    notion: DerivedPort | None
    airtable: DerivedPort | None
    approval: ApprovalPort | None
    faults: FaultInjector

    def missing(self) -> list[str]:
        return [name for name in ("stripe", "notion", "airtable", "approval") if getattr(self, name) is None]


def _setting(settings: object, name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    # pydantic SecretStr and plain strings both work
    getter = getattr(value, "get_secret_value", None)
    text = getter() if callable(getter) else str(value)
    return text.strip() or None


def build_adapters(settings: object, faults: FaultInjector | None = None) -> Adapters:
    injector = faults if faults is not None else injector_for(_setting(settings, "pq_fault"))

    stripe_adapter: StripePort | None = None
    if key := _setting(settings, "stripe_secret_key"):
        from pricequorum.adapters.stripe_adapter import StripeAdapter

        stripe_adapter = StripeAdapter(key, injector)

    notion: DerivedPort | None = None
    token, data_source = _setting(settings, "notion_token"), _setting(settings, "notion_data_source_id")
    if token and data_source:
        from pricequorum.adapters.notion_adapter import NotionAdapter

        notion = NotionAdapter(token, data_source, injector)

    airtable: DerivedPort | None = None
    pat, base, table = (_setting(settings, n) for n in ("airtable_pat", "airtable_base_id", "airtable_table"))
    if pat and base and table:
        from pricequorum.adapters.airtable_adapter import AirtableAdapter

        airtable = AirtableAdapter(pat, base, table, injector)

    approval: ApprovalPort | None = None
    bot, app_token, channel = (
        _setting(settings, n) for n in ("slack_bot_token", "slack_app_token", "slack_approval_channel")
    )
    if bot and app_token and channel:
        from pricequorum.adapters.slack_approval import SlackApproval

        approval = SlackApproval(bot, app_token, channel)

    return Adapters(stripe=stripe_adapter, notion=notion, airtable=airtable, approval=approval, faults=injector)


__all__ = ["Adapters", "EnvFaultInjector", "NoFaults", "build_adapters", "injector_for"]
