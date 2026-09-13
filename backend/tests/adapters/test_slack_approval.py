"""Block Kit shape, acknowledgement order and decision routing for the Slack approval adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from slack_bolt import App
from slack_sdk import WebClient

from pricequorum.adapters.slack_approval import APPROVE_ACTION, DENY_ACTION, SlackApproval, request_blocks
from pricequorum.ports import ApprovalPosted, ApprovalRequest


class FakeWeb(WebClient):
    def __init__(self) -> None:
        super().__init__(token="xoxb-unit")
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def chat_postMessage(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(("chat_postMessage", kwargs))
        return {"ok": True, "channel": "C123", "ts": "1726250000.000100"}

    def chat_update(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(("chat_update", kwargs))
        return {"ok": True}

    def chat_postEphemeral(self, **kwargs: Any) -> Any:  # type: ignore[override]
        self.calls.append(("chat_postEphemeral", kwargs))
        return {"ok": True}

    def users_info(self, **kwargs: Any) -> Any:  # type: ignore[override]
        return {"ok": True, "user": {"name": "stephen", "profile": {"display_name": "Stephen"}}}


class FakeHandler:
    def __init__(self, connected: bool) -> None:
        self.client = type("Client", (), {"is_connected": lambda self: connected})()
        self.connected_called = False

    def connect(self) -> None:
        self.connected_called = True


REQUEST = ApprovalRequest(
    run_id="run-1",
    summary="Pro from 20.00 USD to 25.00 USD per month",
    args_hash="a" * 64,
    expires_at=datetime(2026, 9, 13, 20, 30, tzinfo=UTC) + timedelta(minutes=30),
)


def build(connected: bool = True) -> tuple[SlackApproval, FakeWeb, FakeHandler]:
    web = FakeWeb()
    app = App(client=web, token_verification_enabled=False, request_verification_enabled=False)
    handler = FakeHandler(connected)
    return SlackApproval("xoxb-unit", "xapp-unit", "C123", app=app, handler_factory=lambda a, t: handler), web, handler


def body(action_id: str) -> dict[str, Any]:
    return {
        "actions": [{"action_id": action_id, "value": json.dumps({"run_id": "run-1", "args_hash": "a" * 64})}],
        "user": {"id": "U1"},
        "channel": {"id": "C123"},
        "message": {"ts": "1726250000.000100"},
    }


def test_request_blocks_carry_run_id_and_args_hash_on_both_buttons() -> None:
    actions = request_blocks(REQUEST)[-1]["elements"]
    assert [a["action_id"] for a in actions] == [APPROVE_ACTION, DENY_ACTION]
    for action in actions:
        assert json.loads(action["value"]) == {"run_id": "run-1", "args_hash": "a" * 64}
    assert "confirm" in actions[0]


def test_post_request_and_outcome_use_the_same_message() -> None:
    slack, web, _ = build()
    posted = slack.post_request(REQUEST)
    assert posted == ApprovalPosted(channel="C123", ts="1726250000.000100")
    slack.post_outcome(posted, "APPROVED", "Stephen")
    name, update = web.calls[-1]
    assert name == "chat_update" and update["ts"] == posted.ts
    assert all(block["type"] != "actions" for block in update["blocks"])


def test_button_is_acknowledged_before_the_decision_is_applied() -> None:
    slack, web, handler = build()
    order: list[str] = []

    def decide(run_id: str, decision: str, approver: str, args_hash: str) -> str:
        order.append(f"decide:{run_id}:{decision}:{approver}:{args_hash[:4]}")
        return "APPROVED"

    slack.start(decide)
    assert handler.connected_called and slack.connected()
    slack._make_action("approve")(lambda: order.append("ack"), body(APPROVE_ACTION), web)
    assert order == ["ack", "decide:run-1:approve:Stephen:aaaa"]
    assert web.calls[-1][0] == "chat_update"


def test_an_already_decided_press_gets_an_ephemeral_notice() -> None:
    slack, web, _ = build()
    slack.start(lambda run_id, decision, approver, args_hash: "ALREADY_DECIDED")
    slack.handle_action("deny", body(DENY_ACTION), web)
    name, notice = web.calls[-1]
    assert name == "chat_postEphemeral" and "already decided" in notice["text"]


def test_not_connected_before_start_or_when_the_socket_drops() -> None:
    slack, _, _ = build(connected=False)
    assert slack.connected() is False
    slack.start(lambda *args: "APPROVED")
    assert slack.connected() is False
