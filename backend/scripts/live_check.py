"""Checks every vendor connection against the real apps.

Usage, from backend/:
    uv run python scripts/live_check.py               # read-only
    uv run python scripts/live_check.py --post-smoke  # also posts, updates and deletes one Slack message

Prints PASS, FAIL or NOT VERIFIED per check with ids and prices only, never a secret.
Exit codes: 0 every check passed including Slack posting; 1 a variable is missing or a check
failed; 2 every read check passed but Slack posting was not exercised (run with --post-smoke).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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

CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{8,}$")
SMOKE_TEXT = "PriceQuorum live check: this message is deleted in a moment."


@dataclass(frozen=True)
class SlackCheck:
    failures: int
    posting_verified: bool


def _slack_error(error: SlackApiError) -> str:
    return str(error.response.get("error")) if error.response is not None else str(error)


def granted_scopes(response: Any) -> set[str]:
    """The scopes Slack reports for the token, from the x-oauth-scopes response header."""
    headers: Mapping[str, Any] = getattr(response, "headers", None) or {}
    for name, value in dict(headers).items():
        if name.lower() == "x-oauth-scopes":
            return {scope.strip() for scope in str(value).split(",") if scope.strip()}
    return set()


def check_slack(
    bot_token: str,
    app_token: str,
    channel: str | None,
    *,
    post_smoke: bool,
    client_factory: Callable[[str], Any] = WebClient,
) -> SlackCheck:
    failures = 0
    channel_id = channel if channel and CHANNEL_ID.fullmatch(channel) else None
    if channel_id is None:
        print(f"FAIL slack channel {channel!r}: not a Slack channel id (C... or G...). Use the id, not the name.")
        failures += 1

    bot = client_factory(bot_token)
    try:
        auth = bot.auth_test()
    except SlackApiError as error:
        print(f"FAIL slack bot token: {_slack_error(error)}")
        return SlackCheck(failures + 1, False)
    print(f"PASS slack bot token: team {auth.get('team')} as {auth.get('user')}")

    scopes = granted_scopes(auth)
    required = {"chat:write", "channels:read"} | (
        {"groups:read"} if channel_id and channel_id.startswith("G") else set()
    )
    if not scopes:
        print("FAIL slack scopes: auth.test did not report granted scopes (no x-oauth-scopes header)")
        failures += 1
    elif missing := sorted(required - scopes):
        print(f"FAIL slack scopes: the bot token is missing {', '.join(missing)}")
        failures += 1
    else:
        print(f"PASS slack scopes: {', '.join(sorted(required))} granted")
        if "users:read" not in scopes:
            print("WARN slack scopes: users:read is missing, so approvers will show as user ids")

    try:
        client_factory(app_token).apps_connections_open()
        print("PASS slack app token: a Socket Mode connection can be opened")
    except SlackApiError as error:
        print(f"FAIL slack app token: {_slack_error(error)}")
        failures += 1

    member = False
    if channel_id is not None:
        try:
            member = bool(bot.conversations_info(channel=channel_id)["channel"].get("is_member"))
            print(
                f"{'PASS' if member else 'FAIL'} slack channel {channel_id}: bot is {'' if member else 'not '}a member"
            )
            failures += 0 if member else 1
        except (SlackApiError, KeyError, TypeError) as error:
            detail = _slack_error(error) if isinstance(error, SlackApiError) else "unreadable response"
            print(f"FAIL slack channel {channel_id}: {detail}")
            failures += 1

    posting_verified = False
    if not post_smoke:
        print("NOT VERIFIED slack posting: run with --post-smoke to post, update and delete one message")
    elif channel_id is None or not member or failures:
        print("FAIL slack post smoke: not attempted because an earlier Slack check failed")
        failures += 1
    else:
        try:
            posted = bot.chat_postMessage(channel=channel_id, text=SMOKE_TEXT)
            ts, posted_channel = str(posted["ts"]), str(posted["channel"])
            bot.chat_update(channel=posted_channel, ts=ts, text="PriceQuorum live check: updating works, deleting.")
            bot.chat_delete(channel=posted_channel, ts=ts)
            posting_verified = True
            print("PASS slack post smoke: posted, updated and deleted one message")
        except (SlackApiError, KeyError, TypeError) as error:
            detail = _slack_error(error) if isinstance(error, SlackApiError) else "unreadable response"
            print(f"FAIL slack post smoke: {detail}")
            failures += 1
    return SlackCheck(failures, posting_verified)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--post-smoke", action="store_true", help="post, update and delete one Slack message")
    args = parser.parse_args(argv)

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

    posting_verified = False
    bot, app_token = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_APP_TOKEN")
    if bot and app_token:
        slack = check_slack(bot, app_token, os.environ.get("SLACK_APPROVAL_CHANNEL"), post_smoke=args.post_smoke)
        failed += slack.failures
        posting_verified = slack.posting_verified

    if failed:
        print(f"live check: FAIL ({failed} problems)")
        return 1
    if not posting_verified:
        print("live check: read checks PASS, Slack posting NOT VERIFIED (run with --post-smoke)")
        return 2
    print("live check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
