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
