# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
import logging
import re

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        """Sync partner.email from login (when login is an email and the
        partner has no email yet). Access rights are enforced by Odoo's
        standard groups + our ir.rule records — this override intentionally
        does NOT elevate users into site-wide groups."""
        users = super().create(vals_list)
        for user in users:
            if user.partner_id and user.login and not user.partner_id.email:
                if _EMAIL_RE.match(user.login):
                    user.partner_id.email = user.login
        return users

    def write(self, vals):
        """Sync partner.email from login when login changes."""
        result = super().write(vals)
        if 'login' in vals and vals['login']:
            for user in self:
                if (user.partner_id
                        and user.login
                        and not user.partner_id.email
                        and _EMAIL_RE.match(user.login)):
                    user.partner_id.email = user.login
        return result

    def fix_missing_emails(self):
        """Backfill partner.email from login for selected users."""
        fixed_count = 0
        for user in self:
            if (user.partner_id
                    and user.login
                    and not user.partner_id.email
                    and _EMAIL_RE.match(user.login)):
                user.partner_id.email = user.login
                fixed_count += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': self.env._('Email Fix Complete'),
                'message': self.env._('Fixed %s user(s) by setting partner email from login.', fixed_count),
                'type': 'success',
            },
        }
