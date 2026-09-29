# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
from odoo import models, fields, api


class LeadbackPreview(models.TransientModel):
    """Transient model for previewing email and message templates"""
    _name = 'leadback.preview'
    _description = 'Lead-Back Preview'

    preview_type = fields.Selection([
        ('email', 'Email'),
        ('message', 'Message'),
    ], string='Preview Type', required=True)
    
    subject = fields.Char(string='Subject', readonly=True)
    body_html = fields.Html(string='Email Body', readonly=True)
    body_text = fields.Text(string='Message Body', readonly=True)
    links_html = fields.Html(string='Generated Links', readonly=True)
    message_preview = fields.Text(string='Message Preview', readonly=True)
    
    # Email preview fields
    email_to = fields.Char(string='To', readonly=True)
    email_from = fields.Char(string='From', readonly=True)
    
    # Message preview fields
    message_to = fields.Char(string='Message To', readonly=True)
    channels = fields.Char(string='Channels', readonly=True)

