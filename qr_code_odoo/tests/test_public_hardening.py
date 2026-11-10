# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user

from odoo.addons.qr_code_odoo.controllers import main


@tagged('post_install', '-at_install')
class TestPublicHardening(TransactionCase):
    """Public card routes: limiter, honeypot, publish checks, counters, .vcf escaping."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # install_mode short-circuits the Vinc license guard on create/write.
        cls.env = cls.env(context=dict(cls.env.context, install_mode=True))
        cls.card = cls.env['partner.vcard'].create({'name': 'Ann', 'website_slug': 'ann-hardening'})
        cls.public_env = cls.env(user=cls.env.ref('base.public_user'))
        cls.owner = new_test_user(cls.env, login='hardening_owner', groups='base.group_user')

    def _request(self, env=None, ip='10.0.0.1', body=None, session=None):
        return SimpleNamespace(
            env=env or self.public_env,
            session={} if session is None else session,
            httprequest=SimpleNamespace(remote_addr=ip, data=json.dumps(body or {})),
        )

    def test_limit_refuses_the_eleventh_post(self):
        req = self._request(env=self.env)
        results = [main._over_limit(req) for _ in range(11)]
        self.assertEqual(results, [False] * 10 + [True])
        # Another address has its own budget.
        self.assertFalse(main._over_limit(self._request(env=self.env, ip='10.0.0.2')))

    def test_honeypot_creates_no_lead(self):
        req = self._request(env=self.env, body={
            'contact_name': 'Bot', 'email_from': 'bot@example.com',
            'partner_id': self.card.id, main.HONEYPOT_FIELD: 'filled',
        })
        leads_before = self.env['crm.lead'].search_count([])
        with patch.object(main, 'request', req), \
                patch('odoo.addons.qr_code_odoo.controllers.license_guard._license_ok', return_value=True):
            result = main.LeadController().create_lead()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.env['crm.lead'].search_count([]), leads_before)

    def test_unpublished_card_hidden_from_public(self):
        self.assertFalse(self.card.is_published)
        with patch.object(main, 'request', self._request()):
            self.assertFalse(main._card_visible(self.card))
        with patch.object(main, 'request', self._request(env=self.env)):
            self.assertTrue(main._card_visible(self.card), 'admin may read any card')
        with patch.object(main, 'request', self._request(env=self.env(user=self.owner))):
            self.assertFalse(main._card_visible(self.card), 'another user\'s card stays hidden')

    def test_published_card_visible_to_public(self):
        self.card.action_generate_website_page()
        self.card.website_page_id.is_published = True
        with patch.object(main, 'request', self._request()):
            self.assertTrue(main._card_visible(self.card))
        self.card.website_page_id.is_published = False
        with patch.object(main, 'request', self._request()):
            self.assertFalse(main._card_visible(self.card))

    def test_preview_only_for_its_owner(self):
        preview = self.env['partner.vcard'].create({
            'name': 'Preview', 'website_slug': f'preview-{self.owner.id}'})
        with patch.object(main, 'request', self._request(env=self.env(user=self.owner))):
            self.assertTrue(main._card_visible(preview))
        with patch.object(main, 'request', self._request(env=self.env)):
            self.assertFalse(main._card_visible(preview))
        with patch.object(main, 'request', self._request()):
            self.assertFalse(main._card_visible(preview))

    def test_counts_once_per_session(self):
        session = {}
        with patch.object(main, 'request', self._request(session=session)):
            self.assertEqual([main._count_once(self.card, 'view') for _ in range(3)], [True, False, False])
            self.assertTrue(main._count_once(self.card, 'download'), 'each counter is separate')

    def test_vcf_escapes_values(self):
        self.card.name = 'Ann\nTEL:+15550000'
        self.card.company_name = 'A, B; C\\D'
        lines = self.card._generate_vcf().split('\n')
        self.assertIn('FN:Ann\\nTEL:+15550000', lines)
        self.assertIn('ORG:A\\, B\\; C\\\\D', lines)
        self.assertFalse([l for l in lines if l.startswith('TEL:')], 'no injected TEL line')
