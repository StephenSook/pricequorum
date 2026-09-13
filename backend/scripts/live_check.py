"""Checks every vendor connection against the real apps. Read-only.

Usage, from backend/:
    uv run python scripts/live_check.py

Prints PASS or FAIL per app with ids and prices only, never a secret. Exits non-zero when any
variable is missing or any check fails.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pricequorum.adapters import build_adapters  # noqa: E402
from pricequorum.adapters.faults import NoFaults  # noqa: E402
from pricequorum.ports import AdapterFault, AdapterRefusal  # noqa: E402

REQUIRED = [
    "STRIPE_SECRET_KEY",
    "NOTION_TOKEN",
    "NOTION_DATA_SOURCE_ID",
    "AIRTABLE_PAT",
    "AIRTABLE_BASE_ID",
    "AIRTABLE_TABLE",
    "SLACK_BOT_TOKEN",
    "SLACK_APP_TOKEN",
    "SLACK_APPROVAL_CHANNEL",
]


def main() -> int:
    failed = 0
    missing = [name for name in REQUIRED if not os.environ.get(name, "").strip()]
    for name in missing:
        print(f"FAIL missing environment variable {name}")
    failed += len(missing)

    settings = SimpleNamespace(**{name.lower(): os.environ.get(name) for name in REQUIRED})
    try:
        adapters = build_adapters(settings, faults=NoFaults())
    except AdapterRefusal as refusal:
        print(f"FAIL {refusal.app}: {refusal.reason} {refusal.remedy}")
        return 1

    for name, adapter in (("stripe", adapters.stripe), ("notion", adapters.notion), ("airtable", adapters.airtable)):
        if adapter is None:
            print(f"FAIL {name}: not configured")
            failed += 1
            continue
        try:
            plans = adapter.list_plans()
            keyed = [plan for plan in plans if plan.pq_plan_id]
            print(f"PASS {name}: {len(plans)} plans, keyed {sorted(p.pq_plan_id for p in keyed if p.pq_plan_id)}")
            if not keyed:
                print(f"FAIL {name}: no plan carries a pq_plan_id, run scripts/seed.py")
                failed += 1
                continue
            readback = adapter.read_back(keyed[0].external_id)
            value = f"{readback.value.minor_units} {readback.value.currency}" if readback.value else "unreadable"
            source = f"raw {readback.raw_value}, {readback.source_id}"
            print(f"PASS {name} read-back: {keyed[0].pq_plan_id} = {value} ({source})")
        except (AdapterFault, AdapterRefusal) as error:
            print(f"FAIL {name}: {error} {getattr(error, 'remedy', '')}".strip())
            failed += 1

    bot, app_token, channel = (
        os.environ.get(n) for n in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_APPROVAL_CHANNEL")
    )
    if bot and app_token:
        try:
            auth = WebClient(token=bot).auth_test()
            print(f"PASS slack bot: team {auth.get('team')} as {auth.get('user')}")
            WebClient(token=app_token).apps_connections_open()
            print("PASS slack app token: Socket Mode connection can be opened")
            if channel and channel[:1] in ("C", "G"):
                info = WebClient(token=bot).conversations_info(channel=channel)
                member = info["channel"].get("is_member")
                verdict, state = ("PASS", "a member") if member else ("FAIL", "not a member")
                print(f"{verdict} slack channel {channel}: bot is {state}")
                failed += 0 if member else 1
        except SlackApiError as error:
            print(f"FAIL slack: {error.response.get('error') if error.response is not None else error}")
            failed += 1

    print("live check:", "PASS" if failed == 0 else f"FAIL ({failed} problems)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
