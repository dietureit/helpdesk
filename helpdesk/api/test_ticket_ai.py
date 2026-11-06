import json
from unittest.mock import MagicMock, patch

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from helpdesk.api import ticket_ai

MESSAGES = [
    {"message": "My dinner came two hours late", "message_direction": "Incoming", "timestamp": "2026-10-28 19:00:00"},
    {"message": "internal note", "message_direction": "Outgoing", "timestamp": "2026-10-28 19:01:00", "is_private": 1},
    {"message": "Sorry about that, checking now", "message_direction": "Outgoing", "timestamp": "2026-10-28 19:02:00"},
]
CONFIG = {"enabled": True, "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4.1"}


def _reply(content: str, status: int = 200):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    if status >= 400:
        error = requests.HTTPError(response=response)
        response.raise_for_status.side_effect = error
    return response


class TestTicketAI(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(ticket_ai, "get_config", return_value=dict(CONFIG)))
        self.enterContext(patch.object(ticket_ai, "_api_key", return_value="test-key"))
        self.enterContext(patch.object(ticket_ai, "_ticket_types", return_value=["Delivery", "Problem"]))

    def test_maps_reply_to_ticket_fields(self):
        content = json.dumps(
            {
                "subject": "  Dinner delivered two hours late  ",
                "description": "The dinner arrived at 9pm.\n\nCustomer wants a refund.",
                "ticket_type": "Delivery",
            }
        )
        with patch.object(ticket_ai.requests, "post", return_value=_reply(content)) as post:
            out = ticket_ai.summarize_conversation(MESSAGES)
        self.assertEqual(
            out,
            {
                "subject": "Dinner delivered two hours late",
                "description": "<p>The dinner arrived at 9pm.</p><p>Customer wants a refund.</p>",
                "ticket_type": "Delivery",
            },
        )
        kwargs = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
        body = kwargs["json"]
        user_data = json.loads(body["messages"][1]["content"])
        self.assertEqual([m["from"] for m in user_data["messages"]], ["customer", "agent"])  # private note dropped
        self.assertEqual(user_data["ticket_types"], ["Delivery", "Problem"])
        self.assertIn("", body["response_format"]["json_schema"]["schema"]["properties"]["ticket_type"]["enum"])
        self.assertEqual(body["provider"], {"require_parameters": True})

    def test_fenced_json_and_unknown_type(self):
        content = '```json\n{"subject": "Late dinner", "description": "", "ticket_type": "Not A Type"}\n```'
        with patch.object(ticket_ai.requests, "post", return_value=_reply(content)):
            out = ticket_ai.summarize_conversation(MESSAGES)
        self.assertEqual(out, {"subject": "Late dinner", "description": "", "ticket_type": ""})

    def test_provider_errors_become_agent_safe_messages(self):
        with patch.object(ticket_ai.requests, "post", return_value=_reply("", status=401)):
            with self.assertRaises(ticket_ai.TicketAIError) as caught:
                ticket_ai.summarize_conversation(MESSAGES)
        self.assertIn("API key", str(caught.exception))
        with patch.object(ticket_ai.requests, "post", side_effect=requests.Timeout()):
            with self.assertRaises(ticket_ai.TicketAIError) as caught:
                ticket_ai.summarize_conversation(MESSAGES)
        self.assertIn("timed out", str(caught.exception))
        with patch.object(ticket_ai.requests, "post", return_value=_reply("not json")):
            with self.assertRaises(ticket_ai.TicketAIError):
                ticket_ai.summarize_conversation(MESSAGES)

    def test_not_configured(self):
        with patch.object(ticket_ai, "_api_key", return_value=""):
            self.assertFalse(ticket_ai.is_enabled())
            with self.assertRaises(ticket_ai.TicketAIError):
                ticket_ai.summarize_conversation(MESSAGES)
        self.assertTrue(ticket_ai.is_enabled())
        with self.assertRaises(frappe.ValidationError):
            ticket_ai.summarize_conversation([])

    def test_other_hosts_get_no_openrouter_routing_key(self):
        body = ticket_ai._request_body("gpt-4.1", "https://api.openai.com/v1", MESSAGES, ["Delivery"])
        self.assertNotIn("provider", body)


def _json_reply(data: dict):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = data
    return response


class TestChatJSON(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(patch.object(ticket_ai, "get_config", return_value=dict(CONFIG)))
        self.enterContext(patch.object(ticket_ai, "_api_key", return_value="test-key"))

    def _chat(self, reply, data=None, **kwargs):
        """chat_json against a mocked provider: (its result, the posted body)."""
        with patch.object(ticket_ai.requests, "post", return_value=reply) as post:
            out = ticket_ai.chat_json("You label contacts.", {"lines": []} if data is None else data, **kwargs)
        return out, post.call_args.kwargs["json"]

    def test_arabic_is_sent_as_text_with_a_strict_schema(self):
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        (parsed, _meta), body = self._chat(
            _reply('```json\n{"ok": true}\n```'), data={"lines": [{"id": "L1", "text": "الأكل وصل بارد"}]}, schema=schema
        )
        self.assertEqual(parsed, {"ok": True})
        content = body["messages"][1]["content"]
        self.assertIn("الأكل وصل بارد", content)
        self.assertNotIn("\\u", content)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "You label contacts."})
        self.assertEqual(
            body["response_format"],
            {"type": "json_schema", "json_schema": {"name": "ai_analysis", "strict": True, "schema": schema}},
        )
        self.assertEqual((body["model"], body["max_tokens"], body["temperature"]), ("openai/gpt-4.1", 1200, 0))

    def test_openrouter_routing_only_on_openrouter_hosts(self):
        _out, body = self._chat(_reply("ok"), provider={"data_collection": "deny"})
        self.assertEqual(body["provider"], {"require_parameters": True, "data_collection": "deny"})
        with patch.object(ticket_ai, "get_config", return_value={**CONFIG, "base_url": "https://api.openai.com/v1"}):
            _out, body = self._chat(_reply("ok"), provider={"data_collection": "deny"})
        self.assertNotIn("provider", body)

    def test_cut_off_or_unreadable_reply_raises(self):
        cut = _json_reply({"choices": [{"message": {"content": '{"ok": tr'}, "finish_reason": "length"}]})
        with self.assertRaises(ticket_ai.TicketAIError) as caught:
            self._chat(cut, schema={"type": "object"})
        self.assertIn("cut off", str(caught.exception))
        for reply in (_reply("not json"), _json_reply({"choices": []}), _reply(None)):
            with self.assertRaises(ticket_ai.TicketAIError):
                self._chat(reply, schema={"type": "object"})

    def test_meta_defaults_and_cost(self):
        (_text, meta), _body = self._chat(_reply("plain"))
        self.assertEqual(
            meta, {"usage": {}, "cost": 0.0, "model": "openai/gpt-4.1", "finish_reason": "", "annotations": []}
        )
        citation = {"type": "url_citation", "url_citation": {"url": "https://example.org/a"}}
        reply = _json_reply(
            {
                "model": "openai/gpt-4.1-2025-04-14",
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cost": 0.0042},
                "choices": [{"message": {"content": "plain", "annotations": [citation]}, "finish_reason": "stop"}],
            }
        )
        (_text, meta), _body = self._chat(reply)
        self.assertEqual(meta["cost"], 0.0042)
        self.assertEqual(meta["usage"]["prompt_tokens"], 10)
        self.assertEqual(meta["model"], "openai/gpt-4.1-2025-04-14")
        self.assertEqual(meta["finish_reason"], "stop")
        self.assertEqual(meta["annotations"], [citation])

    def test_temperature_none_is_omitted(self):
        _out, body = self._chat(_reply("ok"), temperature=None)
        self.assertNotIn("temperature", body)

    def test_extra_is_merged_into_the_body(self):
        tools = [{"type": "openrouter:web_search", "parameters": {"max_results": 5}}]
        _out, body = self._chat(_reply("ok"), extra={"tools": tools})
        self.assertEqual(body["tools"], tools)

    def test_no_schema_returns_text(self):
        (text, _meta), body = self._chat(_reply("Two practices found."), data="Fixes for leaking soup tubs?")
        self.assertEqual(text, "Two practices found.")
        self.assertNotIn("response_format", body)
        self.assertEqual(body["messages"][1]["content"], "Fixes for leaking soup tubs?")

    def test_http_errors_carry_their_status(self):
        with patch.object(ticket_ai.frappe, "log_error") as log_error:
            with self.assertRaises(ticket_ai.TicketAIError) as caught:
                self._chat(_reply("", status=429))
        self.assertEqual(caught.exception.http_status, 429)
        self.assertIn("rate limiting", str(caught.exception))
        log_error.assert_called_once_with(title="AI Analysis request failed", message="HTTPError: HTTP 429")
        with patch.object(ticket_ai.requests, "post", side_effect=requests.Timeout()):
            with self.assertRaises(ticket_ai.TicketAIError) as caught:
                ticket_ai.chat_json("s", "d")
        self.assertIsNone(caught.exception.http_status)

    def test_needs_only_url_and_key(self):
        with patch.object(ticket_ai, "get_config", return_value={**CONFIG, "enabled": False}):
            (text, _meta), _body = self._chat(_reply("ok"))
        self.assertEqual(text, "ok")  # the ticket-draft switch does not gate other features
        with patch.object(ticket_ai, "_api_key", return_value=""):
            with self.assertRaises(ticket_ai.TicketAIError) as caught:
                ticket_ai.chat_json("s", "d")
        self.assertIn("not configured", str(caught.exception))

    def test_ticket_draft_body_is_unchanged(self):
        content = json.dumps({"subject": "Late dinner", "description": "", "ticket_type": ""})
        with patch.object(ticket_ai, "_ticket_types", return_value=["Delivery"]):
            with patch.object(ticket_ai.requests, "post", return_value=_reply(content)) as post:
                ticket_ai.summarize_conversation(MESSAGES)
            with (
                patch.object(ticket_ai.requests, "post", return_value=_reply("", status=403)),
                patch.object(ticket_ai.frappe, "log_error"),  # Error Log is MyISAM here: a rollback never undoes it
            ):
                with self.assertRaises(ticket_ai.TicketAIError) as caught:
                    ticket_ai.summarize_conversation(MESSAGES)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["provider"], {"require_parameters": True})
        self.assertEqual(body, ticket_ai._request_body(CONFIG["model"], CONFIG["base_url"], MESSAGES, ["Delivery"]))
        self.assertEqual(post.call_args.kwargs["timeout"], ticket_ai.TIMEOUT)
        self.assertEqual(caught.exception.http_status, 403)
        self.assertIn("API key", str(caught.exception))
