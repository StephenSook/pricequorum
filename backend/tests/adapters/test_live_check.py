"""The Slack live check proves scopes and channel membership, and only proves posting with --post-smoke."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import live_check  # noqa: E402

GOOD_CHANNEL = "C0123456789"


class FakeResponse(dict[str, Any]):
    def __init__(self, data: dict[str, Any], headers: dict[str, str] | None = None) -> None:
        super().__init__(data)
        self.headers = headers or {}


class FakeSlack:
    def __init__(self, scopes: str = "chat:write,channels:read,users:read", member: bool = True) -> None:
        self.scopes = scopes
        self.member = member
        self.calls: list[str] = []

    def __call__(self, token: str) -> FakeSlack:
        return self

    def auth_test(self) -> FakeResponse:
        self.calls.append("auth.test")
        return FakeResponse({"ok": True, "team": "T", "user": "pricequorum"}, {"X-OAuth-Scopes": self.scopes})

    def apps_connections_open(self) -> FakeResponse:
        self.calls.append("apps.connections.open")
        return FakeResponse({"ok": True, "url": "wss://example"})

    def conversations_info(self, channel: str) -> FakeResponse:
        self.calls.append("conversations.info")
        return FakeResponse({"ok": True, "channel": {"id": channel, "is_member": self.member}})

    def chat_postMessage(self, **kwargs: Any) -> FakeResponse:  # noqa: N802 - mirrors the Slack SDK
        self.calls.append("chat.postMessage")
        return FakeResponse({"ok": True, "channel": kwargs["channel"], "ts": "1726250000.000100"})

    def chat_update(self, **kwargs: Any) -> FakeResponse:
        self.calls.append("chat.update")
        return FakeResponse({"ok": True})

    def chat_delete(self, **kwargs: Any) -> FakeResponse:
        self.calls.append("chat.delete")
        return FakeResponse({"ok": True})


def test_an_invalid_channel_id_fails_instead_of_being_skipped() -> None:
    slack = FakeSlack()
    result = live_check.check_slack("xoxb-unit", "xapp-unit", "general", post_smoke=False, client_factory=slack)
    assert result.failures >= 1 and "conversations.info" not in slack.calls


def test_a_bot_token_without_chat_write_fails() -> None:
    slack = FakeSlack(scopes="channels:read,users:read")
    result = live_check.check_slack("xoxb-unit", "xapp-unit", GOOD_CHANNEL, post_smoke=False, client_factory=slack)
    assert result.failures >= 1


def test_without_post_smoke_posting_is_not_verified_and_nothing_is_posted() -> None:
    slack = FakeSlack()
    result = live_check.check_slack("xoxb-unit", "xapp-unit", GOOD_CHANNEL, post_smoke=False, client_factory=slack)
    assert result.failures == 0 and result.posting_verified is False
    assert not any(call.startswith("chat.") for call in slack.calls)


def test_post_smoke_posts_updates_and_deletes_one_message() -> None:
    slack = FakeSlack()
    result = live_check.check_slack("xoxb-unit", "xapp-unit", GOOD_CHANNEL, post_smoke=True, client_factory=slack)
    assert result.failures == 0 and result.posting_verified is True
    assert [c for c in slack.calls if c.startswith("chat.")] == ["chat.postMessage", "chat.update", "chat.delete"]


def test_a_bot_outside_the_channel_fails() -> None:
    slack = FakeSlack(member=False)
    result = live_check.check_slack("xoxb-unit", "xapp-unit", GOOD_CHANNEL, post_smoke=True, client_factory=slack)
    assert result.failures >= 1 and result.posting_verified is False
