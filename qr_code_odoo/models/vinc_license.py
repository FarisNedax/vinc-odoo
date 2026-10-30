import hashlib
import json
import logging
import requests
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

LICENSE_SERVER_URL = "https://getvinc.com"
VALIDATE_INTERVAL_HOURS = 168  # 7 days, overridden by server response
WARNING_DAYS = 30
DEGRADED_DAYS = 60


class VincLicense(models.Model):
    _name = "vinc.license"
    _description = "Vinc License"
    _rec_name = "license_status"

    license_key = fields.Char("License Key", groups="base.group_system")
    key_hint = fields.Char("Key (last 4)", readonly=True)
    database_fingerprint = fields.Char("Database Fingerprint", readonly=True)
    license_status = fields.Selection([
        ("not_activated", "Not Activated"),
        ("active", "Active"),
        ("warning", "Warning"),
        ("degraded", "Degraded"),
        ("suspended", "Suspended"),
        ("revoked", "Revoked"),
        ("failed", "Activation Failed"),
    ], default="not_activated", string="Status", readonly=True)
    activated_at = fields.Datetime("Activated At", readonly=True)
    last_validated_at = fields.Datetime("Last Validated At", readonly=True)
    last_validation_attempt_at = fields.Datetime("Last Validation Attempt", readonly=True)
    validation_interval_hours = fields.Integer("Validation Interval (hours)", default=VALIDATE_INTERVAL_HOURS)
    consecutive_failures = fields.Integer("Consecutive Failures", default=0, readonly=True)
    module_version = fields.Char("Module Version", readonly=True)
    server_url = fields.Char("License Server URL", default=LICENSE_SERVER_URL)
    request_email = fields.Char("Email Address", help="Email to receive your license key")

    def _get_fingerprint(self):
        """Generate a stable database fingerprint."""
        cr = self.env.cr
        cr.execute("SELECT current_database()")
        db_name = cr.fetchone()[0]

        db_uuid = self.env["ir.config_parameter"].sudo().get_param("database.uuid", "")
        create_date = self.env["ir.config_parameter"].sudo().get_param("database.create_date", "")

        raw = f"{db_name}|{db_uuid}|{create_date}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_module_version(self):
        """Get the current installed module version."""
        module = self.env["ir.module.module"].sudo().search([("name", "=", "qr_code_odoo")], limit=1)
        return module.installed_version if module else "unknown"

    def _get_license_record(self):
        """Get or create the singleton license record."""
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({})
        return record

    def _get_server_url(self):
        record = self._get_license_record()
        return (record.server_url or LICENSE_SERVER_URL).rstrip("/")

    def action_activate(self):
        """Activate a license key against the Vinc license server."""
        self.ensure_one()
        record = self

        if not record.license_key:
            raise UserError(self.env._("Please enter a license key and save before activating."))

        # Set key hint if not already set
        if not record.key_hint and record.license_key:
            record.sudo().write({"key_hint": record.license_key[-4:]})

        fingerprint = self._get_fingerprint()
        module_version = self._get_module_version()
        server_url = (record.server_url or LICENSE_SERVER_URL).rstrip("/")

        try:
            resp = requests.post(
                f"{server_url}/api/license/activate",
                json={
                    "license_key": record.license_key,
                    "database_fingerprint": fingerprint,
                    "module_version": module_version,
                    "odoo_version": "17.0",
                    "environment_metadata": {
                        "db_name": self.env.cr.dbname,
                    },
                },
                timeout=10,
            )
            data = resp.json()
        except requests.RequestException as e:
            _logger.warning("License activation network error: %s", e)
            record.sudo().write({
                "license_status": "not_activated",
                "database_fingerprint": fingerprint,
            })
            raise UserError(self.env._(
                "Could not reach the license server. Check your internet connection and try again."
            ))

        if resp.status_code == 200 and data.get("status") == "active":
            interval = data.get("validation_interval_hours", VALIDATE_INTERVAL_HOURS)
            now = fields.Datetime.now()
            record.sudo().write({
                "license_status": "active",
                "database_fingerprint": fingerprint,
                "activated_at": now,
                "last_validated_at": now,
                "last_validation_attempt_at": now,
                "validation_interval_hours": interval,
                "consecutive_failures": 0,
                "module_version": module_version,
            })
            _logger.info("Vinc license activated successfully.")
            return True
        else:
            error_msg = data.get("error_message", "Activation failed.")
            error_code = data.get("error_code", "UNKNOWN")
            _logger.error("License activation failed: %s - %s", error_code, error_msg)
            record.sudo().write({"license_status": "failed"})
            raise UserError(self.env._("License activation failed: %s", error_msg))

    def _cron_validate_license(self):
        """Periodic heartbeat validation. Called by Odoo cron."""
        record = self._get_license_record()

        if record.license_status in ("not_activated", "revoked") or not record.license_key:
            return

        fingerprint = record.database_fingerprint or self._get_fingerprint()
        module_version = self._get_module_version()
        server_url = self._get_server_url()
        now = fields.Datetime.now()

        record.sudo().write({"last_validation_attempt_at": now})

        try:
            resp = requests.post(
                f"{server_url}/api/license/validate",
                json={
                    "license_key": record.license_key,
                    "database_fingerprint": fingerprint,
                    "module_version": module_version,
                },
                timeout=10,
            )
            data = resp.json()
        except requests.RequestException as e:
            _logger.warning("License validation network error: %s", e)
            failures = record.consecutive_failures + 1
            record.sudo().write({"consecutive_failures": failures})
            self._update_degradation_status(record)
            return

        if resp.status_code == 200 and data.get("status") == "valid":
            record.sudo().write({
                "last_validated_at": now,
                "consecutive_failures": 0,
                "module_version": module_version,
            })
            self._update_degradation_status(record)
            _logger.info("Vinc license validated successfully.")
        else:
            error_code = data.get("error_code", "")
            failures = record.consecutive_failures + 1

            # Explicit rejection — server actively killed this key.
            # Take effect immediately, don't use the 30/60 day grace.
            if error_code in ("KEY_SUSPENDED", "KEY_REVOKED", "KEY_REFUNDED"):
                new_status = "suspended" if error_code == "KEY_SUSPENDED" else "revoked"
                _logger.warning("Vinc license %s by server (code=%s)", new_status, error_code)
                record.sudo().write({
                    "license_status": new_status,
                    "consecutive_failures": failures,
                })
                return

            _logger.warning(
                "License validation failed (attempt %d): %s",
                failures,
                data.get("error_message", "unknown"),
            )
            record.sudo().write({"consecutive_failures": failures})
            self._update_degradation_status(record)

    def _update_degradation_status(self, record):
        """Update license status based on last successful validation."""
        if not record.last_validated_at:
            return

        days_since = (fields.Datetime.now() - record.last_validated_at).days

        if days_since < WARNING_DAYS:
            new_status = "active"
        elif days_since < DEGRADED_DAYS:
            new_status = "warning"
        else:
            new_status = "degraded"

        if record.license_status != new_status:
            _logger.info("Vinc license status changed: %s -> %s", record.license_status, new_status)
            record.sudo().write({"license_status": new_status})

    def action_request_key(self):
        """Request a free license key via email (for Odoo App Store buyers)."""
        self.ensure_one()

        email = (self.request_email or "").strip()
        if not email or "@" not in email:
            raise UserError(self.env._("Please enter a valid email address."))

        server_url = self._get_server_url()

        try:
            resp = requests.post(
                f"{server_url}/api/license/request-key",
                json={"email": email},
                timeout=30,
            )
            data = resp.json()
        except requests.RequestException as e:
            _logger.warning("License key request network error: %s", e)
            raise UserError(self.env._(
                "Could not reach the license server. "
                "Check your internet connection and try again."
            ))

        if resp.status_code == 429:
            raise UserError(data.get("error") or self.env._("Too many requests. Please try again later."))

        if resp.status_code == 200 and data.get("ok"):
            license_key = data.get("license_key")
            if license_key:
                # Email failed but server returned the key directly — auto-fill it
                self.sudo().write({"license_key": license_key})
                if not self.key_hint:
                    self.sudo().write({"key_hint": license_key[-4:]})
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "type": "warning",
                        "title": "License Key Ready",
                        "message": "Email delivery failed, but your license key has been "
                                   "filled in automatically. Click Activate License to continue.",
                        "sticky": True,
                    },
                }
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "success",
                    "title": "License Key Sent",
                    "message": f"Check your inbox at {email} for your license key. "
                               "Paste it into the License Key field above and click Activate.",
                    "sticky": True,
                },
            }
        else:
            error_msg = data.get("error", "Request failed. Please try again.")
            raise UserError(error_msg)

    def action_change_key(self):
        """Reset the license so a new key can be entered."""
        self.ensure_one()
        self.sudo().write({
            "license_key": False,
            "key_hint": False,
            "license_status": "not_activated",
            "activated_at": False,
            "last_validated_at": False,
            "last_validation_attempt_at": False,
            "consecutive_failures": 0,
            "database_fingerprint": False,
            "module_version": False,
        })
        _logger.info("Vinc license key cleared — ready for new key entry.")

    def _effective_status(self):
        """Return the real license status, accounting for validation freshness.

        If the cron has been disabled or stopped running, this catches the
        staleness and updates the stored status so degradation still happens
        on schedule — no bypass by disabling the cron job.
        """
        self.ensure_one()
        status = self.license_status

        if status in ("active", "warning") and self.last_validated_at:
            days_since = (fields.Datetime.now() - self.last_validated_at).days
            if days_since >= DEGRADED_DAYS:
                self.sudo().write({"license_status": "degraded"})
                return "degraded"
            elif days_since >= WARNING_DAYS and status == "active":
                self.sudo().write({"license_status": "warning"})
                return "warning"

        return status

    def check_license(self):
        """Raise UserError if the license does not allow writes.

        Called from create/write overrides on protected models and from
        website controllers. Keeps the enforcement in one place so the
        thresholds and messages stay consistent.
        """
        record = self._get_license_record()
        status = record._effective_status()
        if status in ("active", "warning"):
            return  # all good
        if status == "suspended":
            raise UserError(self.env._(
                "This Vinc license has been suspended by the administrator. "
                "All changes are blocked. Contact your reseller or Vinc support."
            ))
        if status == "revoked":
            raise UserError(self.env._(
                "This Vinc license has been revoked. "
                "Go to Vinc ▸ License to enter a new license key, "
                "or contact your reseller."
            ))
        if status == "degraded":
            raise UserError(self.env._(
                "Vinc license validation has failed for over 60 days. "
                "The module is in read-only mode — no changes are allowed. "
                "Go to Vinc ▸ License and re-validate, or contact your reseller."
            ))
        # not_activated, failed, or anything else
        raise UserError(self.env._(
            "Vinc is not licensed. Go to Vinc ▸ License to enter and "
            "activate your license key before using the module."
        ))

    def is_active(self):
        """Check if the license allows full operation."""
        record = self._get_license_record()
        return record._effective_status() in ("active", "warning")

    def is_degraded(self):
        """Check if the license is in read-only degraded mode."""
        record = self._get_license_record()
        return record.license_status == "degraded"

    def get_status_message(self):
        """Get a user-facing status message for banners."""
        record = self._get_license_record()
        if record.license_status == "not_activated":
            return "Vinc license has not been activated. Go to Settings to enter your license key."
        if record.license_status == "warning":
            days_left = DEGRADED_DAYS - (fields.Datetime.now() - record.last_validated_at).days
            return f"License validation has not succeeded recently. Module will continue working for {max(days_left, 0)} more days. Check your network connection or contact your reseller."
        if record.license_status == "degraded":
            return "License validation has failed for over 60 days. Module is in read-only mode. Contact your reseller."
        if record.license_status == "suspended":
            return "This license has been suspended by the administrator. Contact your reseller or Vinc support."
        if record.license_status == "revoked":
            return "This license has been revoked. Enter a new license key or contact your reseller."
        if record.license_status == "failed":
            return "License activation failed. Go to Settings to try again."
        return None
