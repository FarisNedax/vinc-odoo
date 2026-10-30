# -*- coding: utf-8 -*-
"""Rebuild published card pages so they pick up the translatable template
and get their texts translated into every installed language."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cards = env['partner.vcard'].search([('website_page_id', '!=', False)])
    for card in cards.filtered(lambda c: not (c.website_slug or '').startswith('preview-')):
        try:
            with cr.savepoint():
                card.with_context(skip_auto_regen=True).action_generate_website_page()
        except Exception as e:  # one bad card must not block the upgrade
            _logger.warning("Card page rebuild skipped for vCard %s: %s", card.id, e)
