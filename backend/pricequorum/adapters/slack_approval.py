"""Slack, the human approval gate, over Socket Mode.

The approval is a button press by a person in Slack. It is never an argument the model can
fill: the button carries the run id and the args hash, and the decision handler applies it
with a single-winner transition in the database.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError

from pricequorum.ports import AdapterFault, AdapterRefusal, ApprovalPosted, ApprovalRequest, DecisionHandler

log = logging.getLogger(__name__)

APPROVE_ACTION = "pq_approve"
DENY_ACTION = "pq_deny"


def _slack_error(call_site: str, error: SlackApiError) -> Exception:
    code = str(error.response.get("error", "unknown_error")) if error.response is not None else "unknown_error"
    if code == "ratelimited":
        return AdapterFault("rate_limit", call_site, False, code)
    if code in ("channel_not_found", "not_in_channel", "is_archived"):
        return AdapterRefusal(
            "slack",
            f"Slack could not post to the approval channel: {code}.",
            "Invite the PriceQuorum bot to the approval channel and check SLACK_APPROVAL_CHANNEL.",
        )
    if code in ("invalid_auth", "not_authed", "account_inactive", "token_revoked", "missing_scope"):
        return AdapterRefusal(
            "slack",
            f"Slack rejected the bot token: {code}.",
            "Check SLACK_BOT_TOKEN and that the app has the chat:write scope.",
        )
    return AdapterFault("server_5xx", call_site, False, code)


def request_blocks(request: ApprovalRequest) -> list[dict[str, Any]]:
    value = json.dumps({"run_id": request.run_id, "args_hash": request.args_hash})
    expires = int(request.expires_at.timestamp())
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*PriceQuorum wants to change a price*\n{request.summary}"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Run `{request.run_id}` · args `{request.args_hash[:12]}` · "
                    f"expires <!date^{expires}^{{time}}|{request.expires_at.isoformat()}>",
                }
            ],
        },
        {
            "type": "actions",
            "block_id": "pq_decision",
            "elements": [
                {
                    "type": "button",
                    "action_id": APPROVE_ACTION,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "value": value,
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Approve this price change?"},
                        "text": {"type": "mrkdwn", "text": request.summary[:300]},
                        "confirm": {"type": "plain_text", "text": "Approve"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "action_id": DENY_ACTION,
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Deny"},
                    "value": value,
                },
            ],
        },
    ]


def outcome_blocks(summary: str, decision: str, approver_display: str | None) -> list[dict[str, Any]]:
    who = f" by {approver_display}" if approver_display else ""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*PriceQuorum price change*\n{summary}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*{decision}*{who}"}]},
    ]


class SlackApproval:
    def __init__(
        self,
        bot_token: str,
        app_token: str,
        channel: str,
        app: App | None = None,
        handler_factory: Callable[[App, str], Any] | None = None,
    ) -> None:
        self._channel = channel
        self._app_token = app_token
        self._app = app or App(token=bot_token, token_verification_enabled=False)
        self._handler_factory = handler_factory or (lambda app, token: SocketModeHandler(app, token))
        self._handler: Any = None
        self._on_decision: DecisionHandler | None = None
        self._summaries: dict[str, str] = {}
        self._lock = threading.Lock()
        self._app.action(APPROVE_ACTION)(self._make_action("approve"))
        self._app.action(DENY_ACTION)(self._make_action("deny"))

    def start(self, on_decision: DecisionHandler) -> None:
        self._on_decision = on_decision
        self._handler = self._handler_factory(self._app, self._app_token)
        self._handler.connect()  # non-blocking; bolt runs the socket in its own threads

    def connected(self) -> bool:
        try:
            return bool(self._handler is not None and self._handler.client.is_connected())
        except Exception:  # noqa: BLE001 - a broken socket client means not connected
            return False

    def post_request(self, request: ApprovalRequest) -> ApprovalPosted:
        try:
            response = self._app.client.chat_postMessage(
                channel=self._channel, text=f"Approve price change: {request.summary}", blocks=request_blocks(request)
            )
        except SlackApiError as error:
            raise _slack_error("slack.chat.postMessage", error) from error
        except OSError as error:
            raise AdapterFault("timeout", "slack.chat.postMessage", False, str(error)[:200]) from error
        posted = ApprovalPosted(channel=str(response["channel"]), ts=str(response["ts"]))
        with self._lock:
            self._summaries[posted.ts] = request.summary
        return posted

    def post_outcome(self, posted: ApprovalPosted, decision: str, approver_display: str | None) -> None:
        with self._lock:
            summary = self._summaries.get(posted.ts, "Price change")
        try:
            self._app.client.chat_update(
                channel=posted.channel,
                ts=posted.ts,
                text=f"Price change {decision}",
                blocks=outcome_blocks(summary, decision, approver_display),
            )
        except SlackApiError as error:
            raise _slack_error("slack.chat.update", error) from error
        except OSError as error:
            raise AdapterFault("timeout", "slack.chat.update", False, str(error)[:200]) from error

    def _display_name(self, client: Any, user_id: str) -> str:
        try:
            profile = client.users_info(user=user_id)["user"]
            return str(
                profile.get("profile", {}).get("display_name")
                or profile.get("real_name")
                or profile.get("name")
                or user_id
            )
        except (SlackApiError, KeyError, TypeError, OSError):
            return user_id

    def _make_action(self, decision: str) -> Callable[..., None]:
        def handle(ack: Callable[[], None], body: dict[str, Any], client: Any) -> None:
            ack()  # Slack requires an acknowledgement within 3 seconds; the decision is applied after.
            self.handle_action(decision, body, client)

        return handle

    def handle_action(self, decision: str, body: dict[str, Any], client: Any) -> None:
        try:
            action = body["actions"][0]
            value = json.loads(action["value"])
            run_id, args_hash = str(value["run_id"]), str(value["args_hash"])
            user_id = str(body["user"]["id"])
            channel = str(body["channel"]["id"])
            ts = str(body["message"]["ts"])
        except (KeyError, IndexError, TypeError, ValueError):
            log.warning("Ignoring a Slack action with an unreadable payload")
            return
        if self._on_decision is None:
            log.warning("Slack action arrived before the decision handler started")
            return
        approver = self._display_name(client, user_id)
        try:
            result = self._on_decision(run_id, "approve" if decision == "approve" else "deny", approver, args_hash)
        except Exception:  # noqa: BLE001 - the button press must not crash the socket thread
            log.exception("Decision handler failed for run %s", run_id)
            result = "ERROR"
        if result in ("APPROVED", "DENIED", "EXPIRED"):
            try:
                self.post_outcome(
                    ApprovalPosted(channel=channel, ts=ts), result, approver if result != "EXPIRED" else None
                )
            except (AdapterFault, AdapterRefusal):
                log.exception("Could not update the Slack approval message for run %s", run_id)
        else:
            text = (
                "This price change was already decided."
                if result == "ALREADY_DECIDED"
                else "PriceQuorum could not record that decision. Check the run page."
            )
            try:
                client.chat_postEphemeral(channel=channel, user=user_id, text=text)
            except (SlackApiError, OSError):
                log.exception("Could not send the Slack ephemeral notice for run %s", run_id)
