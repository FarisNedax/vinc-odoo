# -*- coding: utf-8 -*-
"""End-to-end card flow: create a card, its QR and vCard, the public page,
and a lead captured from that page."""
import base64
import json

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestCardFlow(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The license guard refuses every write on an unlicensed DB.
        cls.env['vinc.license'].sudo()._get_license_record().write({
            'license_status': 'active',
            'last_validated_at': fields.Datetime.now(),
        })
        cls.card = cls.env['partner.vcard'].create({
            'name': 'Ada Lovelace',
            'website_slug': 'ada-lovelace-test',
            'company_name': 'Analytical Engines',
            'function': 'Engineer',
            'email': 'ada@example.com',
            'phone': '+38761000000',
        })

    def test_card_creation_builds_qr(self):
        card = self.card
        self.assertTrue(card.qr_code_data.endswith(f'/qr/{card.id}'))
        self.assertTrue(base64.b64decode(card.qr_code).startswith(b'\x89PNG'))

        res = self.url_open(f'/vcard/qr_code/download/{card.id}')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.startswith(b'\x89PNG'))

    def test_vcard_download(self):
        res = self.url_open(f'/website/vcard/download/{self.card.id}')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/vcard', res.headers['Content-Type'])
        self.assertIn('BEGIN:VCARD', res.text)
        self.assertIn('FN:Ada Lovelace', res.text)
        self.assertIn('EMAIL:ada@example.com', res.text)
        self.assertEqual(self.card.vcard_download_count, 1)

    def test_public_card_page(self):
        action = self.card.action_generate_website_page()
        self.assertEqual(action['params']['type'], 'success', action['params']['message'])
        self.assertTrue(self.card.website_page_id.is_published)

        res = self.url_open('/ada-lovelace-test')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Ada Lovelace', res.text)
        self.assertIn('Analytical Engines', res.text)

        # QR scans land on the card page.
        res = self.url_open(f'/qr/{self.card.id}', allow_redirects=False)
        self.assertIn(res.status_code, (301, 302, 303))
        self.assertTrue(res.headers['Location'].endswith('/ada-lovelace-test'))
        self.assertEqual(self.card.qr_code_scan_count, 1)

    def test_lead_capture_creates_crm_lead(self):
        # The card page posts a bare JSON body, not a JSON-RPC envelope.
        res = self.url_open('/create_lead', data=json.dumps({
            'partner_id': self.card.id,
            'contact_name': 'Charles Babbage',
            'email_from': 'charles@example.com',
            'phone': '+38761111111',
            'description': 'Met at the expo',
        }), headers={'Content-Type': 'application/json'})
        self.assertEqual(res.status_code, 200)
        result = res.json()['result']
        self.assertEqual(result['status'], 'success', result)

        lead = self.env['crm.lead'].browse(result['opportunity_id'])
        self.assertEqual(lead.partner_vcard_id, self.card)
        self.assertEqual(lead.email_from, 'charles@example.com')
        self.assertEqual(lead.contact_name, 'Charles Babbage')
        self.assertEqual(lead.type, 'opportunity')

    def test_public_pages_render(self):
        for url in ('/get-started', '/vinculum/guide', f'/nfc/setup/{self.card.id}'):
            res = self.url_open(url)
            self.assertEqual(res.status_code, 200, url)

    def test_manager_pages_render(self):
        self.env['res.users'].create({
            'name': 'Vinc Manager', 'login': 'vinc_mgr', 'password': 'vinc_mgr_pw',
            'group_ids': [(6, 0, [self.env.ref('qr_code_odoo.group_vinc_manager').id])],
        })
        self.authenticate('vinc_mgr', 'vinc_mgr_pw')
        res = self.url_open('/bulk-onboard')
        self.assertEqual(res.status_code, 200)
