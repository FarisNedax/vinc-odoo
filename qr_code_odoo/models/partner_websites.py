# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class vCardWebsites(models.Model):
    _name = 'partner.vcard.website'
    _description = 'Partner Website'
    
    # Link to partner.vcard model, not res.partner
    partner_id = fields.Many2one('partner.vcard', string="Partner", required=True, ondelete='cascade')
    website_url = fields.Char(string="Website URL", required=True)
    button_color = fields.Char(string="Button Color", help="Color for the button. Defaults to the vCard's secondary color if not specified.")
    button_logo = fields.Binary(string="Button Logo")
    name = fields.Char(string="Button Label", help="Label text for the button. If a logo is uploaded, the logo will be shown instead of this label.", required=False)
    add_to_cart_action = fields.Boolean(string="Add to Cart Action", default=False)
    full_url = fields.Char(string="Full URL", compute='_compute_full_url', store=False)
    active = fields.Boolean(string='Active', default=True, help='Archive this link to hide it from the vCard without deleting it')
    
    @api.model_create_multi
    def create(self, vals_list):
        """Set default button_color to partner's secondary_color if not provided"""
        for vals in vals_list:
            if 'partner_id' in vals:
                partner = self.env['partner.vcard'].browse(vals['partner_id'])
                # Set default button_color
                if 'button_color' not in vals or not vals.get('button_color'):
                    if partner and partner.secondary_color:
                        vals['button_color'] = partner.secondary_color
        return super(vCardWebsites, self).create(vals_list)
    
    @api.depends('website_url')
    def _compute_full_url(self):
        """Compute the full URL with protocol prefix if needed"""
        for record in self:
            if not record.website_url:
                record.full_url = ''
            elif record.website_url.startswith('http://') or record.website_url.startswith('https://'):
                record.full_url = record.website_url
            else:
                record.full_url = 'http://' + record.website_url
