# -*- coding: utf-8 -*-
"""Shared plumbing for all hrms_* addons.

Imported by every model in every addon so that crypto, audit and statutory-config
access behave identically everywhere.

Nothing in here hardcodes a statutory rate. Config values are always read through
:func:`statutory_value`, which requires an effective-dated config row that has
passed professional sign-off.
"""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

from odoo import SUPERUSER_ID, api, fields, models, tools
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field-level encryption (bank account, PAN, Aadhaar)
# ---------------------------------------------------------------------------
# AEAD so that tampering is detected, not silently decrypted. Key material comes
# from an ir.config_parameter holding a base64 32-byte key plus a version, so the
# key can be rotated without a schema change. Format:
#
#     enc:v1:<key_version>:<base64 nonce>:<base64 ciphertext+tag>
#
# AAD binds the ciphertext to model/field/id, so a value copied from one employee
# row to another fails to decrypt instead of leaking. See ADR-0008.

_ENC_PREFIX = "enc"


def _field_key() -> tuple:
    """Return (key_bytes, key_version) from ir.config_parameter."""
    key_b64 = (
        tools.config.get("hrms.field_encryption_key")
        or _env("FIELD_ENCRYPTION_KEY")
        or ""
    ).strip()
    version = (
        tools.config.get("hrms.field_encryption_key_version") or "1"
    ).strip()
    if not key_b64:
        raise UserError(
            "hrms: field encryption key is not configured. "
            "Set ir.config_parameter 'hrms.field_encryption_key' "
            "(base64 32 bytes) or env FIELD_ENCRYPTION_KEY. "
            "Generate: python3 -c \"import base64,os;"
            "print(base64.b64encode(os.urandom(32)).decode())\""
        )
    try:
        key = base64.b64decode(key_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise UserError(f"hrms: field encryption key is not valid base64: {exc}")
    if len(key) != 32:
        raise UserError(
            f"hrms: field encryption key must decode to 32 bytes, got {len(key)}"
        )
    return key, version


def _env(name, default=""):
    return os.environ.get(name, default)


def _aad(model: str, field_name: str, record_id) -> bytes:
    """Additional authenticated data. Binds ciphertext to its exact location."""
    return f"{model}|{field_name}|{record_id or 0}".encode()


def encrypt_value(plaintext, model: str, field_name: str, record_id=None) -> str:
    """Encrypt a string for storage. Empty/None values pass through untouched."""
    if plaintext in (None, False, ""):
        return plaintext
    text = str(plaintext)
    if text.startswith(f"{_ENC_PREFIX}:v"):
        return text  # already encrypted, do not double-encrypt
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key, version = _field_key()
    nonce = os.urandom(12)
    blob = AESGCM(key).encrypt(nonce, text.encode(), _aad(model, field_name, record_id))
    return ":".join(
        [_ENC_PREFIX, f"v{version}", base64.b64encode(nonce).decode(), base64.b64encode(blob).decode()]
    )


def decrypt_value(stored, model: str, field_name: str, record_id=None):
    """Decrypt a stored value. Plaintext (legacy) values pass through untouched."""
    if stored in (None, False, "") or not str(stored).startswith(f"{_ENC_PREFIX}:v"):
        return stored
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    parts = str(stored).split(":")
    if len(parts) != 4:
        raise UserError(f"hrms: malformed ciphertext in {model}.{field_name}")
    _, _, nonce_b64, blob_b64 = parts
    try:
        nonce = base64.b64decode(nonce_b64)
        blob = base64.b64decode(blob_b64)
    except binascii.Error as exc:
        raise UserError(f"hrms: malformed base64 in {model}.{field_name}: {exc}")

    # Try the current key first, then any previous versions, so a rotation does
    # not lock out existing rows.
    current_key, current_version = _field_key()
    candidates = [(current_version, current_key)]
    prev = (
        tools.config.get("hrms.field_encryption_key_previous")
        or _env("FIELD_ENCRYPTION_KEY_PREVIOUS")
        or ""
    ).strip()
    if prev:
        try:
            candidates.append(("0", base64.b64decode(prev, validate=True)))
        except (binascii.Error, ValueError):
            _logger.warning("hrms: previous field encryption key is invalid base64")
    stored_version = parts[1].lstrip("v")

    for candidate_version, key in candidates:
        if len(key) != 32:
            continue
        if stored_version not in (candidate_version, "0"):
            continue
        try:
            return AESGCM(key).decrypt(nonce, blob, _aad(model, field_name, record_id))
        except InvalidTag:
            # Wrong key, or the value was moved between rows.
            continue
        except Exception as exc:  # pragma: no cover - defensive
            _logger.error("hrms: decrypt failed for %s.%s: %s", model, field_name, exc)
            continue
    raise UserError(
        f"hrms: cannot decrypt {model}.{field_name} (key version {stored_version}). "
        "Either the key is wrong, or this value was copied from another record. "
        "Do not work around this by storing it in plaintext."
    )


class EncryptedChar(models.AbstractModel):
    """Mixin for a char field that is encrypted at rest and transparently decrypted.

    Subclasses set ``_encrypted_fields`` to a mapping of ``odoo_field ->
    {label, group}``. The mixin creates the real stored columns
    (``<name>_enc``) and exposes transparent ``<name>``/``<name>_display``
    accessors so callers never handle ciphertext.
    """

    _name = "hrms.mixin.encrypted"
    _description = "Encrypted field mixin"

    _encrypted_fields: dict = {}

    @api.model
    def _setup_encrypted_fields(self):
        """Create backing storage columns. Called from each concrete model's _setup."""
        cls = type(self)
        if getattr(cls, "_encrypted_ready", False):
            return
        for name, spec in cls._encrypted_fields.items():
            enc = f"{name}_enc"
            if enc not in cls._fields:
                setattr(
                    cls,
                    enc,
                    fields.Char(
                        string=f"{spec['label']} (encrypted)",
                        index=False,
                        copy=False,
                        groups=spec.get("group", "base.group_user"),
                        help="Ciphertext. Never read or write directly; use the "
                        "transparent accessor on the model.",
                    ),
                )
        cls._encrypted_ready = True

    # -- transparent accessors -------------------------------------------
    # Implemented per concrete model so the read/write path stays explicit and
    # auditable rather than hidden in __getattr__ magic.

    @api.model
    def _enc_write(self, field_name, record, value):
        enc = f"{field_name}_enc"
        if not hasattr(record, enc):
            return value
        return encrypt_value(value, record._name, field_name, record.id or 0)

    @api.model
    def _enc_read(self, field_name, record):
        enc = f"{field_name}_enc"
        raw = getattr(record, enc, None)
        if raw in (None, ""):
            return raw
        return decrypt_value(raw, record._name, field_name, record.id or 0)

    @api.model
    def _enc_masked(self, field_name, record):
        """Partially masked form, safe for display and for non-privileged readers."""
        value = self._enc_read(field_name, record)
        if value in (None, ""):
            return ""
        text = str(value)
        if len(text) <= 4:
            return "*" * len(text)
        return "*" * (len(text) - 4) + text[-4:]


# ---------------------------------------------------------------------------
# Webhook HMAC
# ---------------------------------------------------------------------------


def hmac_secret() -> str:
    secret = tools.config.get("hrms.webhook_hmac_secret") or _env("WEBHOOK_HMAC_SECRET") or ""
    if not secret:
        raise UserError(
            "hrms: webhook HMAC secret is not configured. "
            "Set ir.config_parameter 'hrms.webhook_hmac_secret' or env "
            "WEBHOOK_HMAC_SECRET (min 32 bytes)."
        )
    return secret


def hmac_sign(body: bytes, timestamp: str, nonce: str = "") -> str:
    """Return hex digest for the signed payload: ``ts.nonce.body``.

    Signing the timestamp is what makes replay detectable; the nonce lets the
    receiver reject a replay inside the tolerance window even if the attacker
    controls the timestamp.
    """
    secret = hmac_secret()
    if len(secret) < 32:
        _logger.warning(
            "hrms: webhook HMAC secret is shorter than 32 bytes (%d)", len(secret)
        )
    message = f"{timestamp}.{nonce}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def hmac_verify(body: bytes, timestamp: str, signature: str, nonce: str = "") -> bool:
    """Constant-time signature check plus timestamp freshness."""
    try:
        ts = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return False
    tolerance = int(_env("WEBHOOK_TOLERANCE_SECONDS", "300") or 300)
    delta = abs((datetime.utcnow() - ts).total_seconds())
    if delta > tolerance:
        _logger.warning("hrms: webhook timestamp outside tolerance (%.0fs)", delta)
        return False
    expected = hmac_sign(body, timestamp, nonce)
    return hmac.compare_digest(expected, signature or "")


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


class AuditLog(models.Model):
    """Append-only audit trail.

    A concrete model, not an AbstractModel: audit rows are persisted in their own
    table (``hrms_audit_log``) rather than stored on the audited record, so they
    survive record deletion. Nothing may edit or delete them, including
    SUPERUSER, because ``write``/``unlink`` raise.

    Use it through ``self.env["hrms.audit.log"].log(...)``.
    """

    _name = "hrms.audit.log"
    _description = "Audit log (append-only)"
    _order = "id desc"

    name = fields.Char(index=True, required=True)
    model = fields.Char(index=True, required=True)
    res_id = fields.Integer(index=True)
    action = fields.Selection(
        [
            ("create", "Create"),
            ("write", "Write"),
            ("unlink", "Delete"),
            ("read_sensitive", "Read (sensitive)"),
            ("approve", "Approve"),
            ("reject", "Reject"),
            ("release", "Release"),
            ("override", "Override"),
            ("lock", "Lock"),
            ("unlock", "Unlock"),
            ("auth", "Authentication"),
            ("ai_action", "AI action"),
        ],
        required=True,
        index=True,
    )
    user_id = fields.Many2one("res.users", ondelete="restrict", index=True)
    api_key_id = fields.Many2one(
        "res.users.apikeys",
        string="API key",
        ondelete="restrict",
    )
    on_behalf_of_id = fields.Many2one(
        "res.users",
        string="On behalf of",
        ondelete="restrict",
        help="Populated when a service or the AI layer acts for a user.",
    )
    changes = fields.Text(
        help="JSON: {field: {old, new}}. Sensitive values are redacted."
    )
    ip = fields.Char()
    request_id = fields.Char(index=True)
    note = fields.Text()

    # Immutability is enforced in Python (write/unlink raise) rather than by a
    # CHECK constraint, because a constraint cannot express "no UPDATE at all".

    # Redacted field-name fragments. Anything matching is stored as '***'.
    _sensitive_fragments = (
        "pan",
        "aadhaar",
        "aadhar",
        "uidai",
        "bank",
        "account_number",
        "iban",
        "ifsc",
        "salary",
        "passport",
        "dob",
        "secret",
        "token",
        "pin",
        "card",
        "ssn",
        "tax_id",
    )

    @api.model
    def _redact(self, values: dict) -> dict:
        if not isinstance(values, dict):
            return {}
        clean = {}
        for key, val in values.items():
            if any(frag in str(key).lower() for frag in self._sensitive_fragments):
                clean[key] = "***"
            elif isinstance(val, dict):
                clean[key] = self._redact(val)
            else:
                clean[key] = val
        return clean

    @api.model
    def log(
        self,
        model,
        res_id,
        action,
        changes=None,
        note=None,
        on_behalf_of=None,
        request_id=None,
    ):
        """Record an audit entry. Never raises: auditing must not break the request."""
        try:
            user = self.env.user
            sudo = self.sudo()
            ip = None
            try:
                ip = sudo._request.env["HTTP_X_FORWARDED_FOR"].split(",")[0].strip()
            except Exception:
                ip = None
            return sudo.create(
                {
                    "name": f"{model}:{res_id}:{action}",
                    "model": model,
                    "res_id": res_id,
                    "action": action,
                    "user_id": user.id,
                    "on_behalf_of_id": (on_behalf_of or user).id,
                    "changes": json.dumps(
                        sudo._redact(changes or {}), indent=2, sort_keys=True
                    ),
                    "note": note,
                    "ip": ip,
                    "request_id": request_id,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive
            _logger.error("hrms: AUDIT LOG WRITE FAILED model=%s id=%s: %s", model, res_id, exc)
            return self.env["hrms.audit.log"]

    def write(self, vals):
        raise AccessError("Audit log entries are immutable.")

    def unlink(self):
        raise AccessError("Audit log entries cannot be deleted.")

    @api.model
    def check_sod(self, record, action_label, extra_condition=None):
        """Segregation of duties: the actor must not be the subject.

        Called from every approval, claim, ticket and F&F release path. Raises
        rather than returning False so a caller cannot accidentally ignore it.
        """
        user = self.env.user
        if user._is_superuser():
            raise AccessError(
                f"hrms: segregation of duties cannot be satisfied by a superuser "
                f"approving '{action_label}'. Approve as a named HR Admin user so "
                f"the approval is attributable."
            )
        if extra_condition and not extra_condition:
            return False
        for attr in ("employee_id", "user_id", "requested_by", "create_uid", "partner_id"):
            related = record[attr] if attr in record._fields else None
            if related and related.id == user.employee_id.id:
                raise AccessError(
                    f"hrms: you cannot {action_label} your own request. "
                    f"Segregation of duties requires a different approver."
                )
            if related and hasattr(related, "user_id") and related.user_id.id == user.id:
                raise AccessError(
                    f"hrms: you cannot {action_label} your own request. "
                    f"Segregation of duties requires a different approver."
                )
        return True