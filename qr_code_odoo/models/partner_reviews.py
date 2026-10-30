# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class PartnerReviews(models.Model):
    _name = 'partner.vcard.reviews'
    _description = 'Partner Reviews'
    _order = 'sequence, create_date desc'
    
    # Link to partner.vcard model
    partner_id = fields.Many2one('partner.vcard', string="Partner", required=True, ondelete='cascade')
    
    # Review fields
    reviewer_name = fields.Char(string="Reviewer Name", help="Optional name of the reviewer")
    # Sanitised on write: reviews are submitted by unauthenticated visitors via
    # /create_review, so the field must strip scripts / handlers / unsafe tags
    # before the value ever lands in a published-card template.
    review_text = fields.Html(
        string="Review Text", required=True,
        sanitize=True, sanitize_tags=True, sanitize_attributes=True,
        help="Review text (HTML sanitised on save to strip scripts and unsafe attributes).",
    )
    rating = fields.Selection([
        ('1', '1 Star'),
        ('2', '2 Stars'),
        ('3', '3 Stars'),
        ('4', '4 Stars'),
        ('5', '5 Stars')
    ], string="Rating", required=True, default='5')
    
    # Display control
    sequence = fields.Integer(string="Sequence", default=10, help="Order of display")
    is_published = fields.Boolean(string="Published", default=False, help="Show this review on the website")
    
    # Computed fields
    stars_display = fields.Char(string="Stars Display", compute='_compute_stars_display', store=True)
    
    @api.depends('rating')
    def _compute_stars_display(self):
        for record in self:
            if record.rating:
                star_count = int(record.rating)
                record.stars_display = '★' * star_count + '☆' * (5 - star_count)
            else:
                record.stars_display = ''


    @api.constrains('rating')
    def _check_rating(self):
        for record in self:
            if record.rating and int(record.rating) not in range(1, 6):
                raise ValidationError(self.env._("Rating must be between 1 and 5 stars."))
