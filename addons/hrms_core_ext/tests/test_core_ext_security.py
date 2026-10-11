# -*- coding: utf-8 -*-
"""Regression tests for the employee secret (PAN/Aadhaar) path.

These exist because the reveal path shipped broken: ``_hrms_reveal`` and
``action_view_aadhaar`` called ``self.user_has_groups(...)`` on an ``hr.employee``
recordset, which does not exist, so every reveal raised ``AttributeError``. No
test existed in this addon at all, which is why a green suite never caught it.

Keep these tightly scoped: prove the ciphertext lands encrypted, that an
authorised user can reveal it and is audited, and that an unauthorised user is
refused.
"""

import base64
import os

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

KEY = base64.b64encode(os.urandom(32)).decode()


@tagged("post_install", "-at_install", "hrms_core_ext")
class TestEmployeeSecretReveal(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "hrms.field_encryption_key", KEY
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Secret Holder"})
        cls.manager = cls.env["res.users"].create(
            {
                "name": "HR Manager",
                "login": "hrmanager_secret_test",
                "email": "hrmanager@example.invalid",
                "groups_id": [(6, 0, [cls.env.ref("hr.group_hr_manager").id])],
            }
        )
        cls.plain = cls.env["res.users"].create(
            {
                "name": "Plain User",
                "login": "plain_secret_test",
                "email": "plain@example.invalid",
                "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def _store(self, field, value):
        self.employee._hrms_set_enc(field, value)
        self.employee.flush_recordset()

    def _raw(self, column):
        self.env.cr.execute(
            f"select {column} from hr_employee where id=%s", [self.employee.id]
        )
        return self.env.cr.fetchone()[0]

    def test_pan_is_encrypted_at_rest(self):
        self._store("pan_number", "ABCDE1234F")
        raw = self._raw("pan_number_enc")
        self.assertNotEqual(raw, "ABCDE1234F")
        self.assertTrue(
            str(raw).startswith("enc:v1:"),
            "stored PAN must be AEAD ciphertext, not plaintext",
        )

    def test_reveal_returns_plaintext_and_writes_audit(self):
        self._store("pan_number", "ABCDE1234F")
        AuditLog = self.env["hrms.audit.log"]
        before = AuditLog.search_count([("model", "=", "hr.employee")])
        value = self.employee.with_user(self.manager)._hrms_reveal(
            "pan_number", reason="regression test"
        )
        self.assertEqual(value, "ABCDE1234F")
        after = AuditLog.search_count([("model", "=", "hr.employee")])
        self.assertEqual(after, before + 1, "a reveal must be audited")

    def test_reveal_denied_for_unauthorised_user(self):
        self._store("pan_number", "ABCDE1234F")
        with self.assertRaises(AccessError):
            self.employee.with_user(self.plain)._hrms_reveal("pan_number")

    def test_action_view_aadhaar_requires_hr_manager(self):
        self._store("aadhaar_number", "123412341234")
        with self.assertRaises(AccessError):
            self.employee.with_user(self.plain).action_view_aadhaar()
        action = self.employee.with_user(self.manager).action_view_aadhaar()
        self.assertEqual(action.get("res_model"), "hr.employee")

    def test_form_reveal_action_shows_plaintext_and_audits(self):
        self._store("pan_number", "ABCDE1234F")
        action = (
            self.employee.with_user(self.manager)
            .with_context(hrms_reveal_field="pan_number")
            .action_reveal_secret()
        )
        self.assertEqual(action["tag"], "display_notification")
        self.assertIn("ABCDE1234F", action["params"]["message"])

    def test_form_reveal_action_denied_for_unauthorised_user(self):
        self._store("pan_number", "ABCDE1234F")
        with self.assertRaises(AccessError):
            (
                self.employee.with_user(self.plain)
                .with_context(hrms_reveal_field="pan_number")
                .action_reveal_secret()
            )

    def test_form_reveal_action_rejects_unknown_field(self):
        with self.assertRaises(UserError):
            self.employee.with_user(self.manager).with_context(
                hrms_reveal_field="name"
            ).action_reveal_secret()
