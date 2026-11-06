"""Controller rules of the AI Analysis doctypes and of the HD Settings AI Analysis section.

The controllers run on plain dicts with frappe.db stubbed, so these tests need neither the
migrated tables nor any rows.
"""

import json
import os
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.utils import today

from helpdesk.helpdesk.doctype.hd_ai_action.hd_ai_action import HDAIAction
from helpdesk.helpdesk.doctype.hd_ai_exclusion.hd_ai_exclusion import HDAIExclusion, last8
from helpdesk.helpdesk.doctype.hd_ai_gold_label.hd_ai_gold_label import HDAIGoldLabel
from helpdesk.helpdesk.doctype.hd_ai_issue_code.hd_ai_issue_code import HDAIIssueCode
from helpdesk.helpdesk.doctype.hd_settings import hd_settings

DOCTYPE_DIR = os.path.dirname(os.path.dirname(hd_settings.__file__))
with open(os.path.join(DOCTYPE_DIR, "hd_settings", "hd_settings.json")) as fh:
    DEFAULTS = {df["fieldname"]: df.get("default") for df in json.load(fh)["fields"]}


def settings(**values):
    doc = frappe._dict(enable_ai_analysis=1, ai_analysis_legal_approval="PDPPL-TEST-1")
    doc.update(values)
    doc.meta = frappe._dict(get_field=lambda fieldname: frappe._dict(default=DEFAULTS.get(fieldname)))
    return doc


class TestAIDoctypes(TestCase):
    def test_settings_rules_apply_only_when_enabled(self):
        validate = hd_settings.HDSettings.validate_ai_analysis
        validate(settings(enable_ai_analysis=0, ai_analysis_legal_approval=""))
        validate(settings())  # blank model fields mean the JSON defaults, which must pass together
        validate(settings(ai_analysis_council_models="openai/a\n\n google/b \nx-ai/c\n", ai_analysis_chairman_model="anthropic/z"))
        for values in (
            {"ai_analysis_legal_approval": "  "},
            {"ai_analysis_council_models": "openai/gpt-5.4\nopenai/gpt-4.1"},  # one vendor
            {"ai_analysis_council_models": "openai/a\ngoogle/b\nx-ai/c\nmeta/d"},  # four models
            {"ai_analysis_chairman_model": "Google/gemini-2.5-flash"},  # a council vendor
        ):
            with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
                validate(settings(**values))

    def test_exclusion_keeps_last_8_digits_and_rejects_active_duplicates(self):
        self.assertEqual(last8("+974 ٥٥٥٥ ١٢٣٤"), "55551234")
        doc = frappe._dict(name="new", exclusion_type="Phone", value=" 00974-5555-1234 ", active=1)
        with patch.object(frappe.db, "exists", return_value=None) as exists:
            HDAIExclusion.validate(doc)
        self.assertEqual(doc.value, "55551234")
        exists.assert_called_once_with(
            "HD AI Exclusion", {"exclusion_type": "Phone", "value": "55551234", "active": 1, "name": ("!=", "new")}
        )
        self.assertRaises(frappe.ValidationError, HDAIExclusion.validate, frappe._dict(doc, value="101"))
        with patch.object(frappe.db, "exists", return_value="other"):
            self.assertRaises(frappe.ValidationError, HDAIExclusion.validate, frappe._dict(doc))
            removed = frappe._dict(doc, active=0, removed_reason="")
            self.assertRaises(frappe.ValidationError, HDAIExclusion.validate, removed)
            removed.removed_reason = "A real customer after all"
            HDAIExclusion.validate(removed)  # a removed row never clashes
        self.assertEqual(removed.removed_by, frappe.session.user)
        self.assertTrue(removed.removed_on)

    def test_gold_label_codes_must_exist_and_include_the_primary(self):
        names = {"DLV_LATE": "DLV_LATE", "dlv_late": "DLV_LATE", "NEW": "NEW"}

        def exists(doctype, filters):
            return None if doctype == "HD AI Gold Label" else names.get(filters)

        doc = frappe._dict(name="g1", contact="c1", labeller="a@example.com", codes="dlv_late\n\nNEW\nDLV_LATE\n", primary_code="DLV_LATE")
        with patch.object(frappe.db, "exists", side_effect=exists):
            HDAIGoldLabel.validate(doc)
            self.assertEqual(doc.codes, "DLV_LATE\nNEW")
            for values in ({"codes": "NOT_A_CODE"}, {"codes": "NEW", "primary_code": "DLV_LATE"}):
                with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
                    HDAIGoldLabel.validate(frappe._dict(doc, **values))
        with patch.object(frappe.db, "exists", return_value="g0"):  # same contact and labeller
            self.assertRaises(frappe.ValidationError, HDAIGoldLabel.validate, frappe._dict(doc))

    def test_merged_code_is_retired_and_loops_are_rejected(self):
        def chain(links):
            return patch.object(frappe.db, "get_value", side_effect=lambda doctype, code, field: links.get(code))

        doc = frappe._dict(name="A", merged_into="B", status="Active")
        with chain({"B": "C"}):
            HDAIIssueCode.validate(doc)
        self.assertEqual(doc.status, "Retired")
        with chain({"B": "C", "C": "B"}):  # a loop further down still ends
            HDAIIssueCode.validate(frappe._dict(doc))
        for merged_into, links in (("B", {"B": "C", "C": "A"}), ("A", {})):  # via C, and into itself
            with self.subTest(links=links), chain(links), self.assertRaises(frappe.ValidationError):
                HDAIIssueCode.validate(frappe._dict(doc, merged_into=merged_into))

    def test_done_action_gets_done_on(self):
        doc = frappe._dict(status="Done", done_on=None)
        HDAIAction.validate(doc)
        self.assertEqual(str(doc.done_on), today())
        kept = frappe._dict(status="Done", done_on="2026-04-12")
        HDAIAction.validate(kept)
        self.assertEqual(kept.done_on, "2026-04-12")
        still_open = frappe._dict(status="Open", done_on=None)
        HDAIAction.validate(still_open)
        self.assertIsNone(still_open.done_on)

    def test_no_ai_doctype_gives_the_agent_role_access(self):
        for folder in sorted(os.listdir(DOCTYPE_DIR)):
            if folder.startswith("hd_ai_"):
                with open(os.path.join(DOCTYPE_DIR, folder, folder + ".json")) as fh:
                    self.assertNotIn("Agent", {perm["role"] for perm in json.load(fh)["permissions"]}, folder)
