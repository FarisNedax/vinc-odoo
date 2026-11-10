# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from odoo.http import Response
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.qr_code_odoo.controllers import main


@tagged('post_install', '-at_install')
class TestUnicodeDownloads(TransactionCase):
    """A card name with c/s/z carons must not 502 the QR and vCard downloads:
    the header has to be latin-1 safe (RFC 5987 filename*)."""

    def test_unicode_name_downloads(self):
        env = self.env(context=dict(self.env.context, install_mode=True))
        card = env['partner.vcard'].create({'name': 'Čengić Đurđa Šćekić Žarko', 'website_slug': 'cengic-unicode'})
        card.action_generate_website_page()
        card.website_page_id.is_published = True   # downloads are public only for published cards
        req = SimpleNamespace(
            env=env,
            make_response=lambda data, headers: Response(data, headers=headers),
        )
        ctrl = main.VCardController
        with patch.object(main, 'request', req):
            responses = (main.QRCodeController().download_qr_code(card.id), ctrl()._vcf_response(card))
        for res in responses:
            cd = res.headers['Content-Disposition']
            self.assertTrue(cd.isascii(), cd)
            self.assertIn("filename*=UTF-8''%C4%8Cengi%C4%87", cd)
