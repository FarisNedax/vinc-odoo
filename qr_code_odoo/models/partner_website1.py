# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
from odoo import models, api, fields
from odoo.exceptions import ValidationError
from .card_i18n import sync_card_view_translations
import base64
from PIL import Image
import io
class PartnerWebsite(models.Model):
    _inherit = 'partner.vcard'

    @api.onchange('website_slug', 'primary_color', 'secondary_color')
    def _onchange_website_slug(self):
        self._compute_website_full_url()

    def _own_attachment_res_id(self):
        """The ir.attachment.res_id this record's own attachments must carry.

        Inside an onchange `self.id` is a NewId, so fall back to the saved
        record the pseudo-record was built from. A card that has never been
        saved has neither, and therefore owns nothing yet.
        """
        self.ensure_one()
        return self.id if isinstance(self.id, int) else self._origin.id

    def _owns_attachment(self, attachment):
        """True only when `attachment` is this record's own attachment row.

        Attachment references can end up shared between cards (duplicating a
        card used to hand the copy the original's row, and data edits can do
        the same). Rewriting such a row in place changes every card pointing
        at it, so an attachment that is missing, belongs to another model, or
        carries another record's id must never be written - a fresh one is
        created for this record instead.
        """
        self.ensure_one()
        res_id = self._own_attachment_res_id()
        return bool(attachment) and bool(res_id) \
            and attachment.res_model == 'partner.vcard' \
            and attachment.res_id == res_id

    # Imperative side-effect method (no field assignment), invoked from the
    # matching @api.onchange and from controllers. Do NOT decorate with
    # @api.depends — it misleads the registry into treating this as a compute.
    def _update_attachment_if_image_changed(self):
        """Create or update the attachment when image_url is changed."""
        for record in self:
            if record.image_url:
                # Step 1: Create an attachment unless this record already owns one
                if not record._owns_attachment(record.attachment_id):
                    # Create a new attachment for the uploaded image
                    new_attachment = self.env['ir.attachment'].create({
                        'name': f"Partner Image {record.name}",
                        'type': 'binary',
                        'datas': record.image_url,
                        'res_model': 'partner.vcard',
                        'res_id': record._own_attachment_res_id(),
                        'public': True,  # Make it accessible to the public
                        'mimetype': 'image/png',  # Adjust based on the actual image type
                    })
                    # Link the newly created attachment to the record
                    record.attachment_id = new_attachment
                else:
                    # Step 2: Update the existing attachment (if an image already exists)
                    record.attachment_id.write({
                        'datas': record.image_url,
                        'name': f"Partner Image {record.name}",
                        'mimetype': 'image/png',  # Adjust MIME type if needed
                    })
    
    @api.onchange('image_url')
    def _onchange_image_url(self):
        """Trigger update when image_url changes and regenerate the website page."""
        # Call the function to handle attachment creation/update
        self._update_attachment_if_image_changed()
        # Optionally regenerate the website page if the slug is set
        if self.website_slug:
            self.action_generate_website_page()

    # Imperative side-effect method. See note above _update_attachment_if_image_changed.
    def _update_banner_attachment_if_image_changed(self):
        """Create or update the attachment when banner_image is changed."""
        for record in self:
            if record.banner_image:
                # Step 1: Create an attachment unless this record already owns one
                if not record._owns_attachment(record.banner_attachment_id):
                    # Create a new attachment for the uploaded banner image
                    new_attachment = self.env['ir.attachment'].create({
                        'name': f"Partner Banner Image {record.name}",
                        'type': 'binary',
                        'datas': record.banner_image,
                        'res_model': 'partner.vcard',
                        'res_id': record._own_attachment_res_id(),
                        'public': True,  # Make it accessible to the public
                        'mimetype': 'image/png',  # Adjust based on the actual image type
                    })
                    # Link the newly created attachment to the record
                    record.banner_attachment_id = new_attachment
                else:
                    # Step 2: Update the existing attachment (if an image already exists)
                    record.banner_attachment_id.write({
                        'datas': record.banner_image,
                        'name': f"Partner Banner Image {record.name}",
                        'mimetype': 'image/png',  # Adjust MIME type if needed
                    })
            else:
                # Step 3: If banner_image is removed, clear the attachment reference
                if record.banner_attachment_id:
                    # Only delete the row when it is this record's own - a shared
                    # reference belongs to another card and unlinking it would
                    # blank that card's banner too. Dropping the reference is enough.
                    owned = record._owns_attachment(record.banner_attachment_id)
                    old_attachment = record.banner_attachment_id
                    record.banner_attachment_id = False
                    if owned:
                        try:
                            old_attachment.unlink()
                        except Exception:
                            # If deletion fails, just continue - the reference is already cleared
                            pass
    
    @api.onchange('banner_image')
    def _onchange_banner_image(self):
        """Trigger update when banner_image changes and regenerate the website page."""
        # Call the function to handle attachment creation/update
        self._update_banner_attachment_if_image_changed()
        # Optionally regenerate the website page if the slug is set
        if self.website_slug:
            self.action_generate_website_page()

    def action_generate_website_page(self):
        """Generate or update the website page dynamically when the button is clicked."""
        from odoo.exceptions import UserError
        import logging
        _logger = logging.getLogger(__name__)
        
        # A card with no slug has no page to build: the view would be created
        # with name/key derived from an empty slug, which fails NOT NULL at
        # flush and aborts the whole transaction - after this method has
        # already returned "Success!". Skip those records and say so instead.
        skipped = self.filtered(lambda r: not r.website_slug)
        if skipped:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': self.env._('Website slug required'),
                    'message': self.env._('No website was generated. These cards have no '
                                          'URL slug: %s. Enter a unique slug first.',
                                          ', '.join(skipped.mapped('display_name'))),
                    'type': 'danger',
                    'sticky': True,
                }
            }

        try:
            for record in self:
                # Ensure that the image is attached and publicly accessible
                record._update_attachment_if_image_changed()
                record._update_banner_attachment_if_image_changed()
        
                # Get the public URL for the attachment
                image_url = f'/website/image/ir.attachment/{record.attachment_id.id}/datas' if record.attachment_id else None
                banner_url = f'/website/image/ir.attachment/{record.banner_attachment_id.id}/datas' if record.banner_attachment_id else None
        
                # Build the dynamic template
                template = record._build_dynamic_template(image_url, banner_url)
        
                # Check if a view already exists for this slug
                existing_view = self.env['ir.ui.view'].search([('key', '=', f'website.{record.website_slug}')], limit=1)
        
                if existing_view:
                    # Update the existing view with the dynamic template
                    existing_view.write({'arch_db': template})
                    # Clear caches more efficiently - only invalidate specific view
                    # Use registry.clear_cache() instead of model.clear_caches() for better performance
                    self.env.registry.clear_cache()
                    view_id = existing_view.id
                else:
                    # Create a new view with the dynamic template
                    new_view = self.env['ir.ui.view'].create({
                        'name': record.website_slug,
                        'type': 'qweb',
                        'key': f'website.{record.website_slug}',
                        'arch_db': template,  # Use the generated template
                        'website_id': self.env['website'].get_current_website().id,
                    })
                    view_id = new_view.id

                sync_card_view_translations(self.env['ir.ui.view'].browse(view_id))

                # Check if a website page exists for the slug, if not, create it
                existing_page = self.env['website.page'].search([('url', '=', f'/{record.website_slug}')], limit=1)
                if existing_page:
                    # Update the existing page
                    existing_page.write({
                        'name': record.website_slug,
                        'view_id': view_id,
                        'is_published': True,
                    })
                    record.website_page_id = existing_page.id  # Assign existing page ID to the partner
                else:
                    # Create the corresponding website.page entry and mark it as published
                    new_page = self.env['website.page'].create({
                        'name': record.website_slug,
                        'url': f"/{record.website_slug}",
                        'view_id': view_id,
                        'website_id': self.env['website'].get_current_website().id,
                        'is_published': True
                    })
                    # Store the created website page reference
                    record.website_page_id = new_page.id  # Assign new page ID to the partner
                
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': self.env._('Success!'),
                    'message': self.env._('Website generated with %s template!', self.website_template),
                    'type': 'success',
                    'sticky': True,
                }
            }
        except Exception as e:
            _logger.error(f"Error generating website: {str(e)}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': self.env._('Error'),
                    'message': self.env._('Failed: %s', e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
    
    def _build_dynamic_template(self, image_url, banner_url=None):
        """Build the dynamic website template based on selected template."""
        import logging
        _logger = logging.getLogger(__name__)
        
        # Compute referral URL at build time
        self._compute_referral_signup_url()
        referral_url = self.referral_signup_url or '/get-started'
        
        # Route to appropriate template builder based on selection
        if self.website_template == 'modern':
            template = self._build_modern_template(image_url, banner_url, referral_url)
        elif self.website_template == 'minimal':
            template = self._build_minimal_template(image_url, banner_url, referral_url)
        elif self.website_template == 'corporate':
            template = self._build_corporate_template(image_url, banner_url, referral_url)
        elif self.website_template == 'creative':
            template = self._build_creative_template(image_url, banner_url, referral_url)
        else:  # classic or default
            template = self._build_classic_template(image_url, banner_url, referral_url)
        
        # Log error only if referral URL validation fails
        if '{referral_url}' in template:
            _logger.error(f"Template generation error: Referral URL interpolation failed for vCard {self.id}")
        
        return template
    
    def _get_modern_css(self):
        """Get modern template CSS"""
        return """
        <style>
            .vcard-template-modern #wrap {{
                background: #f0f4f8 !important;
                padding: 0 !important;
            }}
            .vcard-template-modern .container-fluid {{
                max-width: 100% !important;
                padding: 0 !important;
            }}
            .vcard-template-modern .s_cover {{
                display: grid !important;
                grid-template-columns: 1fr 1fr !important;
                gap: 40px !important;
                align-items: center !important;
                min-height: 100vh !important;
                padding: 80px 60px !important;
            }}
            .vcard-template-modern .image-container {{
                grid-column: 2 !important;
                order: 2 !important;
            }}
            .vcard-template-modern h1,
            .vcard-template-modern .btn,
            .vcard-template-modern div[t-att-style*="about"] {{
                text-align: left !important;
            }}
            .vcard-template-modern .img-fluid {{
                width: 300px !important;
                height: 300px !important;
                border-radius: 20px !important;
                box-shadow: 0 20px 60px rgba(0,0,0,0.2) !important;
            }}
            .vcard-template-modern .btn {{
                border-radius: 50px !important;
                padding: 15px 40px !important;
                font-size: 18px !important;
                font-weight: 700 !important;
                box-shadow: 0 10px 25px rgba(0,0,0,0.15) !important;
                transition: all 0.3s ease !important;
            }}
            .vcard-template-modern .btn:hover {{
                transform: translateY(-4px) !important;
                box-shadow: 0 15px 35px rgba(0,0,0,0.25) !important;
            }}
            .vcard-template-modern .social-icon {{
                width: 60px !important;
                height: 60px !important;
                border-radius: 15px !important;
                margin: 8px !important;
                box-shadow: 0 8px 20px rgba(0,0,0,0.12) !important;
            }}
            @media (max-width: 992px) {{
                .vcard-template-modern .s_cover {{
                    grid-template-columns: 1fr !important;
                }}
                .vcard-template-modern .image-container {{
                    order: 0 !important;
                }}
                .vcard-template-modern h1,
                .vcard-template-modern .btn {{
                    text-align: center !important;
                }}
            }}
        </style>
        """
    
    def _get_minimal_css(self, primary_color=None):
        """Get minimal template CSS"""
        primary_color = primary_color or '#ffffff'
        return f"""
        <style>
            .vcard-template-minimal #wrap {{
                background: {primary_color} !important;
            }}
            .vcard-template-minimal .container-fluid {{
                max-width: 600px !important;
            }}
            .vcard-template-minimal * {{
                border-radius: 0 !important;
            }}
            .vcard-template-minimal .img-fluid {{
                border: 1px solid #e0e0e0 !important;
                box-shadow: none !important;
            }}
            .vcard-template-minimal .btn {{
                background: transparent !important;
                border: 2px solid currentColor !important;
                box-shadow: none !important;
                font-weight: 400 !important;
            }}
            .vcard-template-minimal .btn:hover {{
                opacity: 0.7 !important;
            }}
            .vcard-template-minimal h1 {{
                font-weight: 300 !important;
                font-size: 2.5rem !important;
            }}
            .vcard-template-minimal h4 {{
                font-weight: 300 !important;
                text-transform: uppercase !important;
                letter-spacing: 3px !important;
                font-size: 0.9rem !important;
            }}
            .vcard-template-minimal .social-icon {{
                background: transparent !important;
                border: 1px solid currentColor !important;
                box-shadow: none !important;
            }}
            .vcard-template-minimal .social-icon:hover {{
                opacity: 0.6 !important;
            }}
            .vcard-template-minimal .border.rounded {{
                box-shadow: none !important;
                border: 1px solid #e0e0e0 !important;
            }}
            .vcard-template-minimal .minimal-tab-content {{
                background-color: inherit !important;
            }}
        </style>
        """
    
    def _get_corporate_css(self, primary_color=None, secondary_color=None):
        """Get corporate template CSS"""
        primary_color = primary_color or '#e86e26'
        secondary_color = secondary_color or '#1c1f3a'
        return f"""
        <style>
            /* Page base */
            .vcard-template-corporate #wrap {{
                background: {primary_color} !important;
            }}
            .vcard-template-corporate .container-fluid {{
                max-width: 980px !important;
                padding: 0 16px !important;
            }}
            .vcard-template-corporate * {{ box-sizing: border-box; }}

            /* Split header: image left, name panel right */
            .vcard-template-corporate .s_cover {{ 
                background: transparent !important; 
                padding: 32px 0 0 0 !important; 
            }}
            .vcard-template-corporate .s_cover .s_allow_columns.container {{ 
                display: grid !important; 
                grid-template-columns: 320px 1fr !important; 
                align-items: stretch !important; 
                gap: 24px !important; 
                text-align: left !important; 
            }}
            .vcard-template-corporate .image-container h1 {{ margin: 0 !important; }}
            .vcard-template-corporate .image-container .img-fluid {{ 
                width: 100% !important; 
                height: auto !important; 
                border-radius: 18px !important; 
                box-shadow: 0 20px 40px rgba(0,0,0,0.18) !important; 
                border: 6px solid #ffffff !important;
            }}
            .vcard-template-corporate .s_cover h1.display-3 {{ display: none !important; }} /* hide centered duplicate */

            /* Name panel on right */
            .vcard-template-corporate .s_cover .container > h1 + div {{ display:none; }}
            .vcard-template-corporate .s_cover .s_allow_columns.container::before {{ content: ''; }}
            .vcard-template-corporate .s_cover .name-panel {{ 
                background: {secondary_color} !important; 
                color: #fff !important; 
                border-radius: 22px !important; 
                padding: 28px !important; 
                box-shadow: 0 18px 36px rgba(0,0,0,0.24) !important; 
            }}
            /* Move the following siblings (name/about/buttons) into the name panel visually */
            .vcard-template-corporate .s_cover .s_allow_columns.container {{ position: relative; }}
            .vcard-template-corporate .s_cover .s_allow_columns.container > .image-container {{ grid-column: 1; }}
            .vcard-template-corporate .s_cover .s_allow_columns.container > h1,
            .vcard-template-corporate .s_cover .s_allow_columns.container > div[t-att-style*="about"],
            .vcard-template-corporate .s_cover .s_allow_columns.container > a.btn,
            .vcard-template-corporate .s_cover .s_allow_columns.container > div:has(#leadModal),
            .vcard-template-corporate .s_cover .s_allow_columns.container > script + #leadModal {{ grid-column: 2; }}
            .vcard-template-corporate .s_cover .s_allow_columns.container > h1 + div {{ grid-column: 2; }}
            .vcard-template-corporate .s_cover .s_allow_columns.container > h1.display-3 + div,
            .vcard-template-corporate .s_cover .s_allow_columns.container > div[t-att-style*="about"] {{ 
                background: {secondary_color} !important; 
                border-radius: 22px 22px 0 0 !important; 
                padding: 28px 28px 8px 28px !important; 
                color: #fff !important; 
            }}
            .vcard-template-corporate .s_cover .s_allow_columns.container > h1.display-3 strong {{ color: #fff !important; font-weight: 800 !important; }}
            .vcard-template-corporate .s_cover .s_allow_columns.container > div[t-att-style*="about"] p {{ color: rgba(255,255,255,0.9) !important; margin: 0 0 10px 0 !important; }}

            /* Orange action band */
            .vcard-template-corporate .action-band {{ 
                background: {primary_color} !important; 
                padding: 16px 22px !important; 
                border-radius: 0 0 22px 22px !important; 
                display: flex !important; 
                gap: 18px !important; 
                align-items: center !important; 
                box-shadow: 0 12px 24px rgba(0,0,0,0.18) !important; 
            }}
            .vcard-template-corporate .action-band .icon {{ 
                width: 56px; height: 56px; 
                border-radius: 50%; 
                border: 2px solid rgba(255,255,255,0.9); 
                display: inline-flex; align-items: center; justify-content: center; 
                color: #fff; font-size: 22px; 
                background: transparent; 
            }}

            /* Re-style primary buttons within header */
            .vcard-template-corporate .s_cover .btn {{ 
                border-radius: 12px !important; 
                padding: 12px 18px !important; 
                font-weight: 600 !important; 
                border: none !important; 
                background: {primary_color} !important; 
                color: #fff !important; 
                box-shadow: 0 8px 16px rgba(0,0,0,0.18) !important; 
            }}

            /* Cards below (About/Contact/Address etc.) */
            .vcard-template-corporate .o_container_small .border.rounded {{
                background: {primary_color} !important;
                border: none !important; 
                border-radius: 18px !important; 
                box-shadow: 0 10px 24px rgba(14,30,37,0.12), 0 2px 6px rgba(14,30,37,0.06) !important; 
                padding: 18px !important; 
            }}
            .vcard-template-corporate h4 {{ 
                color: {primary_color} !important; 
                font-weight: 800 !important; 
            }}

            /* Floating action buttons (bottom corners) */
            .vcard-template-corporate .fab-left, 
            .vcard-template-corporate .fab-right {{ 
                position: fixed; 
                bottom: 26px; 
                z-index: 1000; 
                width: 74px; height: 74px; 
                border-radius: 50%; 
                background: {primary_color}; 
                color: #fff; 
                display: flex; align-items: center; justify-content: center; 
                box-shadow: 0 18px 36px rgba(0,0,0,0.22); 
            }}
            .vcard-template-corporate .fab-left {{ left: 22px; }}
            .vcard-template-corporate .fab-right {{ right: 22px; }}

            /* Social icons consistency - match button design */
            .vcard-template-corporate .social-icon {{ 
                width: 60px !important;
                height: 60px !important;
                border-radius: 8px !important;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                text-decoration: none !important;
                transition: transform 0.1s ease !important;
            }}
            .vcard-template-corporate .social-icon:hover {{
                transform: scale(0.95) !important;
            }}
        </style>
        """
    
    def _get_creative_css(self, primary_color=None):
        """Get creative template CSS"""
        primary_color = primary_color or '#ffffff'
        # Convert hex to rgba for semi-transparent backgrounds
        def hex_to_rgba(hex_color, alpha=0.98):
            hex_color = hex_color.lstrip('#')
            r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            return f"rgba({r},{g},{b},{alpha})"
        
        primary_rgba = hex_to_rgba(primary_color, 0.98)
        primary_rgba_60 = hex_to_rgba(primary_color, 0.6)
        
        return f"""
        <style>
            @keyframes gradientShift {{
                0% {{ background-position: 0% 50%; }}
                50% {{ background-position: 100% 50%; }}
                100% {{ background-position: 0% 50%; }}
            }}
            @keyframes float {{
                0%, 100% {{ transform: translateY(0px); }}
                50% {{ transform: translateY(-20px); }}
            }}
            .vcard-template-creative #wrap {{
                background: {primary_color} !important;
            }}
            .vcard-template-creative .container-fluid {{
                background: {primary_rgba} !important;
                border-radius: 50px !important;
                box-shadow: 0 40px 100px rgba(0,0,0,0.4) !important;
                backdrop-filter: blur(30px) !important;
                border: 4px solid {primary_rgba_60} !important;
            }}
            .vcard-template-creative .s_cover {
                animation: float 5s ease-in-out infinite !important;
            }
            .vcard-template-creative .img-fluid {
                border: 8px solid white !important;
                border-radius: 50% !important;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3) !important;
                transition: transform 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55) !important;
            }
            .vcard-template-creative .img-fluid:hover {
                transform: scale(1.15) rotate(8deg) !important;
            }
            .vcard-template-creative .btn {
                border-radius: 50px !important;
                padding: 18px 50px !important;
                font-weight: 800 !important;
                font-size: 18px !important;
                box-shadow: 0 15px 40px rgba(0,0,0,0.25) !important;
                transition: all 0.4s cubic-bezier(0.68, -0.55, 0.265, 1.55) !important;
            }
            .vcard-template-creative .btn:hover {
                transform: translateY(-6px) scale(1.08) !important;
                box-shadow: 0 20px 50px rgba(0,0,0,0.4) !important;
            }
            .vcard-template-creative h1 {
                font-weight: 900 !important;
                font-size: 4.5rem !important;
                text-shadow: 4px 4px 12px rgba(0,0,0,0.2) !important;
                animation: float 3s ease-in-out infinite !important;
            }
            .vcard-template-creative .social-icon {
                width: 70px !important;
                height: 70px !important;
                border-radius: 50% !important;
                box-shadow: 0 10px 30px rgba(0,0,0,0.25) !important;
                transition: all 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55) !important;
            }
            .vcard-template-creative .social-icon:hover {
                transform: translateY(-10px) rotate(360deg) scale(1.2) !important;
                box-shadow: 0 20px 50px rgba(0,0,0,0.4) !important;
            }
            .vcard-template-creative .s_text_block {
                border-radius: 30px !important;
                transition: transform 0.3s ease !important;
            }
            .vcard-template-creative .s_text_block:hover {
                transform: translateY(-5px) scale(1.02) !important;
            }
        </style>
        """
    
    def _build_classic_template(self, image_url, banner_url=None, referral_url=None):
        """The original/classic template"""
        if referral_url is None:
            referral_url = self.get_referral_signup_url()
        return f"""
        <t t-name="website.{self.website_slug}">
            <t t-set="partner" t-value="request.env['partner.vcard'].sudo().browse({self.id})"/>
    
            <!-- Dashboard Button (visible to logged-in internal users) -->
            <t t-if="request.env.user and not request.env.user._is_public() and not request.env.user.share">
                <style>
                    @media only screen and (max-width: 600px) {{
                        .dashboard-btn-container {{
                            top: 10px !important;
                            right: 10px !important;
                        }}
                        .dashboard-btn-container a {{
                            padding: 10px 16px !important;
                            font-size: 12px !important;
                        }}
                        .dashboard-btn-container .fa {{
                            font-size: 14px !important;
                        }}
                    }}
                </style>
                <div class="dashboard-btn-container" style="position: fixed; top: 20px; right: 20px; z-index: 1000;">
                    <a href="/web#action=qr_code_odoo.action_user_dashboard" 
                       style="display: inline-flex; align-items: center; gap: 8px; padding: 12px 20px; background: rgba(69, 126, 184, 0.9); color: white; text-decoration: none; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 14px; font-weight: 500; transition: all 0.3s ease;"
                       onmouseover="this.style.background='rgba(69, 126, 184, 1)'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';"
                       onmouseout="this.style.background='rgba(69, 126, 184, 0.9)'; this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.2)';">
                        <i class="fa fa-dashboard" style="font-size: 16px;"></i>
                        <span>Back to Dashboard</span>
                    </a>
                </div>
            </t>
    
            <!-- Use custom vCard layout without header and footer -->
            <t t-call="qr_code_odoo.vcard_layout">
                <!-- Main content with responsive width constraint and top padding -->
                <div id="wrap" class="oe_structure oe_empty"
                     t-att-style="partner.primary_color and 'background-color: ' + partner.primary_color or ''"
                     t-att-data-auto-show-lead="str(partner.auto_show_lead_form and partner.show_form and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-auto-download-vcard="str(partner.auto_download_vcard and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-vcard-download-url="'/website/vcard/download/' + str(partner.id)"
                     style="text-align: center; font-family: 'Poppins', sans-serif; padding-top: 0;">

                
                <!-- Responsive container with max-width -->
                <div class="container-fluid" style="max-width: 800px; margin: 0 auto; padding: 0; overflow: visible;">
                <!-- Main content continues here -->

            <!-- Classic Template Header with Cover Image (React Design) -->
            <div class="banner-container" style="position: relative; width: 100%; height: 200px; margin-bottom: 56px; z-index: 1; overflow: visible; padding-bottom: 0;">
                <t t-if="partner.banner_attachment_id">
                    <!-- Banner Image with Dark Overlay -->
                    <div class="banner-image-wrapper" style="width: 100%; height: 100%; overflow: hidden; background-color: #ffffff; position: relative; padding: 18px 28px; box-sizing: border-box;">
                        <img t-att-src="'/website/image/ir.attachment/' + str(partner.banner_attachment_id.id) + '/datas'"
                             alt="" 
                             style="width: 100%; height: 100%; object-fit: contain; display: block;"
                             onerror="this.style.display='none';"/>
                    </div>
                </t>
                <t t-if="not partner.banner_attachment_id">
                    <!-- Fallback banner with primary color and dark overlay -->
                    <div class="banner-image-wrapper" 
                         t-att-style="'width: 100%; height: 100%; background-color: ' + (partner.primary_color or '#e0e0e0') + '; position: relative;'">
                        <div style="position: absolute; inset: 0; background: rgba(0,0,0,0.4); z-index: 1;"></div>
                    </div>
                </t>
                
                <!-- Profile Picture positioned to overlap banner (half circle over banner) -->
                <div class="profile-picture-wrapper" 
                     style="position: absolute; bottom: -30px; left: 50%; transform: translateX(-50%); z-index: 10; background: transparent; pointer-events: none; overflow: visible;">
                    <t t-if="partner.attachment_id">
                        <img t-att-src="'/website/image/ir.attachment/' + str(partner.attachment_id.id) + '/datas'"
                             alt=""
                             class="img img-fluid rounded-circle"
                             t-att-style="'width: 112px; height: 112px; object-fit: cover; border: 4px solid ' + (partner.primary_color or '#ffffff') + '; box-shadow: 0 4px 12px rgba(0,0,0,0.3); background-color: ' + (partner.primary_color or '#ffffff') + '; display: block;'"
                             loading="lazy"/>
                    </t>
                </div>
            </div>

            <!-- Section with centered content (React Classic Design) -->
            <section class="s_cover o_colored_level s_parallax_no_overflow_hidden o_cc o_cc3"
                     t-att-style="'padding-top: 14px; position: relative; z-index: 2; margin-top: 0; background: ' + (partner.primary_color or '#ffffff') + '; min-height: auto; overflow: visible;'">
                <div class="s_allow_columns container" style="text-align: center; padding: 0 16px;">

                    <!-- Partner Name (React Design Style) -->
                    <h1 style="margin-top: 0; padding-top: 0; margin-bottom: 12px; font-size: 1.75rem; font-weight: bold; color: #1e293b;">
                        <t t-esc="partner.name"/>
                    </h1>

                    <!-- Tagline/About section with secondary color (React Design) -->
                    <div t-if="partner.about" style="margin-top: 12px; margin-bottom: 24px; display: inline-block;">
                        <div t-att-style="'background: ' + (partner.secondary_color or '#dbeafe') + '20; padding: 8px 16px; border-radius: 8px; border: 1px solid ' + (partner.secondary_color or '#bfdbfe') + '80; max-width: 600px; margin: 0 auto;'">
                            <p t-att-style="'color: ' + (partner.secondary_color or '#1e40af') + '; font-size: 0.875rem; font-weight: 500; line-height: 1.5; margin: 0;'">
                                <t t-out="partner.about"/>
                            </p>
                        </div>
                    </div>
                    <div t-if="not partner.about and partner.function" style="margin-top: 12px; margin-bottom: 24px; display: inline-block;">
                        <div t-att-style="'background: ' + (partner.secondary_color or '#dbeafe') + '20; padding: 8px 16px; border-radius: 8px; border: 1px solid ' + (partner.secondary_color or '#bfdbfe') + '80; max-width: 600px; margin: 0 auto;'">
                            <p t-att-style="'color: ' + (partner.secondary_color or '#1e40af') + '; font-size: 0.875rem; font-weight: 500; line-height: 1.5; margin: 0;'">
                                <t t-esc="partner.function"/>
                            </p>
                        </div>
                    </div>

        

      <!-- MAIN ACTION BUTTONS (React Classic Design - Grid Layout) -->
<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-top: 24px; max-width: 400px; margin-left: auto; margin-right: auto; margin-bottom: 24px;">
    <!-- Get Info Button (Full Width) -->
<a t-att-href="'/website/vcard/download/' + str(partner.id)"
       t-att-style="'grid-column: 1 / -1; background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-block; text-align: center;'"
       onmouseover="this.style.transform='scale(0.95)'"
       onmouseout="this.style.transform='scale(1)'">
       <t t-set="vinc_label">Get %(name)s's Info</t><t t-out="vinc_label % {{'name': partner.name.split(' ')[0] if partner.name else ''}}"/>
    </a>
    
    <!-- Drop Your Info Button (Full Width) -->
    <t t-if="partner.show_form">
        <a href="#" 
           t-att-style="'grid-column: 1 / -1; background-color: ' + (partner.secondary_color or '#3b82f6') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-block; text-align: center;'"
           data-toggle="modal" 
           data-target="#leadModal"
           onmouseover="this.style.transform='scale(0.95)'"
           onmouseout="this.style.transform='scale(1)'">
           <t t-if="partner.lead_button_label" t-esc="partner.lead_button_label"/><t t-else="">Drop Your Info</t>
        </a>
    </t>
    
    <!-- Email Button (Half Width) -->
    <a t-if="partner.email"
       t-att-href="'mailto:' + partner.email"
       t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-block; text-align: center; cursor: pointer;'"
       onmouseover="this.style.transform='scale(0.95)'"
       onmouseout="this.style.transform='scale(1)'"
       onclick="window.open(this.getAttribute('href'), '_self'); return false;">
       Email
    </a>
    
    <!-- Call Button (Half Width) -->
    <a t-if="partner.phone"
       t-att-href="'tel:' + partner.phone"
       t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-block; text-align: center;'"
       onmouseover="this.style.transform='scale(0.95)'"
       onmouseout="this.style.transform='scale(1)'">
       Call
    </a>
  </div>


<!-- Modal Structure -->
<div class="modal fade" id="leadModal" tabindex="-1" role="dialog" aria-labelledby="leadModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true" data-dismiss-on-backdrop="true">
  <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
    <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
      <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
        <div style="display: flex; align-items: center; width: 100%;">
          <div style="flex: 1;">
            <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="leadModalLabel">Fill in your details</h5>
          </div>
          <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
            <span aria-hidden="true">×</span>
        </button>
      </div>
      </div>
      <div class="modal-body" style="padding: 16px 24px 24px 24px;">
        <div id="successMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
          <i class="fa fa-check-circle me-2"></i>Thank you! I look forward to talking with you soon.
        </div>
<form id="leadForm">


    <!-- Unhide and display the partner_id field -->
    <!-- Hidden Input for lead_tag_ids -->
<div class="form-group">
    <input type="hidden" class="form-control" id="partnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
    <input type="hidden" id="leadTagIds" name="lead_tag_ids" t-att-value="','.join(map(str, partner.lead_tag_ids.ids))"/>
    <input type="hidden" id="formThankYouMessage" t-att-value="partner.form_thank_you_message or 'Thank you! I look forward to talking with you soon.'"/>

</div>


    <!-- Form fields for lead information -->
    <div class="form-group">
        <label for="fullName">Full name <span class="text-danger">*</span></label>
        <input type="text" class="form-control" id="fullName" name="full_name" required="required" placeholder="Your name"/>
    </div>
    <div class="form-group">
        <label for="email">Email <span class="text-danger">*</span></label>
        <input type="email" class="form-control" id="email" name="email" required="required" placeholder="you@example.com"/>
    </div>
    <div class="form-group">
        <label for="phone">Phone</label>
        <input type="tel" class="form-control" id="phone" name="phone" placeholder="Your phone number"/>
        <input type="hidden" id="phone_full" name="phone_full"/>
    </div>
    <style>
        /* Lead modal form layout — keep all fields visually consistent. */
        #leadModal .form-group {{
            position: relative;
            margin-bottom: 14px;
        }}
        #leadModal .form-group label {{
            display: block;
            margin-bottom: 4px;
            font-weight: 500;
            color: #374151;
        }}
        #leadModal .form-group .form-control,
        #leadModal .form-group input.form-control {{
            display: block;
            width: 100%;
            height: 40px;
            box-sizing: border-box;
        }}
        #leadModal textarea.form-control {{
            height: auto;
            min-height: 80px;
        }}
        /* intl-tel-input wrapper — full width, block, stacks under the label. */
        #leadModal .iti {{
            display: block !important;
            width: 100%;
        }}
        #leadModal .iti__flag-container {{
            position: absolute;
            top: 0;
            bottom: 0;
            left: 0;
            right: auto;
            z-index: 2;
        }}
        #leadModal .iti__selected-flag {{
            z-index: 4;
            position: relative;
            display: flex;
            align-items: center;
            height: 100%;
            padding: 0 10px 0 12px;
            background-color: #f8f9fa;
            border-right: 1px solid #dee2e6;
            border-radius: 4px 0 0 4px;
            cursor: pointer;
            min-width: 76px;
        }}
        #leadModal .iti__flag-box {{ margin-right: 6px; }}
        #leadModal .iti__arrow {{
            margin-left: 6px;
            width: 0;
            height: 0;
            border-left: 3px solid transparent;
            border-right: 3px solid transparent;
            border-top: 4px solid #555;
        }}
        #leadModal .iti__selected-dial-code {{
            margin-left: 2px;
            font-size: 14px;
            color: #374151;
        }}
        #leadModal #phone {{
            padding-left: 88px !important;
        }}
        #leadModal .iti__country-list {{ z-index: 9999; }}
    </style>
    <div class="form-group">
        <label for="notes">Notes</label>
        <textarea class="form-control" id="notes" name="notes" placeholder="Anything else you'd like to share (optional)"></textarea>
    </div>

</form>




      </div>
      <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; flex-direction: column; gap: 12px;">
        <button type="button" id="submitLeadBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 12px 24px; border-radius: 8px; width: 100%;'">
          Share My Contact
        </button>
        <small style="text-align: center; color: #6b7280; font-size: 12px; margin: 0;"><t t-set="vinc_label">* By clicking the 'Share My Contact' button, I agree to be contacted by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
      </div>
    </div>
  </div>
</div>

<!-- QR Code Modal -->
<div class="modal fade" id="qrCodeModal" tabindex="-1" role="dialog" aria-labelledby="qrCodeModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
  <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 400px;">
    <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
      <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
        <div style="display: flex; align-items: center; width: 100%;">
          <div style="width: 40px; height: 40px; background: #f3f4f6; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin-right: 12px;">
            <i class="fa fa-qrcode" style="font-size: 20px; color: #6b7280;"></i>
          </div>
          <div style="flex: 1;">
            <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="qrCodeModalLabel">
              <t t-if="partner.name" t-esc="partner.name"/><t t-else="">QR Code</t>
            </h5>
            <p style="margin: 4px 0 0 0; font-size: 14px; color: #6b7280;">Scan to connect</p>
          </div>
          <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>
      <div class="modal-body" style="padding: 16px 24px 24px 24px; text-align: center;">
        <p style="margin: 0 0 20px 0; font-size: 14px; color: #6b7280; line-height: 1.5;">
          <t t-set="vinc_label">Scan this QR code to quickly save %(name)s's information to your device.</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/>
        </p>
        <div t-att-style="'padding: 20px; border-radius: 12px; display: inline-block; box-shadow: 0 2px 8px rgba(0,0,0,0.1); background: ' + (partner.primary_color or '#ffffff') + ';'">
          <img t-att-src="'/vcard/qr_code/download/' + str(partner.id)" 
               alt="QR Code" 
               style="width: 250px; height: 250px; max-width: 100%; display: block;"/>
        </div>
      </div>
      <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; justify-content: space-between; gap: 12px;">
        <button type="button" class="btn" data-dismiss="modal" style="background: transparent; border: none; color: #6b7280; font-weight: 500; padding: 10px 20px; flex: 1;">
          Close
        </button>
        <a t-att-href="'/website/vcard/download/' + str(partner.id)" 
           class="btn" 
           t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; flex: 1; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px;'"
          <i class="fa fa-download"></i>
          <span>Download vCard</span>
        </a>
      </div>
    </div>
  </div>
</div>

<!-- Service Request Modal -->
<div class="modal fade" id="serviceRequestModal" tabindex="-1" role="dialog" aria-labelledby="serviceRequestModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
  <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
    <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
      <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
        <div style="display: flex; align-items: center; width: 100%;">
          <div style="flex: 1;">
            <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="serviceRequestModalLabel">
              Request Service
            </h5>
          </div>
          <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
            <span aria-hidden="true">×</span>
          </button>
        </div>
      </div>
      <div class="modal-body" style="padding: 16px 24px 24px 24px;">
        <div id="serviceRequestSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
          <i class="fa fa-check-circle me-2"></i>Thank you! Your service request has been sent. We'll be in touch shortly.
        </div>
        <form id="serviceRequestForm">
          <!-- Hidden Inputs -->
          <div class="form-group">
            <input type="hidden" class="form-control" id="serviceRequestPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
            <input type="hidden" id="serviceRequestServiceId" name="service_id" value=""/>
            <input type="hidden" id="serviceRequestServiceName" name="service_name" value=""/>
            <input type="hidden" id="serviceRequestServiceDescription" name="service_description" value=""/>
          </div>

          <!-- Service Info (Read-only) -->
          <div class="form-group" style="margin-bottom: 20px;">
            <label style="margin-bottom: 8px; font-weight: 600; color: #111827;"><strong>Service:</strong></label>
            <p id="serviceRequestServiceDisplay" t-att-style="'margin: 0; padding: 12px; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #e5e7eb; border-radius: 8px; color: #111827; font-weight: 600; font-size: 16px;'"></p>
          </div>

          <!-- Form fields -->
          <div class="form-group">
            <label for="serviceRequestFullName">Full name<span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="serviceRequestFullName" name="full_name" required="required"/>
          </div>
          <div class="form-group">
            <label for="serviceRequestEmail">Email<span class="text-danger">*</span></label>
            <input type="email" class="form-control" id="serviceRequestEmail" name="email" required="required"/>
          </div>
          <div class="form-group">
            <label for="serviceRequestPhone">Phone</label>
            <input type="tel" class="form-control" id="serviceRequestPhone" name="phone" placeholder="Your Phone"/>
            <input type="hidden" id="serviceRequestPhoneFull" name="phone_full"/>
          </div>
          <style>
            /* Fix intl-tel-input styling for service request modal */
            #serviceRequestModal .form-group {{
                position: relative;
            }}
            #serviceRequestModal .iti {{
                width: 100%;
                display: block;
            }}
            #serviceRequestModal .iti__flag-container {{
                position: absolute;
                top: 0;
                bottom: 0;
                right: auto;
                left: 0;
                z-index: 2;
            }}
            #serviceRequestModal .iti__selected-flag {{
                z-index: 4;
                position: relative;
                display: flex;
                align-items: center;
                height: 100%;
                padding: 0 10px 0 8px;
                background-color: #f8f9fa;
                border-right: 1px solid #dee2e6;
                cursor: pointer;
                min-width: 70px;
            }}
            #serviceRequestModal .iti__flag-box {{
                margin-right: 4px;
            }}
            #serviceRequestModal .iti__arrow {{
                margin-left: 4px;
                width: 0;
                height: 0;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-top: 4px solid #555;
            }}
            #serviceRequestModal #serviceRequestPhone {{
                padding-left: 80px !important;
            }}
            #serviceRequestModal .iti__selected-dial-code {{
                margin-left: 2px;
                margin-right: 2px;
                font-size: 14px;
            }}
            #serviceRequestModal .iti__country-list {{
                z-index: 9999;
            }}
          </style>
          <!-- Container for dynamic, service-specific custom questions -->
          <div id="serviceRequestCustomQuestions"></div>

          <div class="form-group">
            <label for="serviceRequestNotes">Additional Details</label>
            <textarea class="form-control" id="serviceRequestNotes" name="notes" rows="4" placeholder="Add any additional information or requirements..."></textarea>
          </div>

          <div class="text-center" style="padding-top: 10px;">
            <button type="button" id="submitServiceRequestBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%;'">Send Request</button>
          </div>
        </form>
      </div>
      <div class="modal-footer" style="border-top: none; padding: 0 24px 24px 24px; text-align: center;">
        <small style="color: #6b7280; font-size: 12px;"><t t-set="vinc_label">* By clicking 'Send Request', I agree to be contacted by %(name)s regarding this service</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                                </div>
                            </div>
                        </div>
                    </div>

<!-- Review Modal -->
<div class="modal fade" id="reviewModal" tabindex="-1" role="dialog" aria-labelledby="reviewModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
  <div class="modal-dialog" role="document">
    <div class="modal-content">
      <div class="modal-header">
       <h5 class="modal-title" style="text-align: center;" id="reviewModalLabel">Leave a Review</h5>
        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
          <span aria-hidden="true">&#215;</span>
        </button>
      </div>
      <div class="modal-body">
        <div id="reviewSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
          <i class="fa fa-check-circle me-2"></i>Thank you for your review! We appreciate your feedback.
        </div>
<form id="reviewForm" onsubmit="return false;">

    <!-- Hidden Input for partner_id -->
    <div class="form-group">
        <input type="hidden" class="form-control" id="reviewPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
        <input type="hidden" id="reviewThankYouMessage" t-att-value="partner.review_thank_you_message or 'Thank you for your review! We appreciate your feedback.'"/>
    </div>

    <!-- Form fields for review information -->
    <div class="form-group">
        <label for="reviewerName">Your Name<span class="text-danger">*</span></label>
        <input type="text" class="form-control" id="reviewerName" name="reviewer_name" required="required"/>
    </div>
    
    <div class="form-group">
        <label for="reviewRating">Rating<span class="text-danger">*</span></label>
        <div class="star-rating" style="font-size: 32px; color: #ffc107; cursor: pointer;">
            <span class="star" data-rating="1">&#9734;</span>
            <span class="star" data-rating="2">&#9734;</span>
            <span class="star" data-rating="3">&#9734;</span>
            <span class="star" data-rating="4">&#9734;</span>
            <span class="star" data-rating="5">&#9734;</span>
        </div>
        <input type="hidden" id="reviewRating" name="rating" value="5" required="required"/>
    </div>
    
    <div class="form-group">
        <label for="reviewText">Your Review<span class="text-danger">*</span></label>
        <textarea class="form-control" id="reviewText" name="review_text" rows="4" required="required"></textarea>
    </div>

    <div class="text-center" style="padding-top: 5px;">
        <button type="button" id="submitReviewBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%; text-decoration: none; display: inline-block; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                onmouseover="this.style.transform='scale(0.95)'"
                onmouseout="this.style.transform='scale(1)'">Submit Review</button>
    </div>
</form>

      </div>
     <div class="modal-footer" style="justify-content: center !important; padding: 0;">
    <small><t t-set="vinc_label">* Your review will be visible once approved by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/> </small>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- Load widget.js and other scripts -->
                    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/css/intlTelInput.css"/>
                    <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
                    <script type="text/javascript" src="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/js/bootstrap.min.js"></script>
                    <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/js/intlTelInput.min.js"></script>
                    <!-- Ensure widget.js comes after jQuery and intl-tel-input -->
                    <script type="text/javascript" t-attf-src="/qr_code_odoo/static/src/js/widget.js"></script>
                </div>
            </section>
           
<t t-if="partner.website_ids">
    <section class="s_text_block o_colored_level pt0 pb0"
             t-att-style="'background-color: ' + (partner.primary_color or '#fff') + '; text-align: center;'">
        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000')">Websites</h4>
        
        <!-- Use the same container class as the Contact Information section -->
        <div class="s_allow_columns o_container_small">
            <!-- Flex container with wrapping and centered items -->
            <div class="d-flex flex-wrap justify-content-center">
                <t t-foreach="partner.website_ids" t-as="partner_website">
                    <!-- Item container taking up 50% width -->
                    <div class="d-flex justify-content-center p-2" style="flex: 0 0 50%; max-width: 50%;">
                        <a t-att-href="'http://' + partner_website.website_url if not (partner_website.website_url.startswith('http://') or partner_website.website_url.startswith('https://')) else partner_website.website_url"
                           class="btn"
                           t-att-style="'width: 100%; background-color: ' + (partner_website.button_color or partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-block; text-align: center; border: none;'"
                           target="_blank"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'">
                            <t t-if="partner_website.button_logo">
                                <img t-att-src="'data:image/png;base64,' + partner_website.button_logo.decode('utf-8')"
                                     alt="Logo" class="img-fluid" style="max-height: 50px;"/>
                            </t>
                            <t t-else="">
                                <t t-esc="partner_website.name"/>
                            </t>
                        </a>
                    </div>
                </t>
            </div>
        </div>
    </section>
</t>
<t t-if="partner.video_ids">
    <section class="s_text_block o_colored_level pt0 pb0"
             t-att-style="'background-color: ' + (partner.primary_color or '#fff') + '; text-align: center;'">
        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000')">Videos</h4>
        
        <div class="s_allow_columns o_container_small">
            <div class="d-flex flex-column align-items-center">
                <t t-foreach="partner.video_ids" t-as="partner_video">
                    <div class="p-2 w-100">  <!-- Full width container for each video -->
                        <div class="video-container" style="position: relative;">
                            <iframe width="100%" height="315" 
                                    t-att-src="partner_video.embed_url + '?rel=0&amp;modestbranding=1&amp;showinfo=0'"
                                    frameborder="0" 
                                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                    allowfullscreen="true"
                                    t-att-title="partner_video.name"
                                    loading="lazy"
                                    onerror="this.style.display='none'; this.nextElementSibling.style.display='block';"></iframe>
                            <div class="video-fallback" style="display: none; padding: 20px; text-align: center; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #dee2e6; border-radius: 5px;">
                                <p><i class="fa fa-exclamation-triangle text-warning"></i> Video could not be loaded</p>
                                <a t-att-href="partner_video.video_url" target="_blank" class="btn btn-primary btn-sm">
                                    <i class="fa fa-external-link"></i> Watch on YouTube
                                </a>
                            </div>
                        </div>
                    </div>
                </t>
            </div>
        </div>
    </section>
</t>












            <!-- Social Media Section, shown only if any social media URLs are set -->

                <t t-if="partner.has_socials">
                    <section class="s_text_block o_colored_level pt0 pb0"
                             t-att-style="'background-color: ' + (partner.primary_color or '#fff') + '; text-align: center;'">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000')">Socials</h4>
        <div class="s_allow_columns container">
          <div class="s_social_media o_not_editable text-center"
               style="display: flex; justify-content: center; flex-wrap: wrap; gap: 15px;">

                <!-- Social Media Links with User's Custom Colors -->
                <!-- WhatsApp -->
                <a t-if="partner.whatsapp_url" t-att-href="partner.whatsapp_url if partner.whatsapp_url.startswith('http') else 'https://' + partner.whatsapp_url" target="_blank" title="WhatsApp" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#25D366') + '; border: 2px solid ' + (partner.secondary_color or '#25D366')">
                    <i class="fab fa-whatsapp" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- LinkedIn -->
                <a t-if="partner.linkedin_url" t-att-href="partner.linkedin_url if partner.linkedin_url.startswith('http') else 'https://' + partner.linkedin_url" target="_blank" title="LinkedIn" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#0077B5') + '; border: 2px solid ' + (partner.secondary_color or '#0077B5')">
                    <i class="fab fa-linkedin" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>
                <!-- LinkedIn Company -->
                <a t-if="partner.linkedin_url_company" t-att-href="partner.linkedin_url_company if partner.linkedin_url_company.startswith('http') else 'https://' + partner.linkedin_url_company" target="_blank" title="Company LinkedIn" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#0077B5') + '; border: 2px solid ' + (partner.secondary_color or '#0077B5')">
                    <i class="fab fa-linkedin" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- YouTube -->
                <a t-if="partner.youtube_url" t-att-href="partner.youtube_url if partner.youtube_url.startswith('http') else 'https://' + partner.youtube_url" target="_blank" title="YouTube" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#FF0000') + '; border: 2px solid ' + (partner.secondary_color or '#FF0000')">
                    <i class="fab fa-youtube" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Facebook -->
                <a t-if="partner.facebook_url" t-att-href="partner.facebook_url if partner.facebook_url.startswith('http') else 'https://' + partner.facebook_url" target="_blank" title="Facebook" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#1877F2') + '; border: 2px solid ' + (partner.secondary_color or '#1877F2')">
                    <i class="fab fa-facebook" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>
                <!-- Facebook Company -->
                <a t-if="partner.facebook_url_company" t-att-href="partner.facebook_url_company if partner.facebook_url_company.startswith('http') else 'https://' + partner.facebook_url_company" target="_blank" title="Company Facebook" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#1877F2') + '; border: 2px solid ' + (partner.secondary_color or '#1877F2')">
                    <i class="fab fa-facebook" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Telegram -->
                <a t-if="partner.telegram_url" t-att-href="partner.telegram_url if partner.telegram_url.startswith('http') else 'https://' + partner.telegram_url" target="_blank" title="Telegram" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#0088CC') + '; border: 2px solid ' + (partner.secondary_color or '#0088CC')">
                    <i class="fab fa-telegram" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Instagram -->
                <a t-if="partner.instagram_url" t-att-href="partner.instagram_url if partner.instagram_url.startswith('http') else 'https://' + partner.instagram_url" target="_blank" title="Instagram" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#E4405F') + '; border: 2px solid ' + (partner.secondary_color or '#E4405F')">
                    <i class="fab fa-instagram" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>
                <!-- Instagram Company -->
                <a t-if="partner.instagram_url_company" t-att-href="partner.instagram_url_company if partner.instagram_url_company.startswith('http') else 'https://' + partner.instagram_url_company" target="_blank" title="Company Instagram" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#E4405F') + '; border: 2px solid ' + (partner.secondary_color or '#E4405F')">
                    <i class="fab fa-instagram" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Twitter -->
                <a t-if="partner.twitter_url" t-att-href="partner.twitter_url if partner.twitter_url.startswith('http') else 'https://' + partner.twitter_url" target="_blank" title="Twitter" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#1DA1F2') + '; border: 2px solid ' + (partner.secondary_color or '#1DA1F2')">
                    <i class="fab fa-twitter" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>
                <!-- Twitter Company -->
                <a t-if="partner.twitter_url_company" t-att-href="partner.twitter_url_company if partner.twitter_url_company.startswith('http') else 'https://' + partner.twitter_url_company" target="_blank" title="Company Twitter" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#1DA1F2') + '; border: 2px solid ' + (partner.secondary_color or '#1DA1F2')">
                    <i class="fab fa-twitter" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- GitHub -->
                <a t-if="partner.github_url" t-att-href="partner.github_url if partner.github_url.startswith('http') else 'https://' + partner.github_url" target="_blank" title="GitHub" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#333') + '; border: 2px solid ' + (partner.secondary_color or '#333')">
                    <i class="fab fa-github" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Tumblr -->
                <a t-if="partner.tumblr_url" t-att-href="partner.tumblr_url if partner.tumblr_url.startswith('http') else 'https://' + partner.tumblr_url" target="_blank" title="Tumblr" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#35465C') + '; border: 2px solid ' + (partner.secondary_color or '#35465C')">
                    <i class="fab fa-tumblr" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Additional Social Media Platforms -->
                <!-- Xing -->
                <a t-if="partner.xing_url" t-att-href="partner.xing_url if partner.xing_url.startswith('http') else 'https://' + partner.xing_url" target="_blank" title="Xing" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#006567') + '; border: 2px solid ' + (partner.secondary_color or '#006567')">
                    <i class="fab fa-xing" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Vimeo -->
                <a t-if="partner.vimeo_url" t-att-href="partner.vimeo_url if partner.vimeo_url.startswith('http') else 'https://' + partner.vimeo_url" target="_blank" title="Vimeo" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#1AB7EA') + '; border: 2px solid ' + (partner.secondary_color or '#1AB7EA')">
                    <i class="fab fa-vimeo" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Pinterest -->
                <a t-if="partner.pinterest_url" t-att-href="partner.pinterest_url if partner.pinterest_url.startswith('http') else 'https://' + partner.pinterest_url" target="_blank" title="Pinterest" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#E60023') + '; border: 2px solid ' + (partner.secondary_color or '#E60023')">
                    <i class="fab fa-pinterest" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Skype -->
                <a t-if="partner.skype_url" t-att-href="partner.skype_url if partner.skype_url.startswith('http') else 'https://' + partner.skype_url" target="_blank" title="Skype" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#00AFF0') + '; border: 2px solid ' + (partner.secondary_color or '#00AFF0')">
                    <i class="fab fa-skype" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Dribbble -->
                <a t-if="partner.dribbble_url" t-att-href="partner.dribbble_url if partner.dribbble_url.startswith('http') else 'https://' + partner.dribbble_url" target="_blank" title="Dribbble" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#EA4C89') + '; border: 2px solid ' + (partner.secondary_color or '#EA4C89')">
                    <i class="fab fa-dribbble" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Reddit -->
                <a t-if="partner.reddit_url" t-att-href="partner.reddit_url if partner.reddit_url.startswith('http') else 'https://' + partner.reddit_url" target="_blank" title="Reddit" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#FF4500') + '; border: 2px solid ' + (partner.secondary_color or '#FF4500')">
                    <i class="fab fa-reddit" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Snapchat -->
                <a t-if="partner.snapchat_url" t-att-href="partner.snapchat_url if partner.snapchat_url.startswith('http') else 'https://' + partner.snapchat_url" target="_blank" title="Snapchat" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#FFFC00') + '; border: 2px solid ' + (partner.secondary_color or '#FFFC00')">
                    <i class="fab fa-snapchat" t-att-style="'color: ' + (partner.primary_color or '#000000') + '; font-size: 20px;'"></i>
                </a>

                <!-- Facebook Messenger -->
                <a t-if="partner.messenger_url" t-att-href="partner.messenger_url if partner.messenger_url.startswith('http') else 'https://' + partner.messenger_url" target="_blank" title="Messenger" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#0084FF') + '; border: 2px solid ' + (partner.secondary_color or '#0084FF')">
                    <i class="fab fa-facebook-messenger" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- TikTok -->
                <a t-if="partner.tiktok_url" t-att-href="partner.tiktok_url if partner.tiktok_url.startswith('http') else 'https://' + partner.tiktok_url" target="_blank" title="TikTok" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#000000') + '; border: 2px solid ' + (partner.secondary_color or '#000000')">
                    <i class="fab fa-tiktok" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Viber -->
                <a t-if="partner.viber_url" t-att-href="partner.viber_url if partner.viber_url.startswith('http') or partner.viber_url.startswith('viber:') else 'https://' + partner.viber_url" target="_blank" title="Viber" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#665CAC') + '; border: 2px solid ' + (partner.secondary_color or '#665CAC')">
                    <i class="fab fa-viber" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Line -->
                <a t-if="partner.line_url" t-att-href="partner.line_url if partner.line_url.startswith('http') else 'https://' + partner.line_url" target="_blank" title="Line" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#00C300') + '; border: 2px solid ' + (partner.secondary_color or '#00C300')">
                    <i class="fab fa-line" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- Signal -->
                <a t-if="partner.signal_url" t-att-href="partner.signal_url if partner.signal_url.startswith('http') else 'https://' + partner.signal_url" target="_blank" title="Signal" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#2592E9') + '; border: 2px solid ' + (partner.secondary_color or '#2592E9')">
                    <i class="fab fa-signal-messenger" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                <!-- VKontakte -->
                <a t-if="partner.vkontakte_url" t-att-href="partner.vkontakte_url if partner.vkontakte_url.startswith('http') else 'https://' + partner.vkontakte_url" target="_blank" title="VKontakte" class="social-icon" t-att-style="'background-color: ' + (partner.secondary_color or '#4C75A3') + '; border: 2px solid ' + (partner.secondary_color or '#4C75A3')">
                    <i class="fab fa-vk" t-att-style="'color: ' + (partner.primary_color or '#ffffff') + '; font-size: 20px;'"></i>
                </a>

                         </div>
                        </div>
                    </section>
                </t> 

            <!-- Specialities Section -->
            <t t-if="partner.speciality_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#fff') + '; text-align: center; padding: 20px 0;'">
                    <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 30px;'">
                        Specialities
                    </h4>
                    
                    <div class="s_allow_columns o_container_small">
                        <div class="specialities-container" style="display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; max-width: 100%;">
                            <t t-foreach="partner.speciality_ids" t-as="speciality">
                                <span class="speciality-pill" 
                                      t-att-style="'background-color: ' + (partner.secondary_color or '#007bff') + '; color: ' + (partner.primary_color or '#fff') + '; padding: 8px 16px; border-radius: 20px; font-size: 14px; font-weight: 500; display: inline-block; margin: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'">
                                    <t t-esc="speciality.name"/>
                                </span>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Services Section -->
            <t t-if="partner.service_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#fff') + '; text-align: center; padding: 20px 0;'">
                    <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 30px;'">
                        Services
                    </h4>
                    
                    <div class="s_allow_columns o_container_small" style="max-width: 100%; overflow: hidden;">
                        <div class="services-container" style="display: flex; flex-direction: column; gap: 20px; max-width: 800px; margin: 0 auto; width: 100%; padding: 0 15px; box-sizing: border-box;">
                            <t t-foreach="partner.service_ids" t-as="service">
                                <div class="service-card" 
                                     t-att-style="'background: ' + (partner.primary_color or '#fff') + '; border: 2px solid ' + (partner.secondary_color or '#007bff') + '; border-radius: 12px; padding: 24px; text-align: left; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; box-sizing: border-box; overflow: hidden;'">
                                    <h5 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0 0 12px 0; font-size: 20px; font-weight: 600; word-wrap: break-word;'">
                                        <t t-esc="service.name"/>
                                    </h5>
                                    <div t-att-style="'color: #666; margin: 0 0 12px 0; line-height: 1.6; word-wrap: break-word; overflow-wrap: break-word;'">
                                        <t t-esc="service.description"/>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px; flex-wrap: wrap; gap: 12px;">
                                        <div t-if="service.show_pricing and service.price" style="flex: 0 0 auto;">
                                            <span t-att-style="'color: ' + (partner.secondary_color or '#000') + '; font-weight: 600; font-size: 16px;'">
                                                <t t-esc="service.price"/>
                                            </span>
                                        </div>
                                        <div t-if="not service.show_pricing or not service.price" style="flex: 1;"></div>
                                        <a href="#" 
                                           class="btn service-request-btn" 
                                           t-att-data-service-id="service.id"
                                           t-att-data-service-name="service.name"
                                           t-att-data-service-description="service.description"
                                           t-att-style="'background-color: ' + (partner.secondary_color or '#007bff') + '; color: ' + (partner.primary_color or '#fff') + '; border: none; padding: 10px 24px; border-radius: 8px; font-weight: 600; text-decoration: none; display: inline-block; white-space: nowrap; flex: 0 0 auto;'"
                                           data-toggle="modal" 
                                           data-target="#serviceRequestModal">
                                            Request Service
                                        </a>
                                    </div>
                                </div>
                            </t>
                         </div>
                        </div>
                    </section>
                </t> 

                </t> 

<t t-if="partner.show_reviews">
    <section class="s_text_block o_colored_level pt0 pb0"
             t-att-style="'background-color: ' + (partner.primary_color or '#fff') + '; text-align: center; padding: 20px 0;'">
        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 30px;'">
            <t t-if="partner.reviews_section_title" t-esc="partner.reviews_section_title"/><t t-else="">Reviews</t>
        </h4>
        
        <!-- Reviews section with proper centering -->
        <div class="s_allow_columns o_container_small" t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + ';'">
            <div class="reviews-container" t-att-style="'text-align: center; max-width: 100%; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                <t t-if="partner.review_ids">
                    <!-- Bootstrap Carousel with Fade Animation -->
                    <div id="reviewsCarousel" class="carousel slide carousel-fade" data-ride="carousel" data-pause="hover" t-att-data-interval="(partner.carousel_autoscroll_speed or 5) * 1000">
                        <!-- Carousel Indicators - Completely hidden -->
                        <ol class="carousel-indicators" style="display: none !important; visibility: hidden !important; position: absolute; left: -9999px;"></ol>
                        
                        <!-- Carousel Items -->
                        <div class="carousel-inner">
                            <t t-set="reviews_list" t-value="partner.review_ids.filtered(lambda r: r.is_published)[:partner.max_reviews_display or 5]"/>
                            <t t-set="first_review" t-value="reviews_list[0] if reviews_list else None"/>
                            <t t-foreach="reviews_list" t-as="review">
                                <t t-set="is_first" t-value="review == first_review"/>
                                <div t-att-class="'carousel-item' + (' active' if is_first else '')">
                                    <div class="review-item text-center" t-att-style="'margin: 0 auto; max-width: 600px; padding: 30px; border-radius: 15px; background-color: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid rgba(0,0,0,0.1); box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.15);'">
                                        <div class="review-rating" t-att-style="'color: #ffc107; font-size: 28px; margin-bottom: 20px;'">
                                            <t t-esc="review.stars_display"/>
                                        </div>
                                        <div class="review-text" t-att-style="'color: ' + (partner.secondary_color or '#000') + '; font-style: italic; line-height: 1.8; font-size: 18px; margin-bottom: 20px; word-wrap: break-word; overflow-wrap: break-word; hyphens: auto; word-break: break-word;'">
                                            <t t-out="review.review_text"/>
                                        </div>
                                        <div class="reviewer-info">
                                            <h5 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0; font-weight: bold; font-size: 16px;'">
                                                — <t t-if="review.reviewer_name" t-esc="review.reviewer_name"/><t t-else="">Anonymous</t>
                                            </h5>
                                        </div>
                                    </div>
                                </div>
                            </t>
                        </div>
                        
                        <!-- Carousel Controls -->
                        <a class="carousel-control-prev" href="#reviewsCarousel" role="button" data-slide="prev">
                            <span class="carousel-control-prev-icon" aria-hidden="true"></span>
                            <span class="sr-only">Previous</span>
                        </a>
                        <a class="carousel-control-next" href="#reviewsCarousel" role="button" data-slide="next">
                            <span class="carousel-control-next-icon" aria-hidden="true"></span>
                            <span class="sr-only">Next</span>
                        </a>
                    </div>
                </t>
                <t t-else="">
                    <div class="text-center" t-att-style="'color: ' + (partner.secondary_color or '#000') + '; padding: 20px;'">
                        <p>No reviews yet. Be the first to leave a review!</p>
                    </div>
                </t>
            </div>
        </div>
    </section>
    
    <!-- Leave a Review Button - After reviews section -->
    <t t-if="partner.show_reviews">
        <div style="text-align: center; padding: 20px 0; max-width: 600px; margin-left: auto; margin-right: auto; padding: 20px 16px;">
            <a href="#" 
               t-att-style="'width: 100%; background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; gap: 8px;'"
               data-toggle="modal" 
               data-target="#reviewModal"
               onmouseover="this.style.transform='scale(0.95)'"
               onmouseout="this.style.transform='scale(1)'">
                Leave a Review
            </a>
        </div>
    </t>
</t>

    <!-- Existing Calendly widget code -->
        <t t-if="partner.calendly_url">
            <div class="calendly-inline-widget"
                 t-att-data-url="partner.calendly_url"
                 style="min-width: 100%; height: 100vh; overflow: hidden; margin-bottom: 0; padding-bottom: 0;"></div>
            <script type="text/javascript"
                    src="https://assets.calendly.com/assets/external/widget.js"></script>
        </t>
        
            <!-- Footer CTA - QR Code Button (React Design) -->
            <div style="margin-top: 24px; max-width: 600px; margin-left: auto; margin-right: auto; padding: 0 16px;">
                <a href="#" 
                   data-toggle="modal" 
                   data-target="#qrCodeModal"
                   t-att-style="'width: 100%; background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; gap: 8px;'"
                   onmouseover="this.style.transform='scale(0.95)'"
                   onmouseout="this.style.transform='scale(1)'">
                    <i class="fa fa-qrcode" style="font-size: 18px;"></i> QR Code
                        </a>
                    </div>
        
                </div> <!-- Close the responsive container div -->
    </div> <!-- Close the wrap div here -->
    
    <!-- Custom CSS for Social Media Icons and Responsive Layout -->
    <style>
        /* Prevent horizontal overflow on the main container only */
        .container-fluid {{
            overflow-x: hidden !important;
            overflow-y: visible !important;
        }}
        
        /* Ensure profile picture shadow is visible - override all overflow settings */
        #wrap {{
            overflow: visible !important;
        }}
        
        .banner-container {{
            overflow: visible !important;
            margin-bottom: 56px !important;
        }}
        
        .profile-picture-wrapper {{
            overflow: visible !important;
            padding: 12px !important;
            margin: -12px !important;
        }}
        
        .profile-picture-wrapper img {{
            filter: drop-shadow(0 4px 12px rgba(0,0,0,0.3)) !important;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
        }}
        
        /* Ensure banner container has space for shadow */
        .banner-container {{
            padding-bottom: 20px !important;
        }}
        
        /* Add padding to container-fluid to give shadow space on sides */
        .container-fluid {{
            padding-left: 20px !important;
            padding-right: 20px !important;
        }}
        
        /* Override section overflow that might clip shadow */
        .s_parallax_no_overflow_hidden {{
            overflow: visible !important;
        }}
        
        .s_cover {{
            overflow: visible !important;
        }}
        
        /* Ensure container doesn't clip shadow */
        .s_allow_columns {{
            overflow: visible !important;
        }}
        
        /* Responsive container improvements */
        @media (max-width: 768px) {{
            .container-fluid {{
                padding: 0 15px !important;
            }}
            #wrap {{
                padding-top: 30px !important;
            }}
            .image-container {{
                padding-top: 25px !important;
            }}
        }}
        
        @media (max-width: 480px) {{
            .container-fluid {{
                padding: 0 10px !important;
            }}
            #wrap {{
                padding-top: 20px !important;
            }}
            .image-container {{
                padding-top: 15px !important;
            }}
        }}
        
        /* Modal backdrop styling - Less intrusive */
        .modal-backdrop {{
            background-color: rgba(0, 0, 0, 0.3) !important;
            opacity: 1 !important;
            z-index: 2040 !important;
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100% !important;
            height: 100% !important;
        }}
        
        .modal-backdrop.show {{
            opacity: 1 !important;
        }}
        
        /* Ensure modals are well above backdrop - allow backdrop clicks to close */
        .modal {{
            z-index: 2050 !important;
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100% !important;
            height: 100% !important;
            pointer-events: none !important; /* Allow clicks through to backdrop */
        }}
        
        /* Enable backdrop click to close modal */
        .modal-backdrop {{
            cursor: pointer !important;
        }}
        
        .modal.show {{
            display: block !important;
            z-index: 2050 !important;
        }}
        
        /* Modal dialog blocks clicks and is fully interactive */
        .modal-dialog {{
            z-index: 2051 !important;
            position: relative !important;
            pointer-events: auto !important; /* Block clicks inside dialog */
            margin: 1.75rem auto !important;
        }}
        
        .modal-content {{
            z-index: 2052 !important;
            position: relative !important;
            pointer-events: auto !important;
            background-color: var(--primary-color, #ffffff) !important;
            border-radius: 16px !important;
        }}
        
        /* Ensure all form elements are clickable */
        .modal input,
        .modal textarea,
        .modal select,
        .modal button,
        .modal a,
        .modal .form-control,
        .modal label {{
            pointer-events: auto !important;
            cursor: pointer !important;
            position: relative !important;
        }}
        
        .modal input[type="text"],
        .modal input[type="email"],
        .modal input[type="tel"],
        .modal textarea {{
            cursor: text !important;
        }}
        
        /* Fix for any elements that might be blocking clicks */
        body.modal-open {{
            overflow: hidden !important;
        }}
        
        /* Ensure modal body and header are clickable */
        .modal-header,
        .modal-body,
        .modal-footer {{
            pointer-events: auto !important;
            position: relative !important;
        }}
        
        /* Ensure close button is clickable */
        .modal .close {{
            pointer-events: auto !important;
            cursor: pointer !important;
            z-index: 2053 !important;
        }}
        
        /* Reviews section styling - Simple centering */
        .reviews-container {{
            text-align: center;
            max-width: 100%;
            background-color: inherit !important;
        }}
        
        .s_allow_columns.o_container_small {{
            background-color: inherit !important;
        }}
        
        .review-item {{
            transition: transform 0.3s ease, box-shadow 0.3s ease;
            word-wrap: break-word;
            overflow-wrap: break-word;
            background-color: inherit !important;
        }}
        
        .review-item:hover {{
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        
        .review-text {{
            word-wrap: break-word;
            overflow-wrap: break-word;
            hyphens: auto;
            word-break: break-word;
        }}
        
        /* Carousel controls styling - Perfect circular buttons with arrows */
        .carousel-control-prev,
        .carousel-control-next {{
            width: 40px !important;
            height: 40px !important;
            min-width: 40px !important;
            min-height: 40px !important;
            max-width: 40px !important;
            max-height: 40px !important;
            background-color: rgba(0,0,0,0.7);
            border-radius: 50% !important;
            top: 50%;
            transform: translateY(-50%);
            opacity: 0.9;
            display: flex !important;
            align-items: center;
            justify-content: center;
            transition: all 0.3s ease;
            border: 2px solid rgba(255,255,255,0.5);
            z-index: 10;
            box-sizing: border-box !important;
            padding: 0 !important;
            margin: 0 !important;
            text-decoration: none !important;
            outline: none !important;
        }}
        
        .carousel-control-prev {{
            left: 15px;
        }}
        
        .carousel-control-next {{
            right: 15px;
        }}
        
        .carousel-control-prev:hover,
        .carousel-control-next:hover {{
            opacity: 1;
            background-color: rgba(0,0,0,0.9);
            border-color: rgba(255,255,255,0.8);
            transform: translateY(-50%) scale(1.05);
            text-decoration: none !important;
        }}
        
        .carousel-control-prev:focus,
        .carousel-control-next:focus {{
            text-decoration: none !important;
            outline: none !important;
        }}
        
        .carousel-control-prev:active,
        .carousel-control-next:active {{
            text-decoration: none !important;
        }}
        
        .carousel-control-prev-icon,
        .carousel-control-next-icon {{
            width: 20px;
            height: 20px;
            background: none !important;
            background-image: none !important;
            display: flex !important;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            color: white !important;
            font-weight: bold;
        }}
        
        /* Use Unicode arrows instead of background images */
        .carousel-control-prev-icon:before {{
            content: "◀" !important;
            display: block !important;
        }}
        
        .carousel-control-next-icon:before {{
            content: "▶" !important;
            display: block !important;
        }}
        
        /* Force circular shape - override any conflicting styles */
        .carousel-control-prev,
        .carousel-control-next {{
            aspect-ratio: 1 / 1 !important;
            flex-shrink: 0 !important;
            flex-grow: 0 !important;
        }}
        
        /* Override Bootstrap default carousel control styles */
        .carousel-control-prev,
        .carousel-control-next {{
            background-image: none !important;
            background-position: initial !important;
            background-repeat: initial !important;
            background-size: initial !important;
        }}
        
        /* Ensure proper centering of arrow icons */
        .carousel-control-prev,
        .carousel-control-next {{
            text-align: center;
        }}
        
        /* Force visibility of arrow content */
        .carousel-control-prev-icon,
        .carousel-control-next-icon {{
            visibility: visible !important;
            opacity: 1 !important;
        }}
        
        /* Alternative approach - direct text content */
        .carousel-control-prev:after {{
            content: "◀";
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: white;
            font-size: 18px;
            font-weight: bold;
            z-index: 1;
            text-decoration: none !important;
        }}
        
        .carousel-control-next:after {{
            content: "▶";
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: white;
            font-size: 18px;
            font-weight: bold;
            z-index: 1;
            text-decoration: none !important;
        }}
        
        /* Remove all link styling from carousel controls */
        .carousel-control-prev,
        .carousel-control-next,
        .carousel-control-prev:hover,
        .carousel-control-next:hover,
        .carousel-control-prev:focus,
        .carousel-control-next:focus,
        .carousel-control-prev:active,
        .carousel-control-next:active,
        .carousel-control-prev:visited,
        .carousel-control-next:visited {{
            text-decoration: none !important;
            border-bottom: none !important;
            text-decoration-line: none !important;
            text-decoration-style: none !important;
            text-decoration-color: transparent !important;
        }}
        
        /* Hide scrollbars in review text only */
        .review-text,
        .review-text * {{
            overflow-y: hidden !important;
            max-height: none !important;
        }}
        
        .review-text::-webkit-scrollbar,
        .review-text *::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
        }}
        
        .review-text,
        .review-text * {{
            -ms-overflow-style: none !important;
            scrollbar-width: none !important;
        }}
        
        /* Target any potential scrollbar sources */
        .reviews-container,
        .reviews-container .carousel,
        .reviews-container .carousel-inner,
        .reviews-container .carousel-item,
        .reviews-container .review-item {{
            overflow: hidden !important;
        }}
        
        /* Ensure buttons are visible on desktop */
        @media (min-width: 769px) {{
            .carousel-control-prev,
            .carousel-control-next {{
                display: flex !important;
                opacity: 0.9 !important;
                visibility: visible !important;
            }}
        }}
        
        /* Ensure carousel doesn't extend beyond viewport */
        .carousel {{
            max-width: 100% !important;
            overflow: hidden !important;
        }}
        
        .carousel-inner {{
            max-width: 100% !important;
            overflow: hidden !important;
            display: flex !important;
            align-items: center !important;
        }}
        
        .carousel-item {{
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
        }}
        
        /* Prevent horizontal overflow without breaking layout */
        .reviews-container {{
            max-width: 100% !important;
            overflow-x: hidden !important;
        }}
        
        .carousel {{
            max-width: 100% !important;
            overflow-x: hidden !important;
        }}
        
        /* Force hide scrollbars on the entire reviews section */
        .reviews-container::-webkit-scrollbar,
        .reviews-container .carousel::-webkit-scrollbar,
        .reviews-container .carousel-inner::-webkit-scrollbar,
        .reviews-container .carousel-item::-webkit-scrollbar,
        .reviews-container .review-item::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
        }}
        
        .review-rating {{
            text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
        }}
        
        @media (max-width: 768px) {{
            .review-item {{
                padding: 15px !important;
                margin-bottom: 20px !important;
            }}
        }}
        
        .social-icon {{
            width: 50px;
            height: 50px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            margin: 5px;
            transition: all 0.3s ease;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        
        .social-icon:hover {{
            transform: translateY(-3px);
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }}
        
        /* Contact Information Section - Perfect Centering */
        .s_allow_columns.o_container_small .row.justify-content-center {{
            display: flex !important;
            justify-content: center !important;
            align-items: stretch !important;
            gap: 20px;
        }}
        
        .s_allow_columns.o_container_small .row.justify-content-center .col-lg-5 {{
            flex: 0 0 auto !important;
            max-width: calc(50% - 10px) !important;
            min-height: 200px;
        }}
        
        @media (max-width: 768px) {{
            .s_allow_columns.o_container_small .row.justify-content-center {{
                flex-direction: column !important;
                align-items: center !important;
            }}
            
            .s_allow_columns.o_container_small .row.justify-content-center .col-lg-5 {{
                max-width: 100% !important;
                width: 100% !important;
                margin-bottom: 20px;
            }}
        }}
        
        /* Responsive Design */
        @media (max-width: 768px) {{
            .social-icon {{
                width: 45px;
                height: 45px;
                margin: 3px;
            }}
            
            /* Hide carousel controls and indicators on mobile */
            .carousel-control-prev,
            .carousel-control-next {{
                display: none !important;
            }}
            
            .carousel-indicators {{
                display: none !important;
            }}
            
            /* Ensure no horizontal overflow from carousel elements */
            .carousel-indicators {{
                position: absolute !important;
                left: -9999px !important;
                visibility: hidden !important;
            }}
            
            /* Enable touch scrolling for carousel on mobile */
            .carousel-inner {{
                touch-action: pan-x;
                -webkit-overflow-scrolling: touch;
                -webkit-transform: translateZ(0);
                transform: translateZ(0);
            }}
            
            /* Make carousel items touchable on mobile */
            .carousel-item {{
                touch-action: manipulation;
                -webkit-tap-highlight-color: transparent;
            }}
            
            /* Optimize carousel controls for mobile */
            .carousel-control-prev,
            .carousel-control-next {{
                -webkit-tap-highlight-color: transparent;
                -webkit-touch-callout: none;
                -webkit-user-select: none;
                -khtml-user-select: none;
                -moz-user-select: none;
                -ms-user-select: none;
                user-select: none;
            }}
        }}
        
        /* Carousel fade animation - optimized for speed */
        .carousel-fade .carousel-item {{
            opacity: 0;
            transition: opacity 0.3s ease-in-out;
            transform: translateZ(0); /* Hardware acceleration */
        }}
        
        .carousel-fade .carousel-item.active {{
            opacity: 1;
        }}
        
        .carousel-fade .carousel-item-next,
        .carousel-fade .carousel-item-prev {{
            opacity: 0;
        }}
        
        .carousel-fade .carousel-item-next.active,
        .carousel-fade .carousel-item-prev.active {{
            opacity: 1;
        }}
        
        /* Optimize carousel performance */
        .carousel-inner {{
            will-change: transform, opacity;
        }}
        
        .carousel-item {{
            will-change: opacity;
        }}
    </style>
    
    <!-- Fix Modal Clickability -->
    <script>
        document.addEventListener('DOMContentLoaded', function() {{
            // Fix modal z-index and clickability BEFORE it's shown
            $(document).on('show.bs.modal', '.modal', function() {{
                var $modal = $(this);
                // Move modal to body if not already there (Bootstrap 4 should do this, but ensure it)
                if ($modal.parent().is('body') === false) {{
                    $modal.appendTo('body');
                }}
            }});
            
            // Fix modal z-index and clickability when shown
            $(document).on('shown.bs.modal', '.modal', function() {{
                var $modal = $(this);
                var $backdrop = $('.modal-backdrop');
                
                // Ensure backdrop is below modal and covers full screen
                $backdrop.css({{
                    'z-index': '2040',
                    'position': 'fixed',
                    'top': '0',
                    'left': '0',
                    'width': '100%',
                    'height': '100%',
                    'pointer-events': 'auto'
                }});
                
                // Ensure modal is above everything and covers full screen
                // Modal itself allows clicks through (pointer-events: none from CSS)
                $modal.css({{
                    'z-index': '2050',
                    'position': 'fixed',
                    'top': '0',
                    'left': '0',
                    'width': '100%',
                    'height': '100%',
                    'pointer-events': 'none' // Allow clicks through modal to backdrop
                }});
                
                // Modal dialog captures clicks inside it
                $modal.find('.modal-dialog').css({{
                    'z-index': '2051',
                    'position': 'relative',
                    'pointer-events': 'auto', // Block clicks inside dialog
                    'margin': '1.75rem auto'
                }});
                
                // Modal content is fully interactive
                $modal.find('.modal-content').css({{
                    'z-index': '2052',
                    'position': 'relative',
                    'pointer-events': 'auto',
                    'background-color': 'white',
                    'border-radius': '16px'
                }});
                
                // Ensure all elements inside modal are clickable
                $modal.find('.modal-content *').css('pointer-events', 'auto');
            }});
            
            // Prevent clicks inside modal content from closing the modal
            $(document).on('click', '.modal-content, .modal-header, .modal-body, .modal-footer', function(e) {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }});
            
            // Prevent all form elements from propagating clicks (except submit buttons)
            $(document).on('click', '.modal input, .modal textarea, .modal select, .modal button:not([data-dismiss]):not(#submitReviewBtn):not(#submitLeadBtn):not(#submitServiceRequestBtn), .modal a:not([data-dismiss]), .modal .form-control, .modal label', function(e) {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }});
            
            // Enable backdrop clicks to close modal
            $(document).on('click', '.modal-backdrop', function(e) {{
                e.stopPropagation();
                // Close all open modals when clicking on backdrop
                $('.modal.show').each(function() {{
                    $(this).modal('hide');
                }});
            }});
            
            // Also handle clicks on the modal container itself (outside dialog)
            $(document).on('click', '.modal', function(e) {{
                var $modal = $(this);
                // If clicking directly on modal (not on dialog/content), close it
                if ($(e.target).is('.modal') && !$(e.target).hasClass('modal-dialog') && !$(e.target).hasClass('modal-content')) {{
                    $modal.modal('hide');
                }}
            }});
            
            // Prevent modal from closing when clicking inside modal content area
            $(document).on('click', '.modal-content, .modal-header, .modal-body, .modal-footer', function(e) {{
                e.stopPropagation();
                e.stopImmediatePropagation();
            }});
            
            const carousel = document.getElementById('reviewsCarousel');
            if (!carousel) return;
            
            let startX = 0;
            let startY = 0;
            let isDragging = false;
            let touchStartTime = 0;
            
            // Get autoscroll speed from data attribute
            const autoscrollSpeed = carousel.getAttribute('data-interval');
            const intervalValue = autoscrollSpeed ? parseInt(autoscrollSpeed) : 5000;
            
            // Initialize carousel with proper auto-advance
            $(carousel).carousel({{
                interval: intervalValue > 0 ? intervalValue : false,
                wrap: true,
                touch: true,
                pause: 'hover'
            }});
            
            // Touch event handlers with improved performance
            carousel.addEventListener('touchstart', function(e) {{
                startX = e.touches[0].clientX;
                startY = e.touches[0].clientY;
                isDragging = true;
                touchStartTime = Date.now();
                
                // Pause auto-advance during touch
                $(carousel).carousel('pause');
            }}, {{ passive: true }});
            
            carousel.addEventListener('touchmove', function(e) {{
                if (!isDragging) return;
                
                const currentX = e.touches[0].clientX;
                const currentY = e.touches[0].clientY;
                const diffX = Math.abs(startX - currentX);
                const diffY = Math.abs(startY - currentY);
                
                // Only prevent default for horizontal swipes
                if (diffX > diffY && diffX > 10) {{
                    e.preventDefault();
                }}
            }}, {{ passive: false }});
            
            carousel.addEventListener('touchend', function(e) {{
                if (!isDragging) return;
                
                const endX = e.changedTouches[0].clientX;
                const diffX = startX - endX;
                const touchDuration = Date.now() - touchStartTime;
                
                // Only trigger swipe if it's a quick, horizontal gesture
                if (Math.abs(diffX) > 30 && touchDuration < 500) {{
                    if (diffX > 0) {{
                        // Swipe left - next
                        $(carousel).carousel('next');
                    }} else {{
                        // Swipe right - previous
                        $(carousel).carousel('prev');
                    }}
                }}
                
                isDragging = false;
                
                // Resume auto-advance after a short delay
                setTimeout(function() {{
                    $(carousel).carousel('cycle');
                }}, 2000);
            }}, {{ passive: true }});
            
            // Optimize button clicks and ensure visibility
            const prevBtn = carousel.querySelector('.carousel-control-prev');
            const nextBtn = carousel.querySelector('.carousel-control-next');
            
            // Force show buttons on desktop with proper styling
            if (window.innerWidth > 768) {{
                if (prevBtn) {{
                    prevBtn.style.display = 'flex';
                    prevBtn.style.opacity = '0.9';
                    prevBtn.style.visibility = 'visible';
                    prevBtn.style.alignItems = 'center';
                    prevBtn.style.justifyContent = 'center';
                    prevBtn.style.width = '40px';
                    prevBtn.style.height = '40px';
                }}
                if (nextBtn) {{
                    nextBtn.style.display = 'flex';
                    nextBtn.style.opacity = '0.9';
                    nextBtn.style.visibility = 'visible';
                    nextBtn.style.alignItems = 'center';
                    nextBtn.style.justifyContent = 'center';
                    nextBtn.style.width = '40px';
                    nextBtn.style.height = '40px';
                }}
            }}
            
            if (prevBtn) {{
                prevBtn.addEventListener('click', function(e) {{
                    e.preventDefault();
                    $(carousel).carousel('prev');
                }});
            }}
            
            if (nextBtn) {{
                nextBtn.addEventListener('click', function(e) {{
                    e.preventDefault();
                    $(carousel).carousel('next');
                }});
            }}
            
            // Force remove any scrollbars from review text
            function removeScrollbars() {{
                // Target all elements in the reviews container
                const allElements = document.querySelectorAll('.reviews-container *');
                allElements.forEach(function(element) {{
                    element.style.overflowY = 'hidden';
                    element.style.overflowX = 'hidden';
                    element.style.maxHeight = 'none';
                    element.style.height = 'auto';
                }});
                
                // Also target review text specifically
                const reviewTexts = document.querySelectorAll('.review-text');
                reviewTexts.forEach(function(element) {{
                    element.style.overflowY = 'hidden';
                    element.style.overflowX = 'hidden';
                    element.style.maxHeight = 'none';
                    element.style.height = 'auto';
                    
                    // Force remove any scrollbar styling
                    element.style.setProperty('overflow-y', 'hidden', 'important');
                    element.style.setProperty('overflow-x', 'hidden', 'important');
                }});
            }}
            
            // Remove scrollbars immediately and on carousel slide events
            removeScrollbars();
            $(carousel).on('slide.bs.carousel', removeScrollbars);
            $(carousel).on('slid.bs.carousel', removeScrollbars);
            
            // Also run periodically to catch any dynamically added content
            setInterval(removeScrollbars, 500);
            
            // Run on window resize as well
            window.addEventListener('resize', removeScrollbars);
            
            // Auto-show lead form feature
            var wrapDiv = document.getElementById('wrap');
            if (wrapDiv) {{
                var autoShowLead = wrapDiv.getAttribute('data-auto-show-lead');
                if (autoShowLead === 'true') {{
                    setTimeout(function() {{
                        $('#leadModal').modal('show');
                    }}, 500);
                }}
                
                // Auto-download vCard feature
                var autoDownloadVcard = wrapDiv.getAttribute('data-auto-download-vcard');
                if (autoDownloadVcard === 'true') {{
                    setTimeout(function() {{
                        var downloadUrl = wrapDiv.getAttribute('data-vcard-download-url');
                        if (downloadUrl) {{
                            window.location.href = downloadUrl;
                        }}
                    }}, 800);
                }}
            }}
        }});
    </script>

    
</t>
</t>
"""

    def _build_modern_template(self, image_url, banner_url=None, referral_url=None):
        if referral_url is None:
            referral_url = self.get_referral_signup_url()
        """Build the modern vCard template - React Modern design.
        
        Structure:
        - Header with banner image, name, job position
        - Inline action buttons (Call, Email, Drop Info, Download Info, QR Code)
        - About section with social media icons below
        - Services, Video, Websites, Reviews sections
        """
        return f"""
        <t t-name="website.{self.website_slug}">
            <t t-set="partner" t-value="request.env['partner.vcard'].sudo().browse({self.id})"/>
    
            <!-- Dashboard Button (visible to logged-in internal users) -->
            <t t-if="request.env.user and not request.env.user._is_public() and not request.env.user.share">
                <style>
                    @media only screen and (max-width: 600px) {{
                        .dashboard-btn-container {{
                            top: 10px !important;
                            right: 10px !important;
                        }}
                        .dashboard-btn-container a {{
                            padding: 10px 16px !important;
                            font-size: 12px !important;
                        }}
                        .dashboard-btn-container .fa {{
                            font-size: 14px !important;
                        }}
                    }}
                </style>
                <div class="dashboard-btn-container" style="position: fixed; top: 20px; right: 20px; z-index: 1000;">
                    <a href="/web#action=qr_code_odoo.action_user_dashboard" 
                       style="display: inline-flex; align-items: center; gap: 8px; padding: 12px 20px; background: rgba(69, 126, 184, 0.9); color: white; text-decoration: none; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 14px; font-weight: 500; transition: all 0.3s ease;"
                       onmouseover="this.style.background='rgba(69, 126, 184, 1)'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';"
                       onmouseout="this.style.background='rgba(69, 126, 184, 0.9)'; this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.2)';">
                        <i class="fa fa-dashboard" style="font-size: 16px;"></i>
                        <span>Back to Dashboard</span>
                    </a>
                </div>
            </t>
    
            <!-- Use custom vCard layout without header and footer -->
            <t t-call="qr_code_odoo.vcard_layout">
                <!-- Main content -->
                <div id="wrap" class="oe_structure oe_empty"
                     t-att-style="partner.primary_color and 'background-color: ' + partner.primary_color or ''"
                     t-att-data-auto-show-lead="str(partner.auto_show_lead_form and partner.show_form and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-auto-download-vcard="str(partner.auto_download_vcard and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-vcard-download-url="'/website/vcard/download/' + str(partner.id)"
                     style="text-align: center; font-family: 'Poppins', sans-serif; padding-top: 0;">

                
                <!-- Responsive container -->
                <div class="container-fluid" style="max-width: 800px; margin: 0 auto; padding: 0; overflow: visible;">

            <!-- Modern Template Header with Banner Image -->
            <div class="banner-container" style="position: relative; width: 100%; height: 288px; margin-bottom: 0; z-index: 1; overflow: hidden; border-radius: 0 0 2.5rem 2.5rem;">
                <t t-if="partner.banner_attachment_id">
                    <div class="banner-image-wrapper" style="width: 100%; height: 100%; overflow: hidden; background-color: #ffffff; position: relative; padding: 18px 28px; box-sizing: border-box;">
                        <img t-att-src="'/website/image/ir.attachment/' + str(partner.banner_attachment_id.id) + '/datas'"
                             alt="" 
                             style="width: 100%; height: 100%; object-fit: contain; display: block;"
                             onerror="this.style.display='none';"/>
                    </div>
                </t>
                <t t-if="not partner.banner_attachment_id">
                    <div class="banner-image-wrapper" 
                         t-att-style="'width: 100%; height: 100%; background-color: ' + (partner.primary_color or '#667eea') + '; position: relative;'">
                        <div style="position: absolute; inset: 0; background: rgba(0,0,0,0.3); z-index: 1;"></div>
                    </div>
                </t>
            </div>

            <!-- Profile Picture and Info Section -->
            <section class="s_cover o_colored_level s_parallax_no_overflow_hidden o_cc o_cc3"
                     t-att-style="'padding-top: 24px; position: relative; z-index: 2; margin-top: -80px; min-height: auto; overflow: visible; border-radius: 2rem 2rem 0 0; background: ' + (partner.primary_color or '#ffffff') + ';'">
                <div class="s_allow_columns container" style="text-align: center; padding: 0 16px;">

                    <!-- Profile Picture -->
                    <div style="margin-bottom: 16px;">
                        <t t-if="partner.attachment_id">
                            <img t-att-src="'/website/image/ir.attachment/' + str(partner.attachment_id.id) + '/datas'"
                                 alt=""
                                 class="img img-fluid rounded-circle"
                                 t-att-style="'width: 120px; height: 120px; object-fit: cover; border: 4px solid ' + (partner.primary_color or '#ffffff') + '; box-shadow: 0 4px 12px rgba(0,0,0,0.2); background-color: ' + (partner.primary_color or '#ffffff') + '; display: block; margin: 0 auto;'"
                                 loading="lazy"/>
                        </t>
                    </div>

                    <!-- Partner Name -->
                    <h1 style="margin-top: 0; margin-bottom: 8px; font-size: 1.875rem; font-weight: bold; color: #1e293b;">
                        <t t-esc="partner.name"/>
                    </h1>

                    <!-- Job Position -->
                    <div t-if="partner.function" style="margin-bottom: 24px;">
                        <p style="font-size: 1rem; color: #64748b; font-weight: 500; margin: 0;">
                            <t t-esc="partner.function"/>
                        </p>
                    </div>

                    <!-- Inline Action Buttons (Call, Email, Drop Info, Download Info, QR Code) -->
                    <div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 12px; margin-bottom: 32px; max-width: 600px; margin-left: auto; margin-right: auto;">
                        <!-- Call Button -->
                        <a t-if="partner.phone"
                           t-att-href="'tel:' + partner.phone"
                           t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 10px 20px; border-radius: 12px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 2px solid ' + (partner.secondary_color or '#2563eb') + ';'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'">
                            <i class="fa fa-phone" style="font-size: 16px;"></i>
                            <span>Call</span>
                        </a>
                        
                        <!-- Email Button -->
                        <a t-if="partner.email"
                           t-att-href="'mailto:' + partner.email"
                           t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 10px 20px; border-radius: 12px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; cursor: pointer;'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'"
                           onclick="window.open(this.getAttribute('href'), '_self'); return false;">
                            <i class="fa fa-envelope" style="font-size: 16px;"></i>
                            <span>Email</span>
                        </a>
                        
                        <!-- Drop Info Button -->
                        <t t-if="partner.show_form">
                            <a href="#" 
                               data-toggle="modal" 
                               data-target="#leadModal"
                               t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 10px 20px; border-radius: 12px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 6px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fa fa-paper-plane" style="font-size: 16px;"></i>
                                <span><t t-if="partner.lead_button_label" t-esc="partner.lead_button_label"/><t t-else="">Drop Info</t></span>
                            </a>
                        </t>
                        
                        <!-- Download Info Button -->
                        <a t-att-href="'/website/vcard/download/' + str(partner.id)"
                           t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 10px 20px; border-radius: 12px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 6px;'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'">
                            <i class="fa fa-download" style="font-size: 16px;"></i>
                            <span><t t-set="vinc_label">Get %(name)s's Info</t><t t-out="vinc_label % {{'name': partner.name.split(' ')[0] if partner.name else ''}}"/></span>
                        </a>
                        
                        <!-- QR Code Button (instead of Share) -->
                        <a href="#" 
                           data-toggle="modal" 
                           data-target="#qrCodeModal"
                           t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 10px 20px; border-radius: 12px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 2px solid ' + (partner.secondary_color or '#2563eb') + ';'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'">
                            <i class="fa fa-qrcode" style="font-size: 16px;"></i>
                            <span>QR Code</span>
                        </a>
                    </div>

                </div>
            </section>

            <!-- About Section -->
            <section class="s_text_block o_colored_level pt0 pb0"
                     t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 0;'">
                <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                    <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 16px; text-align: left;'">About</h4>
                    <div t-if="partner.about" style="text-align: left; margin-bottom: 0;">
                        <p t-att-style="'color: #64748b; line-height: 1.6; margin: 0;'">
                            <t t-out="partner.about"/>
                        </p>
                    </div>
                    <div t-if="not partner.about and partner.function" style="text-align: left; margin-bottom: 0;">
                        <p t-att-style="'color: #64748b; line-height: 1.6; margin: 0;'">
                            <t t-esc="partner.function"/>
                        </p>
                    </div>
                </div>
            </section>
            
            <!-- Contact Information Section -->
            <t t-if="partner.phone or partner.mobile or partner.email or partner.street or partner.city or partner.zip or partner.company_name">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 0; margin-top: 16px;'">
                    <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                        <div style="display: flex; flex-direction: column; gap: 16px;">
                            
                            <!-- Combined Phone/Email/Company Section (2 columns: Phone/Mobile left, Email/Company right) -->
                            <t t-if="partner.phone or partner.mobile or partner.email or partner.company_name">
                                <div t-att-style="'background: ' + (partner.secondary_color or '#f3f4f6') + '20; padding: 16px; border-radius: 12px; border: 1px solid ' + (partner.secondary_color or '#e5e7eb') + '60;'">
                                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
                                        <!-- Left Column: Phone and Mobile -->
                                        <div style="display: flex; flex-direction: column; gap: 12px;">
                                            <!-- Primary Phone -->
                                            <t t-if="partner.phone">
                                                <div>
                                                    <div style="display: flex; align-items: center; margin-bottom: 6px;">
                                                        <i class="fa fa-phone" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 16px; margin-right: 8px;'"></i>
                                                        <p style="font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; margin: 0;">Primary Phone</p>
                                                    </div>
                                                    <p style="margin: 0; padding-left: 24px;">
                                                        <a t-att-href="'tel:' + partner.phone" t-att-style="'color: ' + (partner.secondary_color or '#1e40af') + '; text-decoration: none; font-weight: 500;'"><t t-esc="partner.phone"/></a>
                                                    </p>
                                                </div>
                                            </t>
                                            <!-- Mobile -->
                                            <t t-if="partner.mobile">
                                                <div>
                                                    <div style="display: flex; align-items: center; margin-bottom: 6px;">
                                                        <i class="fa fa-mobile" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 16px; margin-right: 8px;'"></i>
                                                        <p style="font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; margin: 0;">Mobile</p>
                                                    </div>
                                                    <p style="margin: 0; padding-left: 24px;">
                                                        <a t-att-href="'tel:' + partner.mobile" t-att-style="'color: ' + (partner.secondary_color or '#1e40af') + '; text-decoration: none; font-weight: 500;'"><t t-esc="partner.mobile"/></a>
                                                    </p>
                                                </div>
                                            </t>
                                        </div>
                                        
                                        <!-- Right Column: Email and Company -->
                                        <div style="display: flex; flex-direction: column; gap: 12px;">
                                            <!-- Email -->
                                            <t t-if="partner.email">
                                                <div>
                                                    <div style="display: flex; align-items: center; margin-bottom: 6px;">
                                                        <i class="fa fa-envelope" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 16px; margin-right: 8px;'"></i>
                                                        <p style="font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; margin: 0;">Email</p>
                                                    </div>
                                                    <p style="margin: 0; padding-left: 24px;">
                                                        <a t-att-href="'mailto:' + partner.email" t-att-style="'color: ' + (partner.secondary_color or '#1e40af') + '; text-decoration: none; font-weight: 500; word-break: break-word;'"><t t-esc="partner.email"/></a>
                                                    </p>
                                                </div>
                                            </t>
                                            <!-- Company Name -->
                                            <t t-if="partner.company_name">
                                                <div>
                                                    <div style="display: flex; align-items: center; margin-bottom: 6px;">
                                                        <i class="fa fa-building" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 16px; margin-right: 8px;'"></i>
                                                        <p style="font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; margin: 0;">Company</p>
                                                    </div>
                                                    <p t-att-style="'color: ' + (partner.secondary_color or '#1e40af') + '; font-weight: 500; margin: 0; padding-left: 24px;'"><t t-esc="partner.company_name"/></p>
                                                </div>
                                            </t>
                                        </div>
                                    </div>
                                </div>
                            </t>
                            
                            <!-- Address Row (Full Width) -->
                            <t t-if="partner.street or partner.city or partner.state_id or partner.zip or partner.country_id">
                                <div t-att-style="'background: ' + (partner.secondary_color or '#f3f4f6') + '20; padding: 16px; border-radius: 12px; border: 1px solid ' + (partner.secondary_color or '#e5e7eb') + '60;'">
                                    <div style="display: flex; align-items: flex-start; margin-bottom: 6px;">
                                        <i class="fa fa-map-marker" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 16px; margin-right: 8px; margin-top: 2px;'"></i>
                                        <p style="font-size: 0.75rem; color: #64748b; font-weight: 600; text-transform: uppercase; margin: 0;">Address</p>
                                    </div>
                                    <p style="margin: 0; padding-left: 24px; line-height: 1.5;">
                                        <t t-esc="partner.street" t-if="partner.street"/>
                                        <t t-if="partner.street and partner.city">, </t>
                                        <t t-esc="partner.city" t-if="partner.city"/>
                                        <t t-if="partner.city and partner.state_id">, </t>
                                        <t t-esc="partner.state_id.name" t-if="partner.state_id"/>
                                        <t t-if="partner.zip"> </t>
                                        <t t-esc="partner.zip" t-if="partner.zip"/>
                                        <t t-if="partner.country_id"><br/><t t-esc="partner.country_id.name"/></t>
                                    </p>
                                    <t t-set="google_maps_url" t-value="partner._get_google_maps_url()"/>
                                    <a t-if="google_maps_url" 
                                       t-att-href="google_maps_url" 
                                       target="_blank" 
                                       t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 6px 12px; border-radius: 8px; font-size: 0.75rem; font-weight: 600; text-decoration: none; display: inline-block; margin-top: 10px; margin-left: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                                       onmouseover="this.style.transform='scale(0.95)'"
                                       onmouseout="this.style.transform='scale(1)'">
                                        <i class="fa fa-map" style="margin-right: 4px;"></i>Directions
                                    </a>
                                </div>
                            </t>
                            
                        </div>
                    </div>
                </section>
            </t>
            
            <!-- Social Media Section -->
            <t t-if="partner.has_socials">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 20px; text-align: left;'">Social Media</h4>
                        <div style="display: flex; flex-wrap: wrap; gap: 12px; margin-top: 0;">
                            <!-- WhatsApp -->
                            <a t-if="partner.whatsapp_url" t-att-href="partner.whatsapp_url if partner.whatsapp_url.startswith('http') else 'https://' + partner.whatsapp_url" target="_blank" title="WhatsApp" 
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#25D366') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-whatsapp" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- LinkedIn -->
                            <a t-if="partner.linkedin_url" t-att-href="partner.linkedin_url if partner.linkedin_url.startswith('http') else 'https://' + partner.linkedin_url" target="_blank" title="LinkedIn"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#0077B5') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-linkedin" style="color: white; font-size: 20px;"></i>
                            </a>
                            <!-- LinkedIn Company -->
                            <a t-if="partner.linkedin_url_company" t-att-href="partner.linkedin_url_company if partner.linkedin_url_company.startswith('http') else 'https://' + partner.linkedin_url_company" target="_blank" title="Company LinkedIn"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#0077B5') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-linkedin" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- YouTube -->
                            <a t-if="partner.youtube_url" t-att-href="partner.youtube_url if partner.youtube_url.startswith('http') else 'https://' + partner.youtube_url" target="_blank" title="YouTube"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#FF0000') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-youtube" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Facebook -->
                            <a t-if="partner.facebook_url" t-att-href="partner.facebook_url if partner.facebook_url.startswith('http') else 'https://' + partner.facebook_url" target="_blank" title="Facebook"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#1877F2') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-facebook" style="color: white; font-size: 20px;"></i>
                            </a>
                            <!-- Facebook Company -->
                            <a t-if="partner.facebook_url_company" t-att-href="partner.facebook_url_company if partner.facebook_url_company.startswith('http') else 'https://' + partner.facebook_url_company" target="_blank" title="Company Facebook"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#1877F2') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-facebook" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Telegram -->
                            <a t-if="partner.telegram_url" t-att-href="partner.telegram_url if partner.telegram_url.startswith('http') else 'https://' + partner.telegram_url" target="_blank" title="Telegram"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#0088CC') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-telegram" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Instagram -->
                            <a t-if="partner.instagram_url" t-att-href="partner.instagram_url if partner.instagram_url.startswith('http') else 'https://' + partner.instagram_url" target="_blank" title="Instagram"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#E4405F') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-instagram" style="color: white; font-size: 20px;"></i>
                            </a>
                            <!-- Instagram Company -->
                            <a t-if="partner.instagram_url_company" t-att-href="partner.instagram_url_company if partner.instagram_url_company.startswith('http') else 'https://' + partner.instagram_url_company" target="_blank" title="Company Instagram"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#E4405F') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-instagram" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Twitter -->
                            <a t-if="partner.twitter_url" t-att-href="partner.twitter_url if partner.twitter_url.startswith('http') else 'https://' + partner.twitter_url" target="_blank" title="Twitter"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#1DA1F2') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-twitter" style="color: white; font-size: 20px;"></i>
                            </a>
                            <!-- Twitter Company -->
                            <a t-if="partner.twitter_url_company" t-att-href="partner.twitter_url_company if partner.twitter_url_company.startswith('http') else 'https://' + partner.twitter_url_company" target="_blank" title="Company Twitter"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#1DA1F2') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-twitter" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- GitHub -->
                            <a t-if="partner.github_url" t-att-href="partner.github_url if partner.github_url.startswith('http') else 'https://' + partner.github_url" target="_blank" title="GitHub"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#333') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-github" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Tumblr -->
                            <a t-if="partner.tumblr_url" t-att-href="partner.tumblr_url if partner.tumblr_url.startswith('http') else 'https://' + partner.tumblr_url" target="_blank" title="Tumblr"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#35465C') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-tumblr" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Xing -->
                            <a t-if="partner.xing_url" t-att-href="partner.xing_url if partner.xing_url.startswith('http') else 'https://' + partner.xing_url" target="_blank" title="Xing"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#006567') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-xing" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Vimeo -->
                            <a t-if="partner.vimeo_url" t-att-href="partner.vimeo_url if partner.vimeo_url.startswith('http') else 'https://' + partner.vimeo_url" target="_blank" title="Vimeo"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#1AB7EA') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-vimeo" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Facebook Messenger -->
                            <a t-if="partner.messenger_url" t-att-href="partner.messenger_url if partner.messenger_url.startswith('http') else 'https://' + partner.messenger_url" target="_blank" title="Messenger"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#0084FF') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-facebook-messenger" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Dribbble -->
                            <a t-if="partner.dribbble_url" t-att-href="partner.dribbble_url if partner.dribbble_url.startswith('http') else 'https://' + partner.dribbble_url" target="_blank" title="Dribbble"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#EA4C89') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-dribbble" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Skype -->
                            <a t-if="partner.skype_url" t-att-href="partner.skype_url if partner.skype_url.startswith('http') or partner.skype_url.startswith('skype:') else 'https://' + partner.skype_url" target="_blank" title="Skype"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#00AFF0') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-skype" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Pinterest -->
                            <a t-if="partner.pinterest_url" t-att-href="partner.pinterest_url if partner.pinterest_url.startswith('http') else 'https://' + partner.pinterest_url" target="_blank" title="Pinterest"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#E60023') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-pinterest" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Reddit -->
                            <a t-if="partner.reddit_url" t-att-href="partner.reddit_url if partner.reddit_url.startswith('http') else 'https://' + partner.reddit_url" target="_blank" title="Reddit"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#FF4500') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-reddit" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Snapchat -->
                            <a t-if="partner.snapchat_url" t-att-href="partner.snapchat_url if partner.snapchat_url.startswith('http') else 'https://' + partner.snapchat_url" target="_blank" title="Snapchat"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#FFFC00') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-snapchat" style="color: #000; font-size: 20px;"></i>
                            </a>
                            
                            <!-- TikTok -->
                            <a t-if="partner.tiktok_url" t-att-href="partner.tiktok_url if partner.tiktok_url.startswith('http') else 'https://' + partner.tiktok_url" target="_blank" title="TikTok"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#000000') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-tiktok" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Viber -->
                            <a t-if="partner.viber_url" t-att-href="partner.viber_url if partner.viber_url.startswith('http') or partner.viber_url.startswith('viber:') else 'https://' + partner.viber_url" target="_blank" title="Viber"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#665CAC') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-viber" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Line -->
                            <a t-if="partner.line_url" t-att-href="partner.line_url if partner.line_url.startswith('http') else 'https://' + partner.line_url" target="_blank" title="Line"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#00C300') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-line" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- Signal -->
                            <a t-if="partner.signal_url" t-att-href="partner.signal_url if partner.signal_url.startswith('http') else 'https://' + partner.signal_url" target="_blank" title="Signal"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#2592E9') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-signal-messenger" style="color: white; font-size: 20px;"></i>
                            </a>
                            
                            <!-- VKontakte -->
                            <a t-if="partner.vkontakte_url" t-att-href="partner.vkontakte_url if partner.vkontakte_url.startswith('http') else 'https://' + partner.vkontakte_url" target="_blank" title="VKontakte"
                               t-att-style="'width: 48px; height: 48px; background-color: ' + (partner.secondary_color or '#4C75A3') + '; border-radius: 12px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-vk" style="color: white; font-size: 20px;"></i>
                            </a>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Services Section -->
            <t t-if="partner.service_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left;'">Services</h4>
                        <div class="services-container" style="display: flex; flex-direction: column; gap: 16px;">
                            <t t-foreach="partner.service_ids" t-as="service">
                                <div class="service-card" 
                                     t-att-style="'background: ' + (partner.primary_color or '#ffffff') + '; border: 2px solid ' + (partner.secondary_color or '#007bff') + '; border-radius: 12px; padding: 20px; text-align: left; box-shadow: 0 2px 8px rgba(0,0,0,0.1);'">
                                    <h5 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0 0 8px 0; font-size: 18px; font-weight: 600;'">
                                        <t t-esc="service.name"/>
                                    </h5>
                                    <div t-att-style="'color: #64748b; margin: 0 0 12px 0; line-height: 1.6; font-size: 14px;'">
                                        <t t-esc="service.description"/>
                                    </div>
                                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 16px; flex-wrap: wrap; gap: 12px;">
                                        <div t-if="service.show_pricing and service.price" style="flex: 0 0 auto;">
                                            <span t-att-style="'color: ' + (partner.secondary_color or '#000') + '; font-weight: 600; font-size: 16px;'">
                                                <t t-esc="service.price"/>
                                            </span>
                                        </div>
                                        <div t-if="not service.show_pricing or not service.price" style="flex: 1;"></div>
                                        <a href="#" 
                                           class="btn service-request-btn" 
                                           t-att-data-service-id="service.id"
                                           t-att-data-service-name="service.name"
                                           t-att-data-service-description="service.description"
                                           t-att-style="'background-color: ' + (partner.secondary_color or '#007bff') + '; color: white; border: none; padding: 8px 20px; border-radius: 8px; font-weight: 600; text-decoration: none; display: inline-block; white-space: nowrap; flex: 0 0 auto;'"
                                           data-toggle="modal" 
                                           data-target="#serviceRequestModal">
                                            Request
                                        </a>
                                    </div>
                                </div>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Video Section -->
            <t t-if="partner.video_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left;'">Video</h4>
                        <div style="display: flex; flex-direction: column; gap: 20px;">
                            <t t-foreach="partner.video_ids" t-as="partner_video">
                                <div class="video-container" style="position: relative; width: 100%; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
                                    <iframe width="100%" height="315" 
                                            t-att-src="partner_video.embed_url + '?rel=0&amp;modestbranding=1&amp;showinfo=0'"
                                            frameborder="0" 
                                            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                            allowfullscreen="true"
                                            t-att-title="partner_video.name"
                                            loading="lazy"
                                            style="display: block;"
                                            onerror="this.style.display='none'; this.nextElementSibling.style.display='block';"></iframe>
                                    <div class="video-fallback" style="display: none; padding: 20px; text-align: center; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #dee2e6; border-radius: 12px;">
                                        <p><i class="fa fa-exclamation-triangle text-warning"></i> Video could not be loaded</p>
                                        <a t-att-href="partner_video.video_url" target="_blank" class="btn btn-primary btn-sm">
                                            <i class="fa fa-external-link"></i> Watch on YouTube
                                        </a>
                                    </div>
                                </div>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Websites Section -->
            <t t-if="partner.website_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left;'">Websites</h4>
                        <div style="display: flex; flex-wrap: wrap; gap: 12px;">
                            <t t-foreach="partner.website_ids" t-as="partner_website">
                                <a t-att-href="'http://' + partner_website.website_url if not (partner_website.website_url.startswith('http://') or partner_website.website_url.startswith('https://')) else partner_website.website_url"
                                   t-att-style="'background-color: ' + (partner_website.button_color or partner.secondary_color or '#2563eb') + '; color: white; padding: 12px 20px; border-radius: 12px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 8px;'"
                                   target="_blank"
                                   onmouseover="this.style.transform='scale(0.95)'"
                                   onmouseout="this.style.transform='scale(1)'">
                                    <t t-if="partner_website.button_logo">
                                        <img t-att-src="'data:image/png;base64,' + partner_website.button_logo.decode('utf-8')"
                                             alt="Logo" class="img-fluid" style="max-height: 24px;"/>
                                    </t>
                                    <t t-else="">
                                        <t t-esc="partner_website.name"/>
                                    </t>
                                </a>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Reviews Section -->
            <t t-if="partner.show_reviews">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 600px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left;'">
                            <t t-if="partner.reviews_section_title" t-esc="partner.reviews_section_title"/><t t-else="">Reviews</t>
                        </h4>
                        <div class="reviews-container" t-att-style="'text-align: center; max-width: 100%; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                            <t t-if="partner.review_ids">
                                <!-- Bootstrap Carousel with Fade Animation -->
                                <div id="reviewsCarousel" class="carousel slide carousel-fade" data-ride="carousel" data-pause="hover" t-att-data-interval="(partner.carousel_autoscroll_speed or 5) * 1000">
                                    <!-- Carousel Indicators - Completely removed to avoid overlapping with reviewer name -->
                                    
                                    <!-- Carousel Items -->
                                    <div class="carousel-inner">
                                        <t t-set="reviews_list" t-value="partner.review_ids.filtered(lambda r: r.is_published)[:partner.max_reviews_display or 5]"/>
                                        <t t-set="first_review" t-value="reviews_list[0] if reviews_list else None"/>
                                        <t t-foreach="reviews_list" t-as="review">
                                            <t t-set="is_first" t-value="review == first_review"/>
                                            <div t-att-class="'carousel-item' + (' active' if is_first else '')">
                                                <div class="review-item text-center" t-att-style="'margin: 0 auto; max-width: 100%; padding: 24px 60px; border-radius: 12px; background-color: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid rgba(0,0,0,0.1);'">
                                                    <div class="review-rating" t-att-style="'color: #ffc107; font-size: 24px; margin-bottom: 16px;'">
                                                        <t t-esc="review.stars_display"/>
                                                    </div>
                                                    <div class="review-text" t-att-style="'color: #495057; font-style: italic; line-height: 1.6; font-size: 16px; margin-bottom: 16px; word-wrap: break-word;'">
                                                        <t t-out="review.review_text"/>
                                                    </div>
                                                    <div class="reviewer-info">
                                                        <h5 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0; font-weight: 600; font-size: 14px;'">
                                                            — <t t-if="review.reviewer_name" t-esc="review.reviewer_name"/><t t-else="">Anonymous</t>
                                                        </h5>
                                                    </div>
                                                </div>
                                            </div>
                                        </t>
                                    </div>
                                    
                                    <!-- Carousel Controls -->
                                    <a class="carousel-control-prev" href="#reviewsCarousel" role="button" data-slide="prev">
                                        <span class="carousel-control-prev-icon" aria-hidden="true"></span>
                                        <span class="sr-only">Previous</span>
                                    </a>
                                    <a class="carousel-control-next" href="#reviewsCarousel" role="button" data-slide="next">
                                        <span class="carousel-control-next-icon" aria-hidden="true"></span>
                                        <span class="sr-only">Next</span>
                                    </a>
                                </div>
                            </t>
                            <t t-else="">
                                <div class="text-center" t-att-style="'color: #64748b; padding: 20px;'">
                                    <p>No reviews yet. Be the first to leave a review!</p>
                                </div>
                            </t>
                        </div>
                    </div>
                </section>
            </t>
            
            <!-- Leave a Review Button - Outside Reviews Section -->
            <t t-if="partner.show_reviews">
                <div style="text-align: center; padding: 20px 0; max-width: 600px; margin-left: auto; margin-right: auto; padding: 20px 16px;">
                    <a href="#" 
                       t-att-style="'width: 100%; background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; gap: 8px;'"
                       data-toggle="modal" 
                       data-target="#reviewModal"
                       onmouseover="this.style.transform='scale(0.95)'"
                       onmouseout="this.style.transform='scale(1)'">
                        Leave a Review
                    </a>
                </div>
            </t>

            <!-- Calendly widget -->
            <t t-if="partner.calendly_url">
                <div class="calendly-inline-widget"
                     t-att-data-url="partner.calendly_url"
                     style="min-width: 100%; height: 100vh; overflow: hidden; margin-bottom: 0; padding-bottom: 0;"></div>
                <script type="text/javascript"
                        src="https://assets.calendly.com/assets/external/widget.js"></script>
            </t>

            <!-- Modals (same as Classic template) -->
            <!-- Lead Modal -->
            <div class="modal fade" id="leadModal" tabindex="-1" role="dialog" aria-labelledby="leadModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true" data-dismiss-on-backdrop="true">
              <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
                <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                  <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                    <div style="display: flex; align-items: center; width: 100%;">
                      <div style="flex: 1;">
                        <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="leadModalLabel">Fill in your details</h5>
                      </div>
                      <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                        <span aria-hidden="true">×</span>
                    </button>
                  </div>
                  </div>
                  <div class="modal-body" style="padding: 16px 24px 24px 24px;">
                    <div id="successMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                      <i class="fa fa-check-circle me-2"></i>Thank you! I look forward to talking with you soon.
                    </div>
            <form id="leadForm">
                <div class="form-group">
                    <input type="hidden" class="form-control" id="partnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                    <input type="hidden" id="leadTagIds" name="lead_tag_ids" t-att-value="','.join(map(str, partner.lead_tag_ids.ids))"/>
                    <input type="hidden" id="formThankYouMessage" t-att-value="partner.form_thank_you_message or 'Thank you! I look forward to talking with you soon.'"/>
                </div>
                <div class="form-group">
                    <label for="fullName">Full name <span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="fullName" name="full_name" required="required" placeholder="Your name"/>
                </div>
                <div class="form-group">
                    <label for="email">Email <span class="text-danger">*</span></label>
                    <input type="email" class="form-control" id="email" name="email" required="required" placeholder="you@example.com"/>
                </div>
                <div class="form-group">
                    <label for="phone">Phone</label>
                    <input type="tel" class="form-control" id="phone" name="phone" placeholder="Your phone number"/>
                    <input type="hidden" id="phone_full" name="phone_full"/>
                </div>
                <style>
                    #leadModal .form-group {{ position: relative; margin-bottom: 14px; }}
                    #leadModal .form-group label {{ display: block !important; margin-bottom: 4px; font-weight: 500; color: #374151; }}
                    #leadModal .form-group .form-control,
                    #leadModal .form-group input.form-control {{ display: block; width: 100%; height: 40px; box-sizing: border-box; }}
                    #leadModal textarea.form-control {{ height: auto; min-height: 80px; }}
                    #leadModal .iti {{ display: block !important; width: 100%; }}
                    #leadModal .iti__flag-container {{ position: absolute; top: 0; bottom: 0; right: auto; left: 0; z-index: 2; }}
                    #leadModal .iti__selected-flag {{ z-index: 4; position: relative; display: flex; align-items: center; height: 100%; padding: 0 10px 0 12px; background-color: #f8f9fa; border-right: 1px solid #dee2e6; border-radius: 4px 0 0 4px; cursor: pointer; min-width: 76px; }}
                    #leadModal .iti__flag-box {{ margin-right: 6px; }}
                    #leadModal .iti__arrow {{ margin-left: 6px; width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 4px solid #555; }}
                    #leadModal .iti__selected-dial-code {{ margin-left: 2px; font-size: 14px; color: #374151; }}
                    #leadModal #phone {{ padding-left: 88px !important; }}
                    #leadModal .iti__country-list {{ z-index: 9999 !important; }}
                </style>
                <div class="form-group">
                    <label for="notes">Notes</label>
                    <textarea class="form-control" id="notes" name="notes" placeholder="Anything else you'd like to share (optional)"></textarea>
                </div>
            </form>
                  </div>
                  <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; flex-direction: column; gap: 12px;">
                    <button type="button" id="submitLeadBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 12px 24px; border-radius: 8px; width: 100%;'">
                      Share My Contact
                    </button>
                    <small style="text-align: center; color: #6b7280; font-size: 12px; margin: 0;"><t t-set="vinc_label">* By clicking the 'Share My Contact' button, I agree to be contacted by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                  </div>
                </div>
              </div>
            </div>

            <!-- QR Code Modal -->
            <div class="modal fade" id="qrCodeModal" tabindex="-1" role="dialog" aria-labelledby="qrCodeModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
              <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 400px;">
                <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                  <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                    <div style="display: flex; align-items: center; width: 100%;">
                      <div style="width: 40px; height: 40px; background: #f3f4f6; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin-right: 12px;">
                        <i class="fa fa-qrcode" style="font-size: 20px; color: #6b7280;"></i>
                      </div>
                      <div style="flex: 1;">
                        <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="qrCodeModalLabel">
                          <t t-if="partner.name" t-esc="partner.name"/><t t-else="">QR Code</t>
                        </h5>
                        <p style="margin: 4px 0 0 0; font-size: 14px; color: #6b7280;">Scan to connect</p>
                      </div>
                      <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                        <span aria-hidden="true">×</span>
                      </button>
                    </div>
                  </div>
                  <div class="modal-body" style="padding: 16px 24px 24px 24px; text-align: center;">
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #6b7280; line-height: 1.5;">
                      <t t-set="vinc_label">Scan this QR code to quickly save %(name)s's information to your device.</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/>
                    </p>
                    <div t-att-style="'background: ' + (partner.primary_color or '#ffffff') + '; padding: 20px; border-radius: 12px; display: inline-block; box-shadow: 0 2px 8px rgba(0,0,0,0.1);'">
                      <img t-att-src="'/vcard/qr_code/download/' + str(partner.id)" 
                           alt="QR Code" 
                           style="width: 250px; height: 250px; max-width: 100%; display: block;"/>
                    </div>
                  </div>
                  <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; justify-content: space-between; gap: 12px;">
                    <button type="button" class="btn" data-dismiss="modal" style="background: transparent; border: none; color: #6b7280; font-weight: 500; padding: 10px 20px; flex: 1;">
                      Close
                    </button>
                    <a t-att-href="'/website/vcard/download/' + str(partner.id)" 
                       class="btn" 
                       t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; flex: 1; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px;'">
                      <i class="fa fa-download"></i>
                      <span>Download vCard</span>
                    </a>
                  </div>
                </div>
              </div>
            </div>

            <!-- Review Modal -->
            <div class="modal fade" id="reviewModal" tabindex="-1" role="dialog" aria-labelledby="reviewModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
              <div class="modal-dialog" role="document">
                <div class="modal-content">
                  <div class="modal-header">
                   <h5 class="modal-title" style="text-align: center;" id="reviewModalLabel">Leave a Review</h5>
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                      <span aria-hidden="true">&#215;</span>
                    </button>
                  </div>
                  <div class="modal-body">
                    <div id="reviewSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                      <i class="fa fa-check-circle me-2"></i>Thank you for your review! We appreciate your feedback.
                    </div>
            <form id="reviewForm" onsubmit="return false;">
                <div class="form-group">
                    <input type="hidden" class="form-control" id="reviewPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                    <input type="hidden" id="reviewThankYouMessage" t-att-value="partner.review_thank_you_message or 'Thank you for your review! We appreciate your feedback.'"/>
                </div>
                <div class="form-group">
                    <label for="reviewerName">Your Name<span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="reviewerName" name="reviewer_name" required="required"/>
                </div>
                <div class="form-group">
                    <label for="reviewRating">Rating<span class="text-danger">*</span></label>
                    <div class="star-rating" style="font-size: 32px; color: #ffc107; cursor: pointer;">
                        <span class="star" data-rating="1">&#9734;</span>
                        <span class="star" data-rating="2">&#9734;</span>
                        <span class="star" data-rating="3">&#9734;</span>
                        <span class="star" data-rating="4">&#9734;</span>
                        <span class="star" data-rating="5">&#9734;</span>
                    </div>
                    <input type="hidden" id="reviewRating" name="rating" value="5" required="required"/>
                </div>
                <div class="form-group">
                    <label for="reviewText">Your Review<span class="text-danger">*</span></label>
                    <textarea class="form-control" id="reviewText" name="review_text" rows="4" required="required"></textarea>
                </div>
                <div class="text-center" style="padding-top: 5px;">
                    <button type="button" id="submitReviewBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%; text-decoration: none; display: inline-block; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                            onmouseover="this.style.transform='scale(0.95)'"
                            onmouseout="this.style.transform='scale(1)'">Submit Review</button>
                </div>
            </form>
                  </div>
                 <div class="modal-footer" style="justify-content: center !important; padding: 0;">
                <small><t t-set="vinc_label">* Your review will be visible once approved by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/> </small>
                                </div>
                            </div>
                        </div>
                    </div>

            <!-- Service Request Modal -->
            <div class="modal fade" id="serviceRequestModal" tabindex="-1" role="dialog" aria-labelledby="serviceRequestModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
              <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
                <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                  <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                    <div style="display: flex; align-items: center; width: 100%;">
                      <div style="flex: 1;">
                        <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="serviceRequestModalLabel">
                          Request Service
                        </h5>
                      </div>
                      <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                        <span aria-hidden="true">×</span>
                      </button>
                    </div>
                  </div>
                  <div class="modal-body" style="padding: 16px 24px 24px 24px;">
                    <div id="serviceRequestSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                      <i class="fa fa-check-circle me-2"></i>Thank you! Your service request has been sent. We'll be in touch shortly.
                    </div>
                    <form id="serviceRequestForm">
                      <div class="form-group">
                        <input type="hidden" class="form-control" id="serviceRequestPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                        <input type="hidden" id="serviceRequestServiceId" name="service_id" value=""/>
                        <input type="hidden" id="serviceRequestServiceName" name="service_name" value=""/>
                        <input type="hidden" id="serviceRequestServiceDescription" name="service_description" value=""/>
                      </div>
                      <div class="form-group" style="margin-bottom: 20px;">
                        <label style="margin-bottom: 8px; font-weight: 600; color: #111827;"><strong>Service:</strong></label>
                        <p id="serviceRequestServiceDisplay" t-att-style="'margin: 0; padding: 12px; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #e5e7eb; border-radius: 8px; color: #111827; font-weight: 600; font-size: 16px;'"></p>
                      </div>
                      <div class="form-group">
                        <label for="serviceRequestFullName">Full name<span class="text-danger">*</span></label>
                        <input type="text" class="form-control" id="serviceRequestFullName" name="full_name" required="required"/>
                      </div>
                      <div class="form-group">
                        <label for="serviceRequestEmail">Email<span class="text-danger">*</span></label>
                        <input type="email" class="form-control" id="serviceRequestEmail" name="email" required="required"/>
                      </div>
                      <div class="form-group">
                        <label for="serviceRequestPhone">Phone</label>
                        <input type="tel" class="form-control" id="serviceRequestPhone" name="phone" placeholder="Your Phone"/>
                        <input type="hidden" id="serviceRequestPhoneFull" name="phone_full"/>
                      </div>
                      <div id="serviceRequestCustomQuestions"></div>
                      <div class="form-group">
                        <label for="serviceRequestNotes">Additional Details</label>
                        <textarea class="form-control" id="serviceRequestNotes" name="notes" rows="4" placeholder="Add any additional information or requirements..."></textarea>
                      </div>
                      <div class="text-center" style="padding-top: 10px;">
                        <button type="button" id="submitServiceRequestBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%;'">Send Request</button>
                      </div>
                    </form>
                  </div>
                  <div class="modal-footer" style="border-top: none; padding: 0 24px 24px 24px; text-align: center;">
                    <small style="color: #6b7280; font-size: 12px;"><t t-set="vinc_label">* By clicking 'Send Request', I agree to be contacted by %(name)s regarding this service</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                  </div>
                </div>
              </div>
            </div>

            <!-- Load scripts -->
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/css/intlTelInput.css"/>
            <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
            <script type="text/javascript" src="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/js/bootstrap.min.js"></script>
            <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/js/intlTelInput.min.js"></script>
            <script type="text/javascript" t-attf-src="/qr_code_odoo/static/src/js/widget.js"></script>
            
            <!-- Modal and Carousel Scripts (same as Classic template) -->
            <script>
                document.addEventListener('DOMContentLoaded', function() {{
                    // Modal clickability fixes (same as Classic template)
                    $(document).on('show.bs.modal', '.modal', function() {{
                        var $modal = $(this);
                        if ($modal.parent().is('body') === false) {{
                            $modal.appendTo('body');
                        }}
                    }});
                    
                    $(document).on('shown.bs.modal', '.modal', function() {{
                        var $modal = $(this);
                        var $backdrop = $('.modal-backdrop');
                        $backdrop.css({{
                            'z-index': '2040',
                            'position': 'fixed',
                            'top': '0',
                            'left': '0',
                            'width': '100%',
                            'height': '100%',
                            'pointer-events': 'auto'
                        }});
                        $modal.css({{
                            'z-index': '2050',
                            'position': 'fixed',
                            'top': '0',
                            'left': '0',
                            'width': '100%',
                            'height': '100%',
                            'pointer-events': 'none'
                        }});
                        $modal.find('.modal-dialog').css({{
                            'z-index': '2051',
                            'position': 'relative',
                            'pointer-events': 'auto',
                            'margin': '1.75rem auto'
                        }});
                        $modal.find('.modal-content').css({{
                            'z-index': '2052',
                            'position': 'relative',
                            'pointer-events': 'auto',
                            'background-color': 'white',
                            'border-radius': '16px'
                        }});
                        $modal.find('.modal-content *').css('pointer-events', 'auto');
                    }});
                    
                    $(document).on('click', '.modal-content, .modal-header, .modal-body, .modal-footer', function(e) {{
                        e.stopPropagation();
                        e.stopImmediatePropagation();
                    }});
                    
                    $(document).on('click', '.modal input, .modal textarea, .modal select, .modal button:not(#submitReviewBtn):not(#submitLeadBtn):not(#submitServiceRequestBtn), .modal a:not([data-dismiss]), .modal .form-control, .modal label', function(e) {{
                        e.stopPropagation();
                        e.stopImmediatePropagation();
                    }});
                    
                    $(document).on('click', '.modal-backdrop', function(e) {{
                        $('.modal.show').modal('hide');
                    }});
                    
                    $(document).on('click', '.modal', function(e) {{
                        if ($(e.target).hasClass('modal')) {{
                            $(this).modal('hide');
                        }}
                    }});
                    
                    // Carousel initialization
                    const carousel = document.getElementById('reviewsCarousel');
                    if (carousel) {{
                        // Remove carousel indicators completely to avoid overlapping with reviewer name
                        const indicators = carousel.querySelector('.carousel-indicators');
                        if (indicators) {{
                            indicators.remove();
                        }}
                        
                        const autoscrollSpeed = carousel.getAttribute('data-interval');
                        const intervalValue = autoscrollSpeed ? parseInt(autoscrollSpeed) : 5000;
                        $(carousel).carousel({{
                            interval: intervalValue > 0 ? intervalValue : false,
                            wrap: true,
                            touch: true,
                            pause: 'hover'
                        }});
                        
                        // Ensure indicators are removed after carousel initialization (in case Bootstrap generates them)
                        $(carousel).on('slide.bs.carousel', function() {{
                            const ind = this.querySelector('.carousel-indicators');
                            if (ind) {{
                                ind.remove();
                            }}
                        }});
                        
                        // Force show arrows on desktop
                        if (window.innerWidth > 768) {{
                            const prevBtn = carousel.querySelector('.carousel-control-prev');
                            const nextBtn = carousel.querySelector('.carousel-control-next');
                            if (prevBtn) {{
                                prevBtn.style.display = 'flex';
                                prevBtn.style.opacity = '0.9';
                                prevBtn.style.visibility = 'visible';
                            }}
                            if (nextBtn) {{
                                nextBtn.style.display = 'flex';
                                nextBtn.style.opacity = '0.9';
                                nextBtn.style.visibility = 'visible';
                            }}
                        }}
                        
                        // Periodically check and remove any dynamically generated indicators
                        setInterval(function() {{
                            const ind = carousel.querySelector('.carousel-indicators');
                            if (ind) {{
                                ind.remove();
                            }}
                        }}, 500);
                    }}
                    
                    // Auto-show lead form feature
                    var wrapDiv = document.getElementById('wrap');
                    if (wrapDiv) {{
                        var autoShowLead = wrapDiv.getAttribute('data-auto-show-lead');
                        if (autoShowLead === 'true') {{
                            setTimeout(function() {{
                                $('#leadModal').modal('show');
                            }}, 500);
                        }}
                        
                        // Auto-download vCard feature
                        var autoDownloadVcard = wrapDiv.getAttribute('data-auto-download-vcard');
                        if (autoDownloadVcard === 'true') {{
                            setTimeout(function() {{
                                var downloadUrl = wrapDiv.getAttribute('data-vcard-download-url');
                                if (downloadUrl) {{
                                    window.location.href = downloadUrl;
                                }}
                            }}, 800);
                        }}
                    }}
                }});
            </script>

            
            <!-- Modal and Carousel CSS -->
            <style>
                .modal-backdrop {{
                    background-color: rgba(0, 0, 0, 0.3) !important;
                    opacity: 1 !important;
                    z-index: 2040 !important;
                    position: fixed !important;
                    top: 0 !important;
                    left: 0 !important;
                    width: 100% !important;
                    height: 100% !important;
                }}
                .modal {{
                    z-index: 2050 !important;
                    position: fixed !important;
                    top: 0 !important;
                    left: 0 !important;
                    width: 100% !important;
                    height: 100% !important;
                    pointer-events: none !important;
                }}
                .modal.show {{
                    display: block !important;
                }}
                .modal-dialog {{
                    z-index: 2051 !important;
                    position: relative !important;
                    pointer-events: auto !important;
                    margin: 1.75rem auto !important;
                }}
                .modal-content {{
                    z-index: 2052 !important;
                    position: relative !important;
                    pointer-events: auto !important;
                    background-color: var(--primary-color, #ffffff) !important;
                    border-radius: 16px !important;
                }}
                
                /* Carousel fade animation */
                .carousel-fade .carousel-item {{
                    opacity: 0;
                    transition: opacity 0.3s ease-in-out;
                    transform: translateZ(0);
                }}
                .carousel-fade .carousel-item.active {{
                    opacity: 1;
                }}
                .carousel-fade .carousel-item-next,
                .carousel-fade .carousel-item-prev {{
                    opacity: 0;
                }}
                .carousel-fade .carousel-item-next.active,
                .carousel-fade .carousel-item-prev.active {{
                    opacity: 1;
                }}
                
                /* Carousel controls styling - Circular buttons with arrows */
                .carousel-control-prev,
                .carousel-control-next {{
                    width: 40px !important;
                    height: 40px !important;
                    min-width: 40px !important;
                    min-height: 40px !important;
                    max-width: 40px !important;
                    max-height: 40px !important;
                    background-color: rgba(0,0,0,0.7) !important;
                    border-radius: 50% !important;
                    top: 50% !important;
                    transform: translateY(-50%) !important;
                    opacity: 0.9 !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    transition: all 0.3s ease !important;
                    border: 2px solid rgba(255,255,255,0.5) !important;
                    z-index: 10 !important;
                    box-sizing: border-box !important;
                    padding: 0 !important;
                    margin: 0 !important;
                    text-decoration: none !important;
                    outline: none !important;
                }}
                
                .carousel-control-prev {{
                    left: 10px !important;
                }}
                
                .carousel-control-next {{
                    right: 10px !important;
                }}
                
                /* Add padding to review items to prevent overlap with carousel controls */
                #reviewsCarousel .review-item {{
                    padding-left: 60px !important;
                    padding-right: 60px !important;
                }}
                
                /* On mobile, reduce padding since buttons are hidden */
                @media (max-width: 768px) {{
                    #reviewsCarousel .review-item {{
                        padding-left: 24px !important;
                        padding-right: 24px !important;
                    }}
                }}
                
                .carousel-control-prev:hover,
                .carousel-control-next:hover {{
                    opacity: 1 !important;
                    background-color: rgba(0,0,0,0.9) !important;
                    border-color: rgba(255,255,255,0.8) !important;
                    transform: translateY(-50%) scale(1.05) !important;
                    text-decoration: none !important;
                }}
                
                .carousel-control-prev-icon,
                .carousel-control-next-icon {{
                    width: 20px !important;
                    height: 20px !important;
                    background: none !important;
                    background-image: none !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    font-size: 18px !important;
                    color: white !important;
                    font-weight: bold !important;
                }}
                
                /* Use Unicode arrows */
                .carousel-control-prev-icon:before {{
                    content: "◀" !important;
                    display: block !important;
                }}
                
                .carousel-control-next-icon:before {{
                    content: "▶" !important;
                    display: block !important;
                }}
                
                /* Ensure buttons are visible on desktop */
                @media (min-width: 769px) {{
                    .carousel-control-prev,
                    .carousel-control-next {{
                        display: flex !important;
                        opacity: 0.9 !important;
                        visibility: visible !important;
                    }}
                }}
                
                /* Hide carousel indicators completely - no numbers showing or overlapping */
                #reviewsCarousel .carousel-indicators,
                .carousel-indicators {{
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    position: absolute !important;
                    left: -9999px !important;
                    width: 0 !important;
                    height: 0 !important;
                    overflow: hidden !important;
                    pointer-events: none !important;
                    z-index: -1 !important;
                }}
                
                #reviewsCarousel .carousel-indicators li,
                .carousel-indicators li {{
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    width: 0 !important;
                    height: 0 !important;
                    pointer-events: none !important;
                }}
                
                /* Ensure reviewer name is not overlapped */
                .reviewer-info {{
                    position: relative !important;
                    z-index: 10 !important;
                }}
                
                /* Hide on mobile */
                @media (max-width: 768px) {{
                    .carousel-control-prev,
                    .carousel-control-next {{
                        display: none !important;
                    }}
                }}
            </style>


                </div> <!-- Close container-fluid -->
            </div> <!-- Close wrap -->
        </t>
    </t>
"""

    def _build_minimal_template(self, image_url, banner_url=None, referral_url=None):
        if referral_url is None:
            referral_url = self.get_referral_signup_url()
        """Build the minimal vCard template with tabbed navigation."""
        partner = self
        return f"""
        <t t-name="website.{self.website_slug}">
            <t t-set="partner" t-value="request.env['partner.vcard'].sudo().browse({self.id})"/>
    
            <!-- Dashboard Button (visible to logged-in internal users) -->
            <t t-if="not request.env.user._is_public()">
                <style>
                    @media only screen and (max-width: 600px) {{
                        .dashboard-btn-container {{
                            top: 10px !important;
                            right: 10px !important;
                        }}
                        .dashboard-btn-container a {{
                            padding: 10px 16px !important;
                            font-size: 12px !important;
                        }}
                        .dashboard-btn-container .fa {{
                            font-size: 14px !important;
                        }}
                    }}
                </style>
                <div class="dashboard-btn-container" style="position: fixed; top: 20px; right: 20px; z-index: 9999;">
                    <a href="/web#action=qr_code_odoo.action_user_dashboard" 
                       style="display: inline-flex; align-items: center; gap: 8px; padding: 12px 20px; background: rgba(69, 126, 184, 0.9); color: white; text-decoration: none; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 14px; font-weight: 500; transition: all 0.3s ease; z-index: 9999;"
                       onmouseover="this.style.background='rgba(69, 126, 184, 1)'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';"
                       onmouseout="this.style.background='rgba(69, 126, 184, 0.9)'; this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.2)';">
                        <i class="fa fa-dashboard" style="font-size: 16px;"></i>
                        <span>Back to Dashboard</span>
                    </a>
                </div>
            </t>
    
            <!-- Use custom vCard layout without header and footer -->
            <t t-call="qr_code_odoo.vcard_layout">
                <div id="wrap" class="oe_structure oe_empty vcard-template-minimal"
                     t-att-style="'text-align: center; font-family: Poppins, sans-serif; padding-top: 0; background-color: ' + (partner.primary_color or '#ffffff') + ';'"
                     t-att-data-auto-show-lead="str(partner.auto_show_lead_form and partner.show_form and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-auto-download-vcard="str(partner.auto_download_vcard and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-vcard-download-url="'/website/vcard/download/' + str(partner.id)">

                
                    <div class="container-fluid" style="max-width: 600px; margin: 0 auto; padding: 0;">
                        
                        <!-- Minimal Banner -->
                        <div class="banner-container" style="position: relative; width: 100%; height: 160px; margin-bottom: 0; z-index: 1; overflow: hidden;">
                            <t t-if="partner.banner_attachment_id">
                                <div class="banner-image-wrapper" style="width: 100%; height: 100%; overflow: hidden; background-color: #ffffff; position: relative; padding: 18px 28px; box-sizing: border-box;">
                                    <img t-att-src="'/website/image/ir.attachment/' + str(partner.banner_attachment_id.id) + '/datas'"
                                         alt="" 
                                         style="width: 100%; height: 100%; object-fit: contain; display: block;"
                                         onerror="this.style.display='none';"/>
                                </div>
                            </t>
                            <t t-if="not partner.banner_attachment_id">
                                <div class="banner-image-wrapper" 
                                     t-att-style="'width: 100%; height: 100%; background-color: ' + (partner.primary_color or '#f3f4f6') + '; position: relative;'">
                                </div>
                            </t>
                        </div>
                        
                        <!-- Minimal Header -->
                        <div t-att-style="'padding: 16px 16px 24px 16px; background: ' + (partner.primary_color or '#ffffff') + ';'">
                            <!-- Profile Picture -->
                            <div style="margin-bottom: 16px;">
                                <t t-if="partner.attachment_id">
                                    <img t-att-src="'/website/image/ir.attachment/' + str(partner.attachment_id.id) + '/datas'"
                                         alt=""
                                         class="img img-fluid rounded-circle"
                                         style="width: 100px; height: 100px; object-fit: cover; border: 2px solid #e5e7eb; display: block; margin: 0 auto;"/>
                                </t>
                                <t t-if="not partner.attachment_id">
                                    <div class="rounded-circle" 
                                         t-att-style="'width: 100px; height: 100px; background-color: ' + (partner.secondary_color or '#e5e7eb') + '; display: flex; align-items: center; justify-content: center; margin: 0 auto; border: 2px solid #e5e7eb;'">
                                        <span t-att-style="'color: ' + (partner.primary_color or '#6b7280') + '; font-size: 2rem; font-weight: 600;'">
                                            <t t-esc="partner.name[0] if partner.name else '?'"/>
                                        </span>
                                    </div>
                                </t>
                            </div>
                            
                            <!-- Name -->
                            <h1 style="margin: 0 0 8px 0; font-size: 1.5rem; font-weight: 600; color: #111827;">
                                <t t-esc="partner.name"/>
                            </h1>
                            
                            <!-- Job Title -->
                            <p t-if="partner.function" style="margin: 0 0 4px 0; font-size: 0.875rem; color: #6b7280;">
                                <t t-esc="partner.function"/>
                            </p>
                            
                            <!-- Company -->
                            <p t-if="partner.company_name" style="margin: 0 0 24px 0; font-size: 0.875rem; color: #9ca3af;">
                                <t t-esc="partner.company_name"/>
                            </p>
                            
                            <!-- Action Buttons -->
                            <div style="display: flex; gap: 8px; justify-content: center; margin-bottom: 24px;">
                                <a t-att-href="'/website/vcard/download/' + str(partner.id)"
                                   t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 10px 20px; border-radius: 6px; font-size: 0.875rem; font-weight: 500; text-decoration: none; display: inline-block;'">
                                    <t t-set="vinc_label">Get %(name)s's Info</t><t t-out="vinc_label % {{'name': partner.name.split(' ')[0] if partner.name else ''}}"/>
                                </a>
                                <t t-if="partner.show_form">
                                    <a href="#" 
                                       data-toggle="modal" 
                                       data-target="#leadModal"
                                       t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 10px 20px; border-radius: 6px; font-size: 0.875rem; font-weight: 500; text-decoration: none; display: inline-block; border: 1px solid ' + (partner.secondary_color or '#2563eb') + ';'">
                                        <t t-if="partner.lead_button_label" t-esc="partner.lead_button_label"/><t t-else="">Get In Touch</t>
                                    </a>
                                </t>
                            </div>
                        </div>
                        
                        <!-- Tab Navigation -->
                        <div t-att-style="'border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; background: ' + (partner.primary_color or '#ffffff') + ';'">
                            <div style="display: flex; overflow-x: auto; -webkit-overflow-scrolling: touch; scrollbar-width: none; -ms-overflow-style: none;">
                                <div style="display: flex; min-width: 100%;">
                                    <button class="minimal-tab-btn active" 
                                            data-tab="contact"
                                            t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; border-bottom: 2px solid ' + (partner.secondary_color or '#2563eb') + ';'"
                                            style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap;">
                                        Contact
                                    </button>
                                    <button class="minimal-tab-btn" 
                                            data-tab="about"
                                            style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                        About
                                    </button>
                                    <t t-if="partner.has_socials">
                                        <button class="minimal-tab-btn" 
                                                data-tab="social"
                                                style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                            Social
                                        </button>
                                    </t>
                                    <t t-if="partner.service_ids">
                                        <button class="minimal-tab-btn" 
                                                data-tab="services"
                                                style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                            Services
                                        </button>
                                    </t>
                                    <t t-if="partner.review_ids and partner.show_reviews">
                                        <button class="minimal-tab-btn" 
                                                data-tab="reviews"
                                                style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                            Reviews
                                        </button>
                                    </t>
                                    <t t-if="partner.speciality_ids">
                                        <button class="minimal-tab-btn" 
                                                data-tab="specialities"
                                                style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                            Specialities
                                        </button>
                                    </t>
                                    <t t-if="partner.website_ids">
                                        <button class="minimal-tab-btn" 
                                                data-tab="websites"
                                                style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                            Websites
                                        </button>
                                    </t>
                                    <t t-if="partner.calendly_url">
                                        <button class="minimal-tab-btn" 
                                                data-tab="calendar"
                                                style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                            Calendar
                                        </button>
                                    </t>
                                    <button class="minimal-tab-btn" 
                                            data-tab="qrcode"
                                            style="flex: 1; padding: 12px 8px; background: none; border: none; border-bottom: 2px solid transparent; font-size: 0.875rem; font-weight: 500; cursor: pointer; white-space: nowrap; color: #6b7280;">
                                        QR Code
                                    </button>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Tab Content -->
                        <div t-att-style="'background: ' + (partner.primary_color or '#ffffff') + '; min-height: 200px;'">
                            
                            <!-- Contact Tab (First) -->
                            <div class="minimal-tab-content" data-content="contact" t-att-style="'display: block; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div style="text-align: left;">
                                    <t t-if="partner.email">
                                        <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
                                            <i class="fa fa-envelope" style="color: #6b7280; font-size: 18px; width: 20px;"></i>
                                            <a t-att-href="'mailto:' + partner.email" 
                                               onclick="window.open(this.getAttribute('href'), '_self'); return false;"
                                               style="color: #111827; text-decoration: none; font-size: 0.875rem;">
                                                <t t-esc="partner.email"/>
                                            </a>
                                        </div>
                                    </t>
                                    <t t-if="partner.phone">
                                        <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
                                            <i class="fa fa-phone" style="color: #6b7280; font-size: 18px; width: 20px;"></i>
                                            <a t-att-href="'tel:' + partner.phone" 
                                               style="color: #111827; text-decoration: none; font-size: 0.875rem;">
                                                <t t-esc="partner.phone"/>
                                            </a>
                                        </div>
                                    </t>
                                    <t t-if="partner.mobile">
                                        <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
                                            <i class="fa fa-mobile" style="color: #6b7280; font-size: 18px; width: 20px;"></i>
                                            <a t-att-href="'tel:' + partner.mobile" 
                                               style="color: #111827; text-decoration: none; font-size: 0.875rem;">
                                                <t t-esc="partner.mobile"/>
                                            </a>
                                        </div>
                                    </t>
                                    <t t-if="partner.street or partner.city or partner.state_id or partner.zip or partner.country_id">
                                        <div style="margin-bottom: 16px; display: flex; align-items: flex-start; gap: 12px;">
                                            <i class="fa fa-map-marker" style="color: #6b7280; font-size: 18px; width: 20px; margin-top: 2px;"></i>
                                            <div style="flex: 1;">
                                                <div style="color: #111827; font-size: 0.875rem; line-height: 1.5; display: inline;">
                                                    <t t-esc="partner.street" t-if="partner.street"/>
                                                    <t t-if="partner.street and partner.city">, </t>
                                                    <t t-esc="partner.city" t-if="partner.city"/>
                                                    <t t-if="partner.city and partner.state_id">, </t>
                                                    <t t-esc="partner.state_id.name" t-if="partner.state_id"/>
                                                    <t t-if="partner.zip"> </t>
                                                    <t t-esc="partner.zip" t-if="partner.zip"/>
                                                    <t t-if="partner.country_id"><br/><t t-esc="partner.country_id.name"/></t>
                                                </div>
                                                <t t-set="google_maps_url" t-value="partner._get_google_maps_url()"/>
                                                <t t-if="google_maps_url">
                                                    <a t-att-href="google_maps_url" 
                                                       target="_blank" 
                                                       t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; text-decoration: none; font-size: 0.875rem; font-weight: 500; margin-left: 8px; display: inline-flex; align-items: center; gap: 4px;'">
                                                        <i class="fa fa-map"></i> Directions
                                                    </a>
                                                </t>
                                            </div>
                                        </div>
                                    </t>
                                    <t t-if="partner.company_name">
                                        <div style="margin-bottom: 16px; display: flex; align-items: center; gap: 12px;">
                                            <i class="fa fa-building" style="color: #6b7280; font-size: 18px; width: 20px;"></i>
                                            <span style="color: #111827; font-size: 0.875rem;">
                                                <t t-esc="partner.company_name"/>
                                            </span>
                                        </div>
                                    </t>
                                </div>
                            </div>
                            
                            <!-- Social Tab -->
                            <div class="minimal-tab-content" data-content="social" t-att-style="'display: none; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div style="display: flex; flex-wrap: wrap; gap: 12px; justify-content: center;">
                                    <t t-if="partner.whatsapp_url">
                                        <a t-att-href="partner.whatsapp_url if partner.whatsapp_url.startswith('http') else 'https://' + partner.whatsapp_url" 
                                           target="_blank" 
                                           title="WhatsApp"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-whatsapp" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.linkedin_url">
                                        <a t-att-href="partner.linkedin_url if partner.linkedin_url.startswith('http') else 'https://' + partner.linkedin_url" 
                                           target="_blank" 
                                           title="LinkedIn"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-linkedin" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.linkedin_url_company">
                                        <a t-att-href="partner.linkedin_url_company if partner.linkedin_url_company.startswith('http') else 'https://' + partner.linkedin_url_company" 
                                           target="_blank" 
                                           title="Company LinkedIn"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-linkedin" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.youtube_url">
                                        <a t-att-href="partner.youtube_url if partner.youtube_url.startswith('http') else 'https://' + partner.youtube_url" 
                                           target="_blank" 
                                           title="YouTube"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-youtube" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.facebook_url">
                                        <a t-att-href="partner.facebook_url if partner.facebook_url.startswith('http') else 'https://' + partner.facebook_url" 
                                           target="_blank" 
                                           title="Facebook"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-facebook" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.facebook_url_company">
                                        <a t-att-href="partner.facebook_url_company if partner.facebook_url_company.startswith('http') else 'https://' + partner.facebook_url_company" 
                                           target="_blank" 
                                           title="Company Facebook"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-facebook" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.telegram_url">
                                        <a t-att-href="partner.telegram_url if partner.telegram_url.startswith('http') else 'https://' + partner.telegram_url" 
                                           target="_blank" 
                                           title="Telegram"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-telegram" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.instagram_url">
                                        <a t-att-href="partner.instagram_url if partner.instagram_url.startswith('http') else 'https://' + partner.instagram_url" 
                                           target="_blank" 
                                           title="Instagram"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-instagram" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.instagram_url_company">
                                        <a t-att-href="partner.instagram_url_company if partner.instagram_url_company.startswith('http') else 'https://' + partner.instagram_url_company" 
                                           target="_blank" 
                                           title="Company Instagram"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-instagram" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.twitter_url">
                                        <a t-att-href="partner.twitter_url if partner.twitter_url.startswith('http') else 'https://' + partner.twitter_url" 
                                           target="_blank" 
                                           title="Twitter"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-twitter" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.twitter_url_company">
                                        <a t-att-href="partner.twitter_url_company if partner.twitter_url_company.startswith('http') else 'https://' + partner.twitter_url_company" 
                                           target="_blank" 
                                           title="Company Twitter"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-twitter" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.github_url">
                                        <a t-att-href="partner.github_url if partner.github_url.startswith('http') else 'https://' + partner.github_url" 
                                           target="_blank" 
                                           title="GitHub"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-github" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.tumblr_url">
                                        <a t-att-href="partner.tumblr_url if partner.tumblr_url.startswith('http') else 'https://' + partner.tumblr_url" 
                                           target="_blank" 
                                           title="Tumblr"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-tumblr" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.xing_url">
                                        <a t-att-href="partner.xing_url if partner.xing_url.startswith('http') else 'https://' + partner.xing_url" 
                                           target="_blank" 
                                           title="Xing"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-xing" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.vimeo_url">
                                        <a t-att-href="partner.vimeo_url if partner.vimeo_url.startswith('http') else 'https://' + partner.vimeo_url" 
                                           target="_blank" 
                                           title="Vimeo"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-vimeo" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.pinterest_url">
                                        <a t-att-href="partner.pinterest_url if partner.pinterest_url.startswith('http') else 'https://' + partner.pinterest_url" 
                                           target="_blank" 
                                           title="Pinterest"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-pinterest" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.skype_url">
                                        <a t-att-href="partner.skype_url if partner.skype_url.startswith('http') else 'https://' + partner.skype_url" 
                                           target="_blank" 
                                           title="Skype"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-skype" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.dribbble_url">
                                        <a t-att-href="partner.dribbble_url if partner.dribbble_url.startswith('http') else 'https://' + partner.dribbble_url" 
                                           target="_blank" 
                                           title="Dribbble"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-dribbble" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.messenger_url">
                                        <a t-att-href="partner.messenger_url if partner.messenger_url.startswith('http') else 'https://' + partner.messenger_url" 
                                           target="_blank" 
                                           title="Messenger"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-facebook-messenger" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.doordash_url">
                                        <a t-att-href="partner.doordash_url if partner.doordash_url.startswith('http') else 'https://' + partner.doordash_url" 
                                           target="_blank" 
                                           title="DoorDash"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fas fa-utensils" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.tripadvisor_url">
                                        <a t-att-href="partner.tripadvisor_url if partner.tripadvisor_url.startswith('http') else 'https://' + partner.tripadvisor_url" 
                                           target="_blank" 
                                           title="TripAdvisor"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-tripadvisor" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.yelp_url">
                                        <a t-att-href="partner.yelp_url if partner.yelp_url.startswith('http') else 'https://' + partner.yelp_url" 
                                           target="_blank" 
                                           title="Yelp"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-yelp" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.google_reviews_url">
                                        <a t-att-href="partner.google_reviews_url if partner.google_reviews_url.startswith('http') else 'https://' + partner.google_reviews_url" 
                                           target="_blank" 
                                           title="Google Reviews"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-google" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.ubereats_url">
                                        <a t-att-href="partner.ubereats_url if partner.ubereats_url.startswith('http') else 'https://' + partner.ubereats_url" 
                                           target="_blank" 
                                           title="UberEats"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fas fa-utensils" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.line_url">
                                        <a t-att-href="partner.line_url if partner.line_url.startswith('http') else 'https://' + partner.line_url" 
                                           target="_blank" 
                                           title="Line"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-line" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.vkontakte_url">
                                        <a t-att-href="partner.vkontakte_url if partner.vkontakte_url.startswith('http') else 'https://' + partner.vkontakte_url" 
                                           target="_blank" 
                                           title="VKontakte"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-vk" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.reddit_url">
                                        <a t-att-href="partner.reddit_url if partner.reddit_url.startswith('http') else 'https://' + partner.reddit_url" 
                                           target="_blank" 
                                           title="Reddit"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-reddit" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.viber_url">
                                        <a t-att-href="partner.viber_url if partner.viber_url.startswith('http') else 'https://' + partner.viber_url" 
                                           target="_blank" 
                                           title="Viber"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-viber" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.pinterest_url">
                                        <a t-att-href="partner.pinterest_url if partner.pinterest_url.startswith('http') else 'https://' + partner.pinterest_url" 
                                           target="_blank" 
                                           title="Pinterest"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-pinterest" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.tiktok_url">
                                        <a t-att-href="partner.tiktok_url if partner.tiktok_url.startswith('http') else 'https://' + partner.tiktok_url" 
                                           target="_blank" 
                                           title="TikTok"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-tiktok" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.snapchat_url">
                                        <a t-att-href="partner.snapchat_url if partner.snapchat_url.startswith('http') else 'https://' + partner.snapchat_url" 
                                           target="_blank" 
                                           title="Snapchat"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-snapchat" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                    <t t-if="partner.signal_url">
                                        <a t-att-href="partner.signal_url if partner.signal_url.startswith('http') else 'https://' + partner.signal_url" 
                                           target="_blank" 
                                           title="Signal"
                                           class="minimal-social-icon"
                                           t-att-data-color="partner.secondary_color or '#2563eb'"
                                           style="width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; border: 1px solid #e5e7eb; border-radius: 6px; text-decoration: none; color: #6b7280; transition: all 0.2s;">
                                            <i class="fab fa-signal" style="font-size: 20px;"></i>
                                        </a>
                                    </t>
                                </div>
                            </div>
                            
                            <!-- About Tab -->
                            <div class="minimal-tab-content" data-content="about" t-att-style="'display: none; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div t-if="partner.about" style="text-align: left; color: #374151; line-height: 1.6; font-size: 0.875rem;">
                                    <t t-out="partner.about"/>
                                </div>
                                <div t-if="not partner.about and partner.function" style="text-align: left; color: #374151; line-height: 1.6; font-size: 0.875rem;">
                                    <t t-esc="partner.function"/>
                                </div>
                            </div>
                            
                            <!-- Services Tab -->
                            <div class="minimal-tab-content" data-content="services" t-att-style="'display: none; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div style="text-align: left;">
                                    <t t-foreach="partner.service_ids" t-as="service">
                                        <div style="margin-bottom: 24px; padding-bottom: 24px; border-bottom: 1px solid #e5e7eb;">
                                            <h3 style="margin: 0 0 8px 0; font-size: 1rem; font-weight: 600; color: #111827;">
                                                <t t-esc="service.name"/>
                                            </h3>
                                            <div t-if="service.description" style="margin: 0 0 12px 0; color: #6b7280; font-size: 0.875rem; line-height: 1.6;">
                                                <t t-esc="service.description"/>
                                            </div>
                                            <div style="display: flex; align-items: center; justify-content: space-between;">
                                                <t t-if="service.price">
                                                    <span t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-weight: 600; font-size: 1rem;'">
                                                        <t t-esc="service.price"/>
                                                    </span>
                                                </t>
                                                <a href="#" 
                                                   class="service-request-btn"
                                                   t-att-data-service-id="service.id"
                                                   t-att-data-service-name="service.name"
                                                   t-att-data-service-description="service.description or ''"
                                                   data-toggle="modal"
                                                   data-target="#serviceRequestModal"
                                                   t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 8px 16px; border-radius: 6px; font-size: 0.875rem; font-weight: 500; text-decoration: none; display: inline-block;'">
                                                    Request Service
                                                </a>
                                            </div>
                                        </div>
                                    </t>
                                </div>
                            </div>
                            
                            <!-- Reviews Tab - Vertical List -->
                            <div class="minimal-tab-content" data-content="reviews" t-att-style="'display: none; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div style="text-align: left;">
                                    <t t-set="review_count" t-value="0"/>
                                    <t t-foreach="partner.review_ids" t-as="review">
                                        <t t-if="review.is_published and review_count &lt; (partner.max_reviews_display or 5)">
                                            <t t-set="review_count" t-value="review_count + 1"/>
                                            <div style="margin-bottom: 24px; padding-bottom: 24px; border-bottom: 1px solid #e5e7eb;">
                                                <div style="margin-bottom: 8px; color: #fbbf24; font-size: 1rem;">
                                                    <t t-esc="review.stars_display"/>
                                                </div>
                                                <p style="margin: 0 0 8px 0; color: #374151; font-size: 0.875rem; line-height: 1.6;">
                                                    <t t-esc="review.review_text"/>
                                                </p>
                                                <p style="margin: 0; color: #6b7280; font-size: 0.75rem; font-weight: 500;">
                                                    - <t t-esc="review.reviewer_name"/>
                                                </p>
                                            </div>
                                        </t>
                                    </t>
                                    <div style="margin-top: 24px; text-align: center;">
                                        <a href="#" 
                                           data-toggle="modal" 
                                           data-target="#reviewModal"
                                           t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 10px 20px; border-radius: 6px; font-size: 0.875rem; font-weight: 500; text-decoration: none; display: inline-block;'">
                                            Leave a Review
                                        </a>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Specialities Tab -->
                            <div class="minimal-tab-content" data-content="specialities" t-att-style="'display: none; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                                    <t t-foreach="partner.speciality_ids" t-as="speciality">
                                        <span t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '20; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 6px 12px; border-radius: 20px; font-size: 0.875rem; font-weight: 500; display: inline-block;'">
                                            <t t-esc="speciality.name"/>
                                        </span>
                                    </t>
                                </div>
                            </div>
                            
                            <!-- Websites Tab -->
                            <div class="minimal-tab-content" data-content="websites" t-att-style="'display: none; padding: 24px 16px; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <div style="display: flex; flex-direction: column; gap: 12px;">
                                    <t t-foreach="partner.website_ids" t-as="partner_website">
                                        <a t-att-href="'http://' + partner_website.website_url if not (partner_website.website_url.startswith('http://') or partner_website.website_url.startswith('https://')) else partner_website.website_url"
                                           target="_blank"
                                           t-att-style="'background-color: ' + (partner_website.button_color or partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 6px; font-size: 0.875rem; font-weight: 500; text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 8px;'">
                                            <t t-if="partner_website.button_logo">
                                                <img t-att-src="'/website/image/partner.vcard.website/' + str(partner_website.id) + '/button_logo'"
                                                     alt="Logo" 
                                                     style="max-height: 24px; max-width: 24px;"/>
                                            </t>
                                            <t t-esc="partner_website.name or partner_website.website_url"/>
                                        </a>
                                    </t>
                                </div>
                            </div>
                            
                            <!-- Calendar Tab -->
                            <t t-if="partner.calendly_url">
                                <div class="minimal-tab-content" data-content="calendar" t-att-style="'display: none; padding: 0; height: 600px; overflow: hidden; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                    <div class="calendly-inline-widget"
                                         t-att-data-url="partner.calendly_url"
                                         style="min-width: 100%; height: 100%; overflow: hidden;"></div>
                                </div>
                            </t>
                            
                            <!-- QR Code Tab -->
                            <div class="minimal-tab-content" data-content="qrcode" t-att-style="'display: none; padding: 24px 16px; text-align: center; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                                <p style="margin: 0 0 16px 0; color: #6b7280; font-size: 0.875rem;">
                                    Scan to save or share this card
                                </p>
                                <div style="margin-bottom: 0;">
                                    <img t-att-src="'/vcard/qr_code/download/' + str(partner.id)" 
                                         alt="QR Code" 
                                         style="max-width: 200px; height: auto; border: 1px solid #e5e7eb; border-radius: 6px; padding: 8px; background: white;"/>
                                </div>
                            </div>
                            
                        </div>
                        
                        <!-- Lead Modal -->
                        <div class="modal fade" id="leadModal" tabindex="-1" role="dialog" aria-labelledby="leadModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true" data-dismiss-on-backdrop="true">
                          <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
                            <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                              <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                                <div style="display: flex; align-items: center; width: 100%;">
                                  <div style="flex: 1;">
                                    <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="leadModalLabel">Fill in your details</h5>
                                  </div>
                                  <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                                    <span aria-hidden="true">×</span>
                                </button>
                              </div>
                              </div>
                              <div class="modal-body" style="padding: 16px 24px 24px 24px;">
                                <div id="successMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                                  <i class="fa fa-check-circle me-2"></i>Thank you! I look forward to talking with you soon.
                                </div>
                        <form id="leadForm">
                            <div class="form-group">
                                <input type="hidden" class="form-control" id="partnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                                <input type="hidden" id="leadTagIds" name="lead_tag_ids" t-att-value="','.join(map(str, partner.lead_tag_ids.ids))"/>
                                <input type="hidden" id="formThankYouMessage" t-att-value="partner.form_thank_you_message or 'Thank you! I look forward to talking with you soon.'"/>
                            </div>
                            <div class="form-group">
                                <label for="fullName">Full name <span class="text-danger">*</span></label>
                                <input type="text" class="form-control" id="fullName" name="full_name" required="required" placeholder="Your name"/>
                            </div>
                            <div class="form-group">
                                <label for="email">Email <span class="text-danger">*</span></label>
                                <input type="email" class="form-control" id="email" name="email" required="required" placeholder="you@example.com"/>
                            </div>
                            <div class="form-group">
                                <label for="phone">Phone</label>
                                <input type="tel" class="form-control" id="phone" name="phone" placeholder="Your phone number"/>
                                <input type="hidden" id="phone_full" name="phone_full"/>
                            </div>
                            <style>
                                #leadModal .form-group {{ position: relative; margin-bottom: 14px; }}
                                #leadModal .form-group label {{ display: block !important; margin-bottom: 4px; font-weight: 500; color: #374151; }}
                                #leadModal .form-group .form-control,
                                #leadModal .form-group input.form-control {{ display: block; width: 100%; height: 40px; box-sizing: border-box; }}
                                #leadModal textarea.form-control {{ height: auto; min-height: 80px; }}
                                #leadModal .iti {{ display: block !important; width: 100%; }}
                                #leadModal .iti__flag-container {{ position: absolute; top: 0; bottom: 0; right: auto; left: 0; z-index: 2; }}
                                #leadModal .iti__selected-flag {{ z-index: 4; position: relative; display: flex; align-items: center; height: 100%; padding: 0 10px 0 12px; background-color: #f8f9fa; border-right: 1px solid #dee2e6; border-radius: 4px 0 0 4px; cursor: pointer; min-width: 76px; }}
                                #leadModal .iti__flag-box {{ margin-right: 6px; }}
                                #leadModal .iti__arrow {{ margin-left: 6px; width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 4px solid #555; }}
                                #leadModal .iti__selected-dial-code {{ margin-left: 2px; font-size: 14px; color: #374151; }}
                                #leadModal #phone {{ padding-left: 88px !important; }}
                                #leadModal .iti__country-list {{ z-index: 9999 !important; }}
                                #leadModal .intl-tel-input .iti__country-list {{ z-index: 9999 !important; }}
                            </style>
                            <div class="form-group">
                                <label for="notes">Notes</label>
                                <textarea class="form-control" id="notes" name="notes" placeholder="Anything else you'd like to share (optional)"></textarea>
                            </div>
                        </form>
                              </div>
                              <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; flex-direction: column; gap: 12px;">
                                <button type="button" id="submitLeadBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 12px 24px; border-radius: 8px; width: 100%;'">
                                  Share My Contact
                                </button>
                                <small style="text-align: center; color: #6b7280; font-size: 12px; margin: 0;"><t t-set="vinc_label">* By clicking the 'Share My Contact' button, I agree to be contacted by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                              </div>
                            </div>
                          </div>
                        </div>

                        <!-- Review Modal -->
                        <div class="modal fade" id="reviewModal" tabindex="-1" role="dialog" aria-labelledby="reviewModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
                          <div class="modal-dialog" role="document">
                            <div class="modal-content">
                              <div class="modal-header">
                               <h5 class="modal-title" style="text-align: center;" id="reviewModalLabel">Leave a Review</h5>
                                <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                                  <span aria-hidden="true">×</span>
                                </button>
                              </div>
                              <div class="modal-body">
                                <div id="reviewSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                                  <i class="fa fa-check-circle me-2"></i>Thank you for your review! We appreciate your feedback.
                                </div>
                        <form id="reviewForm" onsubmit="return false;">
                            <div class="form-group">
                                <input type="hidden" class="form-control" id="reviewPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                                <input type="hidden" id="reviewThankYouMessage" t-att-value="partner.review_thank_you_message or 'Thank you for your review! We appreciate your feedback.'"/>
                            </div>
                            <div class="form-group">
                                <label for="reviewerName">Your Name<span class="text-danger">*</span></label>
                                <input type="text" class="form-control" id="reviewerName" name="reviewer_name" required="required"/>
                            </div>
                            <div class="form-group">
                                <label for="reviewRating">Rating<span class="text-danger">*</span></label>
                                <div class="star-rating" style="font-size: 32px; color: #ffc107; cursor: pointer;">
                                    <span class="star" data-rating="1">☆</span>
                                    <span class="star" data-rating="2">☆</span>
                                    <span class="star" data-rating="3">☆</span>
                                    <span class="star" data-rating="4">☆</span>
                                    <span class="star" data-rating="5">☆</span>
                                </div>
                                <input type="hidden" id="reviewRating" name="rating" value="5" required="required"/>
                            </div>
                            <div class="form-group">
                                <label for="reviewText">Your Review<span class="text-danger">*</span></label>
                                <textarea class="form-control" id="reviewText" name="review_text" rows="4" required="required"></textarea>
                            </div>
                            <div class="text-center" style="padding-top: 5px;">
                                <button type="button" id="submitReviewBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%; text-decoration: none; display: inline-block; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                                        onmouseover="this.style.transform='scale(0.95)'"
                                        onmouseout="this.style.transform='scale(1)'">Submit Review</button>
                            </div>
                        </form>
                              </div>
                             <div class="modal-footer" style="justify-content: center !important; padding: 0;">
                            <small><t t-set="vinc_label">* Your review will be visible once approved by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/> </small>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                        <!-- Service Request Modal -->
                        <div class="modal fade" id="serviceRequestModal" tabindex="-1" role="dialog" aria-labelledby="serviceRequestModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
                          <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
                            <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                              <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                                <div style="display: flex; align-items: center; width: 100%;">
                                  <div style="flex: 1;">
                                    <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="serviceRequestModalLabel">
                                      Request Service
                                    </h5>
                                  </div>
                                  <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                                    <span aria-hidden="true">×</span>
                                  </button>
                                </div>
                              </div>
                              <div class="modal-body" style="padding: 16px 24px 24px 24px;">
                                <div id="serviceRequestSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                                  <i class="fa fa-check-circle me-2"></i>Thank you! Your service request has been sent. We'll be in touch shortly.
                                </div>
                                <form id="serviceRequestForm">
                                  <div class="form-group">
                                    <input type="hidden" class="form-control" id="serviceRequestPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                                    <input type="hidden" id="serviceRequestServiceId" name="service_id" value=""/>
                                    <input type="hidden" id="serviceRequestServiceName" name="service_name" value=""/>
                                    <input type="hidden" id="serviceRequestServiceDescription" name="service_description" value=""/>
                                  </div>
                                  <div class="form-group" style="margin-bottom: 20px;">
                                    <label style="margin-bottom: 8px; font-weight: 600; color: #111827;"><strong>Service:</strong></label>
                                    <p id="serviceRequestServiceDisplay" t-att-style="'margin: 0; padding: 12px; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #e5e7eb; border-radius: 8px; color: #111827; font-weight: 600; font-size: 16px;'"></p>
                                  </div>
                                  <div class="form-group">
                                    <label for="serviceRequestFullName">Full name<span class="text-danger">*</span></label>
                                    <input type="text" class="form-control" id="serviceRequestFullName" name="full_name" required="required"/>
                                  </div>
                                  <div class="form-group">
                                    <label for="serviceRequestEmail">Email<span class="text-danger">*</span></label>
                                    <input type="email" class="form-control" id="serviceRequestEmail" name="email" required="required"/>
                                  </div>
                                  <div class="form-group">
                                    <label for="serviceRequestPhone">Phone</label>
                                    <input type="tel" class="form-control" id="serviceRequestPhone" name="phone" placeholder="Your Phone"/>
                                    <input type="hidden" id="serviceRequestPhoneFull" name="phone_full"/>
                                  </div>
                                  <style>
                                    #serviceRequestModal .form-group {{ position: relative; }}
                                    #serviceRequestModal .iti {{ width: 100%; display: block; }}
                                    #serviceRequestModal .iti__flag-container {{ position: absolute; top: 0; bottom: 0; right: auto; left: 0; z-index: 2; }}
                                    #serviceRequestModal .iti__selected-flag {{ z-index: 4; position: relative; display: flex; align-items: center; height: 100%; padding: 0 10px 0 8px; background-color: #f8f9fa; border-right: 1px solid #dee2e6; cursor: pointer; min-width: 70px; }}
                                    #serviceRequestModal #serviceRequestPhone {{ padding-left: 80px !important; }}
                                    /* Fix z-index for country dropdown to appear above modal */
                                    #serviceRequestModal .iti__country-list {{ z-index: 9999 !important; }}
                                    #serviceRequestModal .intl-tel-input .iti__country-list {{ z-index: 9999 !important; }}
                                  </style>
                                  <div id="serviceRequestCustomQuestions"></div>
                                  <div class="form-group">
                                    <label for="serviceRequestNotes">Additional Details</label>
                                    <textarea class="form-control" id="serviceRequestNotes" name="notes" rows="4" placeholder="Add any additional information or requirements..."></textarea>
                                  </div>
                                  <div class="text-center" style="padding-top: 10px;">
                                    <button type="button" id="submitServiceRequestBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%;'">Send Request</button>
                                  </div>
                                </form>
                              </div>
                              <div class="modal-footer" style="border-top: none; padding: 0 24px 24px 24px; text-align: center;">
                                <small style="color: #6b7280; font-size: 12px;"><t t-set="vinc_label">* By clicking 'Send Request', I agree to be contacted by %(name)s regarding this service</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                              </div>
                            </div>
                          </div>
                        </div>
                        
                        <!-- Scripts -->
                        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/css/intlTelInput.css"/>
                        <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
                        <script type="text/javascript" src="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/js/bootstrap.min.js"></script>
                        <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/js/intlTelInput.min.js"></script>
                        <script type="text/javascript" t-attf-src="/qr_code_odoo/static/src/js/widget.js"></script>
                        
                        <!-- Tab Navigation Script -->
                        <script>
                        $(document).ready(function() {{
                            var secondaryColor = '<t t-esc="partner.secondary_color or '#2563eb'"/>';
                            
                            // Tab navigation
                            $('.minimal-tab-btn').on('click', function() {{
                                var tabName = $(this).data('tab');
                                
                                // Remove active class from all buttons
                                $('.minimal-tab-btn').removeClass('active');
                                $('.minimal-tab-btn').css({{
                                    'color': '#6b7280',
                                    'border-bottom': '2px solid transparent'
                                }});
                                
                                // Add active class to clicked button
                                $(this).addClass('active');
                                $(this).css({{
                                    'color': secondaryColor,
                                    'border-bottom': '2px solid ' + secondaryColor
                                }});
                                
                                // Hide all tab contents
                                $('.minimal-tab-content').hide();
                                
                                // Show selected tab content
                                $('.minimal-tab-content[data-content="' + tabName + '"]').show();
                            }});
                            
                            // Social icon hover effects
                            $('.minimal-social-icon').on('mouseenter', function() {{
                                var color = $(this).data('color') || '#2563eb';
                                $(this).css({{
                                    'border-color': color,
                                    'color': color
                                }});
                            }}).on('mouseleave', function() {{
                                $(this).css({{
                                    'border-color': '#e5e7eb',
                                    'color': '#6b7280'
                                }});
                            }});
                            
                            // Auto-show lead form feature
                            var wrapDiv = document.getElementById('wrap');
                            if (wrapDiv) {{
                                var autoShowLead = wrapDiv.getAttribute('data-auto-show-lead');
                                if (autoShowLead === 'true') {{
                                    setTimeout(function() {{
                                        $('#leadModal').modal('show');
                                    }}, 500);
                                }}
                                
                                // Auto-download vCard feature
                                var autoDownloadVcard = wrapDiv.getAttribute('data-auto-download-vcard');
                                if (autoDownloadVcard === 'true') {{
                                    setTimeout(function() {{
                                        var downloadUrl = wrapDiv.getAttribute('data-vcard-download-url');
                                        if (downloadUrl) {{
                                            window.location.href = downloadUrl;
                                        }}
                                    }}, 800);
                                }}
                            }}
                        }});

                        </script>
                        
                        <!-- Calendly Widget Script -->
                        <t t-if="partner.calendly_url">
                            <script type="text/javascript"
                                    src="https://assets.calendly.com/assets/external/widget.js"></script>
                        </t>
                        
                        
                    </div>
                </div>
            </t>
        </t>
        """

    def _build_corporate_template(self, image_url, banner_url=None, referral_url=None):
        if referral_url is None:
            referral_url = self.get_referral_signup_url()
        """Build the corporate vCard template - React Corporate design.
        
        Structure:
        - Banner at top
        - Profile image inline with name, title, company, and QR code button
        - Action buttons (Call, Email, Fill in your info, Download my info)
        - About, Services, Specialties, Reviews, Video, Websites sections
        """
        return f"""
        <t t-name="website.{self.website_slug}">
            <t t-set="partner" t-value="request.env['partner.vcard'].sudo().browse({self.id})"/>
    
            <!-- Dashboard Button (visible to logged-in internal users) -->
            <t t-if="not request.env.user._is_public()">
                <style>
                    @media only screen and (max-width: 600px) {{
                        .dashboard-btn-container {{
                            top: 10px !important;
                            right: 10px !important;
                        }}
                        .dashboard-btn-container a {{
                            padding: 10px 16px !important;
                            font-size: 12px !important;
                        }}
                        .dashboard-btn-container .fa {{
                            font-size: 14px !important;
                        }}
                    }}
                </style>
                <div class="dashboard-btn-container" style="position: fixed; top: 20px; right: 20px; z-index: 9999;">
                    <a href="/web#action=qr_code_odoo.action_user_dashboard" 
                       style="display: inline-flex; align-items: center; gap: 8px; padding: 12px 20px; background: rgba(69, 126, 184, 0.9); color: white; text-decoration: none; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 14px; font-weight: 500; transition: all 0.3s ease; z-index: 9999;"
                       onmouseover="this.style.background='rgba(69, 126, 184, 1)'; this.style.transform='translateY(-2px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';"
                       onmouseout="this.style.background='rgba(69, 126, 184, 0.9)'; this.style.transform='translateY(0)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.2)';">
                        <i class="fa fa-dashboard" style="font-size: 16px;"></i>
                        <span>Back to Dashboard</span>
                    </a>
                </div>
            </t>
    
            <!-- Use custom vCard layout without header and footer -->
            <t t-call="qr_code_odoo.vcard_layout">
                <!-- Main content -->
                <div id="wrap" class="oe_structure oe_empty vcard-template-corporate"
                     t-att-style="partner.primary_color and 'background-color: ' + partner.primary_color or ''"
                     t-att-data-auto-show-lead="str(partner.auto_show_lead_form and partner.show_form and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-auto-download-vcard="str(partner.auto_download_vcard and (request.env.user._is_public() or request.env.user.share)).lower()"
                     t-att-data-vcard-download-url="'/website/vcard/download/' + str(partner.id)"
                     style="text-align: left; font-family: 'Poppins', sans-serif; padding-top: 0;">

                
                <!-- Responsive container -->
                <div class="container-fluid" style="max-width: 1000px; margin: 0 auto; padding: 0; overflow: visible;">

            <!-- Corporate Template Banner -->
            <div class="banner-container" style="position: relative; width: 100%; height: 200px; margin-bottom: 0; z-index: 1; overflow: hidden;">
                <t t-if="partner.banner_attachment_id">
                    <div class="banner-image-wrapper" style="width: 100%; height: 100%; overflow: hidden; background-color: #ffffff; position: relative; padding: 18px 28px; box-sizing: border-box;">
                        <img t-att-src="'/website/image/ir.attachment/' + str(partner.banner_attachment_id.id) + '/datas'"
                             alt="" 
                             style="width: 100%; height: 100%; object-fit: contain; display: block;"
                             onerror="this.style.display='none';"/>
                    </div>
                </t>
                <t t-if="not partner.banner_attachment_id">
                    <div class="banner-image-wrapper" 
                         t-att-style="'width: 100%; height: 100%; background-color: ' + (partner.primary_color or '#667eea') + '; position: relative;'">
                    </div>
                </t>
            </div>

            <!-- Profile Header Section (Image inline with name, title, company, QR button) -->
            <section class="s_cover o_colored_level s_parallax_no_overflow_hidden o_cc o_cc3"
                     t-att-style="'padding: 24px 16px; position: relative; z-index: 2; background: ' + (partner.primary_color or '#ffffff') + '; min-height: auto; overflow: visible;'">
                <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                    <div style="display: flex; align-items: flex-start; gap: 24px; flex-wrap: wrap;">
                        <!-- Profile Picture -->
                        <div style="flex-shrink: 0;">
                            <t t-if="partner.attachment_id">
                                <img t-att-src="'/website/image/ir.attachment/' + str(partner.attachment_id.id) + '/datas'"
                                     alt=""
                                     class="img img-fluid"
                                     t-att-style="'width: 120px; height: 120px; object-fit: cover; border-radius: 8px; border: 2px solid #e5e7eb; background-color: ' + (partner.primary_color or '#ffffff') + '; display: block;'"
                                     loading="lazy"/>
                            </t>
                        </div>
                        
                        <!-- Name, Title, Company Info -->
                        <div style="flex: 1; min-width: 200px;">
                            <!-- Partner Name -->
                            <h1 style="margin: 0 0 8px 0; font-size: 1.875rem; font-weight: bold; color: #1e293b;">
                                <t t-esc="partner.name"/>
                            </h1>
                            
                            <!-- Job Title -->
                            <div t-if="partner.function" style="margin-bottom: 8px;">
                                <p style="font-size: 1rem; color: #64748b; font-weight: 500; margin: 0;">
                                    <t t-esc="partner.function"/>
                                </p>
                            </div>
                            
                            <!-- Company Name -->
                            <div t-if="partner.company_name" style="margin-bottom: 12px;">
                                <p t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 1rem; font-weight: 500; margin: 0;'">
                                    <t t-esc="partner.company_name"/>
                                </p>
                            </div>
                            
                            <!-- Phone and Email Section (Inline) -->
                            <div style="display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-bottom: 0;">
                                <t t-if="partner.phone">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <i class="fa fa-phone" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 14px;'"></i>
                                        <a t-att-href="'tel:' + partner.phone" t-att-style="'color: #64748b; text-decoration: none; font-size: 0.875rem;'">
                                            <t t-esc="partner.phone"/>
                                        </a>
                                    </div>
                                </t>
                                <t t-if="partner.mobile">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <i class="fa fa-mobile" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 14px;'"></i>
                                        <a t-att-href="'tel:' + partner.mobile" t-att-style="'color: #64748b; text-decoration: none; font-size: 0.875rem;'">
                                            <t t-esc="partner.mobile"/>
                                        </a>
                                    </div>
                                </t>
                                <t t-if="partner.email">
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <i class="fa fa-envelope" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 14px;'"></i>
                                        <a t-att-href="'mailto:' + partner.email" t-att-style="'color: #64748b; text-decoration: none; font-size: 0.875rem;'">
                                            <t t-esc="partner.email"/>
                                        </a>
                                    </div>
                                </t>
                            </div>
                        </div>
                        
                        <!-- QR Code / Download Button -->
                        <div style="flex-shrink: 0; margin-left: auto;">
                            <a href="#" 
                               data-toggle="modal" 
                               data-target="#qrCodeModal"
                               t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px 20px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 2px 8px rgba(0,0,0,0.1); transition: transform 0.1s; display: inline-flex; align-items: center; justify-content: center; gap: 8px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fa fa-qrcode" style="font-size: 18px;"></i>
                                <span>QR Code</span>
                            </a>
                        </div>
                    </div>
                </div>
            </section>

            <!-- Action Buttons Section (Call, Email, Fill in your info, Download my info) -->
            <section class="s_text_block o_colored_level pt0 pb0"
                     t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px;">
                        <!-- Call Button -->
                        <a t-if="partner.phone"
                           t-att-href="'tel:' + partner.phone"
                           t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; border: 2px solid ' + (partner.secondary_color or '#2563eb') + ';'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'">
                            <i class="fa fa-phone" style="font-size: 24px;"></i>
                            <span>CALL</span>
                        </a>
                        
                        <!-- Email Button -->
                        <a t-if="partner.email"
                           t-att-href="'mailto:' + partner.email"
                           t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; color: ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; cursor: pointer;'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'"
                           onclick="window.open(this.getAttribute('href'), '_self'); return false;">
                            <i class="fa fa-envelope" style="font-size: 24px;"></i>
                            <span>EMAIL</span>
                        </a>
                        
                        <!-- Fill in your info Button -->
                        <t t-if="partner.show_form">
                            <a href="#" 
                               data-toggle="modal" 
                               data-target="#leadModal"
                               t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fa fa-paper-plane" style="font-size: 24px;"></i>
                                <span><t t-if="partner.lead_button_label" t-esc="partner.lead_button_label"/><t t-else="">INQUIRE</t></span>
                            </a>
                        </t>
                        
                        <!-- Download my info Button -->
                        <a t-att-href="'/website/vcard/download/' + str(partner.id)"
                           t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;'"
                           onmouseover="this.style.transform='scale(0.95)'"
                           onmouseout="this.style.transform='scale(1)'">
                            <i class="fa fa-download" style="font-size: 24px;"></i>
                            <span><t t-set="vinc_label">Get %(name)s's Info</t><t t-out="vinc_label % {{'name': partner.name.split(' ')[0] if partner.name else ''}}"/></span>
                        </a>
                    </div>
                </div>
            </section>
            
            <!-- About Section -->
            <section class="s_text_block o_colored_level pt0 pb0"
                     t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 0;'">
                <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                    <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 16px; text-align: left; text-transform: uppercase; font-size: 0.875rem; letter-spacing: 0.05em;'">About</h4>
                    <div t-if="partner.about" style="text-align: left; margin-bottom: 0;">
                        <p t-att-style="'color: #64748b; line-height: 1.6; margin: 0;'">
                            <t t-out="partner.about"/>
                        </p>
                    </div>
                    <div t-if="not partner.about and partner.function" style="text-align: left; margin-bottom: 0;">
                        <p t-att-style="'color: #64748b; line-height: 1.6; margin: 0;'">
                            <t t-esc="partner.function"/>
                        </p>
                    </div>
                </div>
            </section>
            
            <!-- Social Media Section -->
            <t t-if="partner.has_socials">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 0;'">
                    <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                        <div class="s_social_media o_not_editable text-center"
                             style="display: flex; justify-content: center; flex-wrap: wrap; gap: 15px; padding: 0;">
                            
                            <!-- WhatsApp -->
                            <a t-if="partner.whatsapp_url" t-att-href="partner.whatsapp_url if partner.whatsapp_url.startswith('http') else 'https://' + partner.whatsapp_url" target="_blank" title="WhatsApp" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-whatsapp" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- LinkedIn -->
                            <a t-if="partner.linkedin_url" t-att-href="partner.linkedin_url if partner.linkedin_url.startswith('http') else 'https://' + partner.linkedin_url" target="_blank" title="LinkedIn" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-linkedin" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- LinkedIn Company -->
                            <a t-if="partner.linkedin_url_company" t-att-href="partner.linkedin_url_company if partner.linkedin_url_company.startswith('http') else 'https://' + partner.linkedin_url_company" target="_blank" title="Company LinkedIn" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-linkedin" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- YouTube -->
                            <a t-if="partner.youtube_url" t-att-href="partner.youtube_url if partner.youtube_url.startswith('http') else 'https://' + partner.youtube_url" target="_blank" title="YouTube" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-youtube" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Facebook -->
                            <a t-if="partner.facebook_url" t-att-href="partner.facebook_url if partner.facebook_url.startswith('http') else 'https://' + partner.facebook_url" target="_blank" title="Facebook" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-facebook" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Facebook Company -->
                            <a t-if="partner.facebook_url_company" t-att-href="partner.facebook_url_company if partner.facebook_url_company.startswith('http') else 'https://' + partner.facebook_url_company" target="_blank" title="Company Facebook" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-facebook" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Telegram -->
                            <a t-if="partner.telegram_url" t-att-href="partner.telegram_url if partner.telegram_url.startswith('http') else 'https://' + partner.telegram_url" target="_blank" title="Telegram" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-telegram" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Instagram -->
                            <a t-if="partner.instagram_url" t-att-href="partner.instagram_url if partner.instagram_url.startswith('http') else 'https://' + partner.instagram_url" target="_blank" title="Instagram" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-instagram" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Instagram Company -->
                            <a t-if="partner.instagram_url_company" t-att-href="partner.instagram_url_company if partner.instagram_url_company.startswith('http') else 'https://' + partner.instagram_url_company" target="_blank" title="Company Instagram" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-instagram" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Twitter -->
                            <a t-if="partner.twitter_url" t-att-href="partner.twitter_url if partner.twitter_url.startswith('http') else 'https://' + partner.twitter_url" target="_blank" title="Twitter" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-twitter" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Twitter Company -->
                            <a t-if="partner.twitter_url_company" t-att-href="partner.twitter_url_company if partner.twitter_url_company.startswith('http') else 'https://' + partner.twitter_url_company" target="_blank" title="Company Twitter" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-twitter" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- GitHub -->
                            <a t-if="partner.github_url" t-att-href="partner.github_url if partner.github_url.startswith('http') else 'https://' + partner.github_url" target="_blank" title="GitHub" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-github" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Tumblr -->
                            <a t-if="partner.tumblr_url" t-att-href="partner.tumblr_url if partner.tumblr_url.startswith('http') else 'https://' + partner.tumblr_url" target="_blank" title="Tumblr" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-tumblr" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Xing -->
                            <a t-if="partner.xing_url" t-att-href="partner.xing_url if partner.xing_url.startswith('http') else 'https://' + partner.xing_url" target="_blank" title="Xing" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-xing" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Vimeo -->
                            <a t-if="partner.vimeo_url" t-att-href="partner.vimeo_url if partner.vimeo_url.startswith('http') else 'https://' + partner.vimeo_url" target="_blank" title="Vimeo" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-vimeo" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Pinterest -->
                            <a t-if="partner.pinterest_url" t-att-href="partner.pinterest_url if partner.pinterest_url.startswith('http') else 'https://' + partner.pinterest_url" target="_blank" title="Pinterest" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-pinterest" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Skype -->
                            <a t-if="partner.skype_url" t-att-href="partner.skype_url if partner.skype_url.startswith('http') else 'https://' + partner.skype_url" target="_blank" title="Skype" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-skype" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Dribbble -->
                            <a t-if="partner.dribbble_url" t-att-href="partner.dribbble_url if partner.dribbble_url.startswith('http') else 'https://' + partner.dribbble_url" target="_blank" title="Dribbble" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-dribbble" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Messenger -->
                            <a t-if="partner.messenger_url" t-att-href="partner.messenger_url if partner.messenger_url.startswith('http') else 'https://' + partner.messenger_url" target="_blank" title="Messenger" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-facebook-messenger" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- DoorDash -->
                            <a t-if="partner.doordash_url" t-att-href="partner.doordash_url if partner.doordash_url.startswith('http') else 'https://' + partner.doordash_url" target="_blank" title="DoorDash" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fas fa-utensils" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- TripAdvisor -->
                            <a t-if="partner.tripadvisor_url" t-att-href="partner.tripadvisor_url if partner.tripadvisor_url.startswith('http') else 'https://' + partner.tripadvisor_url" target="_blank" title="TripAdvisor" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-tripadvisor" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Yelp -->
                            <a t-if="partner.yelp_url" t-att-href="partner.yelp_url if partner.yelp_url.startswith('http') else 'https://' + partner.yelp_url" target="_blank" title="Yelp" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-yelp" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Google Reviews -->
                            <a t-if="partner.google_reviews_url" t-att-href="partner.google_reviews_url if partner.google_reviews_url.startswith('http') else 'https://' + partner.google_reviews_url" target="_blank" title="Google Reviews" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-google" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- UberEats -->
                            <a t-if="partner.ubereats_url" t-att-href="partner.ubereats_url if partner.ubereats_url.startswith('http') else 'https://' + partner.ubereats_url" target="_blank" title="UberEats" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fas fa-utensils" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Line -->
                            <a t-if="partner.line_url" t-att-href="partner.line_url if partner.line_url.startswith('http') else 'https://' + partner.line_url" target="_blank" title="Line" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-line" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- VKontakte -->
                            <a t-if="partner.vkontakte_url" t-att-href="partner.vkontakte_url if partner.vkontakte_url.startswith('http') else 'https://' + partner.vkontakte_url" target="_blank" title="VKontakte" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-vk" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Reddit -->
                            <a t-if="partner.reddit_url" t-att-href="partner.reddit_url if partner.reddit_url.startswith('http') else 'https://' + partner.reddit_url" target="_blank" title="Reddit" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-reddit" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Viber -->
                            <a t-if="partner.viber_url" t-att-href="partner.viber_url if partner.viber_url.startswith('http') else 'https://' + partner.viber_url" target="_blank" title="Viber" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-viber" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- TikTok -->
                            <a t-if="partner.tiktok_url" t-att-href="partner.tiktok_url if partner.tiktok_url.startswith('http') else 'https://' + partner.tiktok_url" target="_blank" title="TikTok" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-tiktok" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Snapchat -->
                            <a t-if="partner.snapchat_url" t-att-href="partner.snapchat_url if partner.snapchat_url.startswith('http') else 'https://' + partner.snapchat_url" target="_blank" title="Snapchat" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-snapchat" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                            
                            <!-- Signal -->
                            <a t-if="partner.signal_url" t-att-href="partner.signal_url if partner.signal_url.startswith('http') else 'https://' + partner.signal_url" target="_blank" title="Signal" class="social-icon" t-att-style="'background-color: white; color: ' + (partner.secondary_color or '#2563eb') + '; border: 2px solid ' + (partner.secondary_color or '#2563eb') + '; padding: 12px; border-radius: 8px; font-weight: 600; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; width: 60px; height: 60px;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                <i class="fab fa-signal" t-att-style="'color: ' + (partner.secondary_color or '#2563eb') + '; font-size: 24px;'"></i>
                            </a>
                        </div>
                    </div>
                </section>
            </t>
            
            <!-- Services Section -->
            <t t-if="partner.service_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left; text-transform: uppercase; font-size: 0.875rem; letter-spacing: 0.05em;'">Services</h4>
                        <div class="services-container" style="display: flex; flex-direction: column; gap: 16px;">
                            <t t-foreach="partner.service_ids" t-as="service">
                                <div class="service-card" 
                                     t-att-style="'background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; text-align: left; box-shadow: 0 2px 4px rgba(0,0,0,0.05); width: 100%; box-sizing: border-box; overflow: hidden; display: flex; justify-content: space-between; align-items: center;'">
                                    <div style="flex: 1;">
                                        <h5 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0 0 8px 0; font-size: 18px; font-weight: 600; word-wrap: break-word;'">
                                            <t t-esc="service.name"/>
                                        </h5>
                                        <div t-att-style="'color: #666; margin: 0 0 12px 0; line-height: 1.6; word-wrap: break-word; overflow-wrap: break-word;'">
                                            <t t-esc="service.description"/>
                                        </div>
                                        <div t-if="service.show_pricing and service.price" style="flex: 0 0 auto;">
                                            <span t-att-style="'color: ' + (partner.secondary_color or '#000') + '; font-weight: 600; font-size: 16px;'">
                                                <t t-esc="service.price"/>
                                            </span>
                                        </div>
                                    </div>
                                    <a href="#" 
                                       class="btn service-request-btn" 
                                       t-att-data-service-id="service.id"
                                       t-att-data-service-name="service.name"
                                       t-att-data-service-description="service.description"
                                       t-att-style="'background-color: ' + (partner.secondary_color or '#007bff') + '; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: 600; text-decoration: none; display: inline-block; white-space: nowrap; flex: 0 0 auto; margin-left: 16px;'"
                                       data-toggle="modal" 
                                       data-target="#serviceRequestModal"
                                       onmouseover="this.style.transform='scale(0.95)'"
                                       onmouseout="this.style.transform='scale(1)'">
                                        Request
                                    </a>
                                </div>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Specialities Section -->
            <t t-if="partner.speciality_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left; text-transform: uppercase; font-size: 0.875rem; letter-spacing: 0.05em;'">Specialties</h4>
                        <div class="specialities-container" style="display: flex; flex-wrap: wrap; justify-content: flex-start; gap: 10px; max-width: 100%;">
                            <t t-foreach="partner.speciality_ids" t-as="speciality">
                                <span class="speciality-pill" 
                                      t-att-style="'background-color: ' + (partner.primary_color or '#f3f4f6') + '; color: #374151; padding: 8px 16px; border-radius: 20px; font-size: 14px; font-weight: 500; display: inline-block; margin: 5px; box-shadow: 0 1px 2px rgba(0,0,0,0.1);'">
                                    <t t-esc="speciality.name"/>
                                </span>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Reviews Section -->
            <t t-if="partner.show_reviews">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
                            <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0; text-align: left; text-transform: uppercase; font-size: 0.875rem; letter-spacing: 0.05em;'">
                                <t t-if="partner.reviews_section_title" t-esc="partner.reviews_section_title"/><t t-else="">Testimonials</t>
                            </h4>
                            <a href="#" 
                               data-toggle="modal" 
                               data-target="#reviewModal"
                               t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; padding: 6px 12px; border-radius: 6px; font-weight: 600; text-decoration: none; font-size: 0.875rem;'"
                               onmouseover="this.style.transform='scale(0.95)'"
                               onmouseout="this.style.transform='scale(1)'">
                                Add +
                            </a>
                        </div>
                        <div class="reviews-container" t-att-style="'text-align: center; max-width: 100%; background-color: ' + (partner.primary_color or '#ffffff') + ';'">
                            <t t-if="partner.review_ids">
                                <!-- Bootstrap Carousel with Fade Animation -->
                                <div id="reviewsCarousel" class="carousel slide carousel-fade" data-ride="carousel" data-pause="hover" t-att-data-interval="(partner.carousel_autoscroll_speed or 5) * 1000">
                                    <!-- Carousel Indicators - Completely removed to avoid overlapping with reviewer name -->
                                    
                                    <!-- Carousel Items -->
                                    <div class="carousel-inner">
                                        <t t-set="reviews_list" t-value="partner.review_ids.filtered(lambda r: r.is_published)[:partner.max_reviews_display or 5]"/>
                                        <t t-set="first_review" t-value="reviews_list[0] if reviews_list else None"/>
                                        <t t-foreach="reviews_list" t-as="review">
                                            <t t-set="is_first" t-value="review == first_review"/>
                                            <div t-att-class="'carousel-item' + (' active' if is_first else '')">
                                                <div class="review-item text-center" t-att-style="'margin: 0 auto; max-width: 100%; padding: 24px 60px; border-radius: 8px; background-color: ' + (partner.primary_color or '#ffffff') + '; border-left: 4px solid ' + (partner.secondary_color or '#2563eb') + '; box-shadow: 0 2px 4px rgba(0,0,0,0.1);'">
                                                    <div class="review-rating" t-att-style="'color: #ffc107; font-size: 24px; margin-bottom: 16px;'">
                                                        <t t-esc="review.stars_display"/>
                                                    </div>
                                                    <div class="review-text" t-att-style="'color: #495057; font-style: italic; line-height: 1.6; font-size: 16px; margin-bottom: 16px; word-wrap: break-word;'">
                                                        <t t-out="review.review_text"/>
                                                    </div>
                                                    <div class="reviewer-info">
                                                        <h5 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin: 0; font-weight: 600; font-size: 14px;'">
                                                            — <t t-if="review.reviewer_name" t-esc="review.reviewer_name"/><t t-else="">Anonymous</t>
                                                        </h5>
                                                    </div>
                                                </div>
                                            </div>
                                        </t>
                                    </div>
                                    
                                    <!-- Carousel Controls -->
                                    <a class="carousel-control-prev" href="#reviewsCarousel" role="button" data-slide="prev">
                                        <span class="carousel-control-prev-icon" aria-hidden="true"></span>
                                        <span class="sr-only">Previous</span>
                                    </a>
                                    <a class="carousel-control-next" href="#reviewsCarousel" role="button" data-slide="next">
                                        <span class="carousel-control-next-icon" aria-hidden="true"></span>
                                        <span class="sr-only">Next</span>
                                    </a>
                                </div>
                            </t>
                            <t t-else="">
                                <div class="text-center" t-att-style="'color: #64748b; padding: 20px;'">
                                    <p>No reviews yet. Be the first to leave a review!</p>
                                </div>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Video Section -->
            <t t-if="partner.video_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                        <h4 t-att-style="'color: ' + (partner.secondary_color or '#000') + '; margin-bottom: 24px; text-align: left; text-transform: uppercase; font-size: 0.875rem; letter-spacing: 0.05em;'">Video</h4>
                        <div class="d-flex flex-column align-items-center">
                            <t t-foreach="partner.video_ids" t-as="partner_video">
                                <div class="p-2 w-100">
                                    <div class="video-container" style="position: relative;">
                                        <iframe width="100%" height="315" 
                                                t-att-src="partner_video.embed_url + '?rel=0&amp;modestbranding=1&amp;showinfo=0'"
                                                frameborder="0" 
                                                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                                                allowfullscreen="true"
                                                t-att-title="partner_video.name"
                                                loading="lazy"
                                                onerror="this.style.display='none'; this.nextElementSibling.style.display='block';"></iframe>
                                        <div class="video-fallback" style="display: none; padding: 20px; text-align: center; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #dee2e6; border-radius: 5px;">
                                            <p><i class="fa fa-exclamation-triangle text-warning"></i> Video could not be loaded</p>
                                            <a t-att-href="partner_video.video_url" target="_blank" class="btn btn-primary btn-sm">
                                                <i class="fa fa-external-link"></i> Watch on YouTube
                                            </a>
                                        </div>
                                    </div>
                                </div>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Websites Section -->
            <t t-if="partner.website_ids">
                <section class="s_text_block o_colored_level pt0 pb0"
                         t-att-style="'background-color: ' + (partner.primary_color or '#ffffff') + '; padding: 12px 0;'">
                    <div class="s_allow_columns container" style="max-width: 1000px; margin: 0 auto; padding: 0 16px;">
                        <div class="d-flex flex-wrap justify-content-center gap-3">
                            <t t-foreach="partner.website_ids" t-as="partner_website">
                                <a t-att-href="'http://' + partner_website.website_url if not (partner_website.website_url.startswith('http://') or partner_website.website_url.startswith('https://')) else partner_website.website_url"
                                   class="btn"
                                   t-att-style="'flex: 1 1 calc(50% - 12px); max-width: calc(50% - 12px); background-color: ' + (partner_website.button_color or partner.secondary_color or '#2563eb') + '; color: white; padding: 12px; border-radius: 8px; font-weight: bold; text-decoration: none; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s; display: flex; align-items: center; justify-content: center; gap: 8px; border: none;'"
                                   onmouseover="this.style.transform='scale(0.95)'"
                                   onmouseout="this.style.transform='scale(1)'"
                                   target="_blank">
                                    <t t-if="partner_website.button_logo">
                                        <img t-att-src="'/website/image/partner.vcard.website/' + str(partner_website.id) + '/button_logo'"
                                             alt="Logo" class="img-fluid" style="max-height: 24px;"/>
                                    </t>
                                    <t t-else="">
                                        <t t-esc="partner_website.name"/>
                                    </t>
                                </a>
                            </t>
                        </div>
                    </div>
                </section>
            </t>

            <!-- Existing Calendly widget code -->
            <t t-if="partner.calendly_url">
                <div class="calendly-inline-widget"
                     t-att-data-url="partner.calendly_url"
                     style="min-width: 100%; height: 100vh; overflow: hidden; margin-bottom: 0; padding-bottom: 0;"></div>
                <script type="text/javascript"
                        src="https://assets.calendly.com/assets/external/widget.js"></script>
            </t>
       
                </div> <!-- Close the responsive container div -->
            </div> <!-- Close the wrap div here -->
            
            <!-- Modals (Lead, QR Code, Service Request, Review) -->
            <!-- Lead Modal -->
            <div class="modal fade" id="leadModal" tabindex="-1" role="dialog" aria-labelledby="leadModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true" data-dismiss-on-backdrop="true">
              <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
                <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                  <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                    <div style="display: flex; align-items: center; width: 100%;">
                      <div style="flex: 1;">
                        <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="leadModalLabel">Fill in your details</h5>
                      </div>
                      <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                        <span aria-hidden="true">×</span>
                      </button>
                    </div>
                  </div>
                  <div class="modal-body" style="padding: 16px 24px 24px 24px;">
                    <div id="successMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                      <i class="fa fa-check-circle me-2"></i>Thank you! I look forward to talking with you soon.
                    </div>
            <form id="leadForm">
                <div class="form-group">
                    <input type="hidden" class="form-control" id="partnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                    <input type="hidden" id="leadTagIds" name="lead_tag_ids" t-att-value="','.join(map(str, partner.lead_tag_ids.ids))"/>
                    <input type="hidden" id="formThankYouMessage" t-att-value="partner.form_thank_you_message or 'Thank you! I look forward to talking with you soon.'"/>
                </div>
                <div class="form-group">
                    <label for="fullName">Full name <span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="fullName" name="full_name" required="required" placeholder="Your name"/>
                </div>
                <div class="form-group">
                    <label for="email">Email <span class="text-danger">*</span></label>
                    <input type="email" class="form-control" id="email" name="email" required="required" placeholder="you@example.com"/>
                </div>
                <div class="form-group">
                    <label for="phone">Phone</label>
                    <input type="tel" class="form-control" id="phone" name="phone" placeholder="Your phone number"/>
                    <input type="hidden" id="phone_full" name="phone_full"/>
                </div>
                <style>
                    #leadModal .form-group {{ position: relative; margin-bottom: 14px; }}
                    #leadModal .form-group label {{ display: block !important; margin-bottom: 4px; font-weight: 500; color: #374151; }}
                    #leadModal .form-group .form-control,
                    #leadModal .form-group input.form-control {{ display: block; width: 100%; height: 40px; box-sizing: border-box; }}
                    #leadModal textarea.form-control {{ height: auto; min-height: 80px; }}
                    #leadModal .iti {{ display: block !important; width: 100%; }}
                    #leadModal .iti__flag-container {{ position: absolute; top: 0; bottom: 0; right: auto; left: 0; z-index: 2; }}
                    #leadModal .iti__selected-flag {{ z-index: 4; position: relative; display: flex; align-items: center; height: 100%; padding: 0 10px 0 12px; background-color: #f8f9fa; border-right: 1px solid #dee2e6; border-radius: 4px 0 0 4px; cursor: pointer; min-width: 76px; }}
                    #leadModal .iti__flag-box {{ margin-right: 6px; }}
                    #leadModal .iti__arrow {{ margin-left: 6px; width: 0; height: 0; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 4px solid #555; }}
                    #leadModal .iti__selected-dial-code {{ margin-left: 2px; font-size: 14px; color: #374151; }}
                    #leadModal #phone {{ padding-left: 88px !important; }}
                    #leadModal .iti__country-list {{ z-index: 9999 !important; }}
                </style>
                <div class="form-group">
                    <label for="notes">Notes</label>
                    <textarea class="form-control" id="notes" name="notes" placeholder="Anything else you'd like to share (optional)"></textarea>
                </div>
            </form>
                  </div>
                  <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; flex-direction: column; gap: 12px;">
                    <button type="button" id="submitLeadBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 12px 24px; border-radius: 8px; width: 100%;'">
                      Share My Contact
                    </button>
                    <small style="text-align: center; color: #6b7280; font-size: 12px; margin: 0;"><t t-set="vinc_label">* By clicking the 'Share My Contact' button, I agree to be contacted by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                  </div>
                </div>
              </div>
            </div>
            
            <!-- QR Code Modal -->
            <div class="modal fade" id="qrCodeModal" tabindex="-1" role="dialog" aria-labelledby="qrCodeModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
              <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 400px;">
                <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                  <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                    <div style="display: flex; align-items: center; width: 100%;">
                      <div style="width: 40px; height: 40px; background: #f3f4f6; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin-right: 12px;">
                        <i class="fa fa-qrcode" style="font-size: 20px; color: #6b7280;"></i>
                      </div>
                      <div style="flex: 1;">
                        <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="qrCodeModalLabel">
                          <t t-if="partner.name" t-esc="partner.name"/><t t-else="">QR Code</t>
                        </h5>
                        <p style="margin: 4px 0 0 0; font-size: 14px; color: #6b7280;">Scan to connect</p>
                      </div>
                      <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                        <span aria-hidden="true">×</span>
                      </button>
                    </div>
                  </div>
                  <div class="modal-body" style="padding: 16px 24px 24px 24px; text-align: center;">
                    <p style="margin: 0 0 20px 0; font-size: 14px; color: #6b7280; line-height: 1.5;">
                      <t t-set="vinc_label">Scan this QR code to quickly save %(name)s's information to your device.</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/>
                    </p>
                    <div t-att-style="'background: ' + (partner.primary_color or '#ffffff') + '; padding: 20px; border-radius: 12px; display: inline-block; box-shadow: 0 2px 8px rgba(0,0,0,0.1);'">
                      <img t-att-src="'/vcard/qr_code/download/' + str(partner.id)" 
                           alt="QR Code" 
                           style="width: 250px; height: 250px; max-width: 100%; display: block;"/>
                    </div>
                  </div>
                  <div class="modal-footer" style="border-top: none; padding: 16px 24px 24px 24px; display: flex; justify-content: space-between; gap: 12px;">
                    <button type="button" class="btn" data-dismiss="modal" style="background: transparent; border: none; color: #6b7280; font-weight: 500; padding: 10px 20px; flex: 1;">
                      Close
                    </button>
                    <a t-att-href="'/website/vcard/download/' + str(partner.id)" 
                       class="btn" 
                       t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; flex: 1; text-decoration: none; display: inline-flex; align-items: center; justify-content: center; gap: 8px;'">
                      <i class="fa fa-download"></i>
                      <span>Download vCard</span>
                    </a>
                  </div>
                </div>
              </div>
            </div>
            
            <!-- Service Request Modal -->
            <div class="modal fade" id="serviceRequestModal" tabindex="-1" role="dialog" aria-labelledby="serviceRequestModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
              <div class="modal-dialog modal-dialog-centered" role="document" style="max-width: 500px;">
                <div class="modal-content" style="border-radius: 16px; border: none; box-shadow: 0 10px 40px rgba(0,0,0,0.2); background-color: white;">
                  <div class="modal-header" style="border-bottom: none; padding: 24px 24px 8px 24px;">
                    <div style="display: flex; align-items: center; width: 100%;">
                      <div style="flex: 1;">
                        <h5 class="modal-title" style="margin: 0; font-weight: 600; font-size: 18px; color: #111827;" id="serviceRequestModalLabel">
                          Request Service
                        </h5>
                      </div>
                      <button type="button" class="close" data-dismiss="modal" aria-label="Close" style="margin: 0; padding: 0; background: none; border: none; font-size: 24px; color: #9ca3af; cursor: pointer;">
                        <span aria-hidden="true">×</span>
                      </button>
                    </div>
                  </div>
                  <div class="modal-body" style="padding: 16px 24px 24px 24px;">
                    <div id="serviceRequestSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                      <i class="fa fa-check-circle me-2"></i>Thank you! Your service request has been sent. We'll be in touch shortly.
                    </div>
                    <form id="serviceRequestForm">
                      <!-- Hidden Inputs -->
                      <div class="form-group">
                        <input type="hidden" class="form-control" id="serviceRequestPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                        <input type="hidden" id="serviceRequestServiceId" name="service_id" value=""/>
                        <input type="hidden" id="serviceRequestServiceName" name="service_name" value=""/>
                        <input type="hidden" id="serviceRequestServiceDescription" name="service_description" value=""/>
                      </div>
          
                      <!-- Service Info (Read-only) -->
                      <div class="form-group" style="margin-bottom: 20px;">
                        <label style="margin-bottom: 8px; font-weight: 600; color: #111827;"><strong>Service:</strong></label>
                        <p id="serviceRequestServiceDisplay" t-att-style="'margin: 0; padding: 12px; background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid #e5e7eb; border-radius: 8px; color: #111827; font-weight: 600; font-size: 16px;'"></p>
                      </div>
          
                      <!-- Form fields -->
                      <div class="form-group">
                        <label for="serviceRequestFullName">Full name<span class="text-danger">*</span></label>
                        <input type="text" class="form-control" id="serviceRequestFullName" name="full_name" required="required"/>
                      </div>
                      <div class="form-group">
                        <label for="serviceRequestEmail">Email<span class="text-danger">*</span></label>
                        <input type="email" class="form-control" id="serviceRequestEmail" name="email" required="required"/>
                      </div>
                      <div class="form-group">
                        <label for="serviceRequestPhone">Phone</label>
                        <input type="tel" class="form-control" id="serviceRequestPhone" name="phone" placeholder="Your Phone"/>
                        <input type="hidden" id="serviceRequestPhoneFull" name="phone_full"/>
                      </div>
                      <style>
                        /* Fix intl-tel-input styling for service request modal */
                        #serviceRequestModal .form-group {{
                            position: relative;
                        }}
                        #serviceRequestModal .iti {{
                            width: 100%;
                            display: block;
                        }}
                        #serviceRequestModal .iti__flag-container {{
                            position: absolute;
                            top: 0;
                            bottom: 0;
                            right: auto;
                            left: 0;
                            z-index: 2;
                        }}
                        #serviceRequestModal .iti__selected-flag {{
                            z-index: 4;
                            position: relative;
                            display: flex;
                            align-items: center;
                            height: 100%;
                            padding: 0 10px 0 8px;
                            background-color: #f8f9fa;
                            border-right: 1px solid #dee2e6;
                            cursor: pointer;
                            min-width: 70px;
                        }}
                        #serviceRequestModal .iti__flag-box {{
                            margin-right: 4px;
                        }}
                        #serviceRequestModal .iti__arrow {{
                            margin-left: 4px;
                            width: 0;
                            height: 0;
                            border-left: 3px solid transparent;
                            border-right: 3px solid transparent;
                            border-top: 4px solid #555;
                        }}
                        #serviceRequestModal #serviceRequestPhone {{
                            padding-left: 80px !important;
                        }}
                        #serviceRequestModal .iti__selected-dial-code {{
                            margin-left: 2px;
                            margin-right: 2px;
                            font-size: 14px;
                        }}
                        #serviceRequestModal .iti__country-list {{
                            z-index: 9999;
                        }}
                      </style>
                      <!-- Container for dynamic, service-specific custom questions -->
                      <div id="serviceRequestCustomQuestions"></div>
          
                      <div class="form-group">
                        <label for="serviceRequestNotes">Additional Details</label>
                        <textarea class="form-control" id="serviceRequestNotes" name="notes" rows="4" placeholder="Add any additional information or requirements..."></textarea>
                      </div>
          
                      <div class="text-center" style="padding-top: 10px;">
                        <button type="button" id="submitServiceRequestBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#8b5cf6') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%;'">Send Request</button>
                      </div>
                    </form>
                  </div>
                  <div class="modal-footer" style="border-top: none; padding: 0 24px 24px 24px; text-align: center;">
                    <small style="color: #6b7280; font-size: 12px;"><t t-set="vinc_label">* By clicking 'Send Request', I agree to be contacted by %(name)s regarding this service</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/></small>
                  </div>
                </div>
              </div>
            </div>
            
            <!-- Review Modal -->
            <div class="modal fade" id="reviewModal" tabindex="-1" role="dialog" aria-labelledby="reviewModalLabel" aria-hidden="true" data-backdrop="true" data-keyboard="true">
              <div class="modal-dialog" role="document">
                <div class="modal-content">
                  <div class="modal-header">
                   <h5 class="modal-title" style="text-align: center;" id="reviewModalLabel">Leave a Review</h5>
                    <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                      <span aria-hidden="true">×</span>
                    </button>
                  </div>
                  <div class="modal-body">
                    <div id="reviewSuccessMessage" class="alert alert-success text-center" role="alert" style="display: none; font-size: 16px; font-weight: bold;">
                      <i class="fa fa-check-circle me-2"></i>Thank you for your review! We appreciate your feedback.
                    </div>
            <form id="reviewForm" onsubmit="return false;">
                <div class="form-group">
                    <input type="hidden" class="form-control" id="reviewPartnerId" name="partner_id" t-att-value="partner.id" readonly="readonly"/>
                    <input type="hidden" id="reviewThankYouMessage" t-att-value="partner.review_thank_you_message or 'Thank you for your review! We appreciate your feedback.'"/>
                </div>
                <div class="form-group">
                    <label for="reviewerName">Your Name<span class="text-danger">*</span></label>
                    <input type="text" class="form-control" id="reviewerName" name="reviewer_name" required="required"/>
                </div>
                
                <div class="form-group">
                    <label for="reviewRating">Rating<span class="text-danger">*</span></label>
                    <div class="star-rating" style="font-size: 32px; color: #ffc107; cursor: pointer;">
                        <span class="star" data-rating="1">☆</span>
                        <span class="star" data-rating="2">☆</span>
                        <span class="star" data-rating="3">☆</span>
                        <span class="star" data-rating="4">☆</span>
                        <span class="star" data-rating="5">☆</span>
                    </div>
                    <input type="hidden" id="reviewRating" name="rating" value="5" required="required"/>
                </div>
                
                <div class="form-group">
                    <label for="reviewText">Your Review<span class="text-danger">*</span></label>
                    <textarea class="form-control" id="reviewText" name="review_text" rows="4" required="required"></textarea>
                </div>
           
                <div class="text-center" style="padding-top: 5px;">
                    <button type="button" id="submitReviewBtn" class="btn" t-att-style="'background-color: ' + (partner.secondary_color or '#2563eb') + '; color: white; border: none; font-weight: 600; padding: 10px 24px; border-radius: 8px; width: 100%; text-decoration: none; display: inline-block; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: transform 0.1s;'"
                            onmouseover="this.style.transform='scale(0.95)'"
                            onmouseout="this.style.transform='scale(1)'">Submit Review</button>
                </div>
            </form>
                  </div>
                 <div class="modal-footer" style="justify-content: center !important; padding: 0;">
               <small><t t-set="vinc_label">* Your review will be visible once approved by %(name)s</t><t t-out="vinc_label % {{'name': partner.name or ''}}"/> </small>
                               </div>
                           </div>
                       </div>
                   </div>
           
                   <!-- Load widget.js and other scripts -->
                   <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/css/intlTelInput.css"/>
                   <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
                   <script type="text/javascript" src="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/js/bootstrap.min.js"></script>
                   <script type="text/javascript" src="https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.19/js/intlTelInput.min.js"></script>
                   <!-- Ensure widget.js comes after jQuery and intl-tel-input -->
                   <script type="text/javascript" t-attf-src="/qr_code_odoo/static/src/js/widget.js"></script>
           
           <!-- Modal and Carousel CSS -->
           <style>
               .modal-backdrop {{
                   background-color: rgba(0, 0, 0, 0.3) !important;
                   opacity: 1 !important;
                   z-index: 2040 !important;
                   position: fixed !important;
                   top: 0 !important;
                   left: 0 !important;
                   width: 100% !important;
                   height: 100% !important;
               }}
               .modal {{
                   z-index: 2050 !important;
                   position: fixed !important;
                   top: 0 !important;
                   left: 0 !important;
                   width: 100% !important;
                   height: 100% !important;
                   pointer-events: none !important;
               }}
               .modal-backdrop.show {{
                   opacity: 1 !important;
               }}
               .modal-dialog {{
                   z-index: 2051 !important;
                   position: relative !important;
                   pointer-events: auto !important;
                   margin: 1.75rem auto !important;
               }}
               .modal-content {{
                   z-index: 2052 !important;
                   position: relative !important;
                   pointer-events: auto !important;
                   background-color: var(--primary-color, #ffffff) !important;
                   border-radius: 16px !important;
               }}
               .modal input, .modal textarea, .modal select, .modal button, .modal a, .modal .form-control, .modal label {{
                   pointer-events: auto !important;
                   cursor: pointer !important;
                   position: relative !important;
               }}
               .modal input[type="text"], .modal input[type="email"], .modal input[type="tel"], .modal textarea {{
                   cursor: text !important;
               }}
               body.modal-open {{
                   overflow: hidden !important;
               }}
               .modal-header, .modal-body, .modal-footer {{
                   pointer-events: auto !important;
                   position: relative !important;
               }}
               .modal .close {{
                   pointer-events: auto !important;
                   cursor: pointer !important;
                   z-index: 2053 !important;
               }}
               .reviews-container {{
                   text-align: center;
                   max-width: 100%;
               }}
               .review-item {{
                   transition: transform 0.3s ease, box-shadow 0.3s ease;
                   word-wrap: break-word;
                   overflow-wrap: break-word;
               }}
               .review-item:hover {{
                   transform: translateY(-5px);
                   box-shadow: 0 5px 15px rgba(0,0,0,0.1);
               }}
               .review-text {{
                   word-wrap: break-word;
                   overflow-wrap: break-word;
                   hyphens: auto;
                   word-break: break-word;
               }}
               .carousel-control-prev, .carousel-control-next {{
                   width: 40px !important;
                   height: 40px !important;
                   min-width: 40px !important;
                   min-height: 40px !important;
                   max-width: 40px !important;
                   max-height: 40px !important;
                   background-color: rgba(0,0,0,0.7) !important;
                   border-radius: 50% !important;
                   top: 50% !important;
                   transform: translateY(-50%) !important;
                   opacity: 0.9 !important;
                   display: flex !important;
                   align-items: center !important;
                   justify-content: center !important;
                   transition: all 0.3s ease !important;
                   border: 2px solid rgba(255,255,255,0.5) !important;
                   z-index: 10 !important;
                   box-sizing: border-box !important;
                   padding: 0 !important;
                   margin: 0 !important;
                   text-decoration: none !important;
                   outline: none !important;
               }}
               .carousel-control-prev {{
                   left: 10px !important;
               }}
               .carousel-control-next {{
                   right: 10px !important;
               }}
               .carousel-control-prev:hover, .carousel-control-next:hover {{
                   opacity: 1 !important;
                   background-color: rgba(0,0,0,0.9) !important;
                   border-color: rgba(255,255,255,0.8) !important;
                   transform: translateY(-50%) scale(1.05) !important;
                   text-decoration: none !important;
               }}
               .carousel-control-prev:focus, .carousel-control-next:focus {{
                   text-decoration: none !important;
                   outline: none !important;
               }}
               .carousel-control-prev:active, .carousel-control-next:active {{
                   text-decoration: none !important;
               }}
               .carousel-control-prev-icon, .carousel-control-next-icon {{
                   width: 20px !important;
                   height: 20px !important;
                   background: none !important;
                   background-image: none !important;
                   display: flex !important;
                   align-items: center;
                   justify-content: center;
                   font-size: 18px;
                   color: white !important;
                   font-weight: bold;
               }}
               .carousel-control-prev-icon:before {{
                   content: "◀" !important;
                   display: block !important;
               }}
               .carousel-control-next-icon:before {{
                   content: "▶" !important;
                   display: block !important;
               }}
               .carousel-control-prev, .carousel-control-next {{
                   aspect-ratio: 1 / 1 !important;
                   flex-shrink: 0 !important;
                   flex-grow: 0 !important;
               }}
               .carousel-control-prev, .carousel-control-next {{
                   background-image: none !important;
                   background-position: initial !important;
                   background-repeat: initial !important;
                   background-size: initial !important;
               }}
               .carousel-control-prev, .carousel-control-next {{
                   text-align: center;
               }}
               .carousel-control-prev-icon, .carousel-control-next-icon {{
                   visibility: visible !important;
                   opacity: 1 !important;
               }}
               .carousel-control-prev:after {{
                   content: "◀";
                   position: absolute;
                   top: 50%;
                   left: 50%;
                   transform: translate(-50%, -50%);
                   color: white;
                   font-size: 18px;
                   font-weight: bold;
                   z-index: 1;
                   text-decoration: none !important;
               }}
               .carousel-control-next:after {{
                   content: "▶";
                   position: absolute;
                   top: 50%;
                   left: 50%;
                   transform: translate(-50%, -50%);
                   color: white;
                   font-size: 18px;
                   font-weight: bold;
                   z-index: 1;
                   text-decoration: none !important;
               }}
               .carousel-control-prev, .carousel-control-next, .carousel-control-prev:hover, .carousel-control-next:hover, .carousel-control-prev:focus, .carousel-control-next:focus, .carousel-control-prev:active, .carousel-control-next:active, .carousel-control-prev:visited, .carousel-control-next:visited {{
                   text-decoration: none !important;
                   border-bottom: none !important;
                   text-decoration-line: none !important;
                   text-decoration-style: none !important;
                   text-decoration-color: transparent !important;
               }}
               .review-text, .review-text * {{
                   overflow-y: hidden !important;
                   max-height: none !important;
               }}
               .review-text::-webkit-scrollbar, .review-text *::-webkit-scrollbar {{
                   display: none !important;
                   width: 0 !important;
                   height: 0 !important;
               }}
               .review-text, .review-text * {{
                   -ms-overflow-style: none !important;
                   scrollbar-width: none !important;
               }}
               .reviews-container, .reviews-container .carousel, .reviews-container .carousel-inner, .reviews-container .carousel-item, .reviews-container .review-item {{
                   overflow: hidden !important;
               }}
               .review-rating {{
                   text-shadow: 1px 1px 2px rgba(0,0,0,0.3);
               }}
               @media (max-width: 768px) {{
                   .review-item {{
                       padding: 15px !important;
                       margin-bottom: 20px !important;
                   }}
               }}
               /* Hide carousel indicators completely - no numbers showing or overlapping */
               #reviewsCarousel .carousel-indicators,
               .carousel-indicators {{
                   display: none !important;
                   visibility: hidden !important;
                   opacity: 0 !important;
                   position: absolute !important;
                   left: -9999px !important;
                   width: 0 !important;
                   height: 0 !important;
                   overflow: hidden !important;
                   pointer-events: none !important;
                   z-index: -1 !important;
               }}
               #reviewsCarousel .carousel-indicators li,
               .carousel-indicators li {{
                   display: none !important;
                   visibility: hidden !important;
                   opacity: 0 !important;
                   width: 0 !important;
                   height: 0 !important;
                   pointer-events: none !important;
               }}
               /* Ensure reviewer name is not overlapped */
               .reviewer-info {{
                   position: relative !important;
                   z-index: 10 !important;
               }}
               /* Add padding to review items to prevent overlap with carousel controls */
               #reviewsCarousel .review-item {{
                   padding-left: 60px !important;
                   padding-right: 60px !important;
               }}
               /* On mobile, reduce padding since buttons are hidden */
               @media (max-width: 768px) {{
                   #reviewsCarousel .review-item {{
                       padding-left: 24px !important;
                       padding-right: 24px !important;
                   }}
                   .carousel-control-prev, .carousel-control-next {{
                       display: none !important;
                   }}
               }}
               .carousel-fade .carousel-item {{
                   opacity: 0;
                   transition: opacity 0.3s ease-in-out;
                   transform: translateZ(0);
               }}
               .carousel-fade .carousel-item.active {{
                   opacity: 1;
               }}
               .carousel-fade .carousel-item-next, .carousel-fade .carousel-item-prev {{
                   opacity: 0;
               }}
               .carousel-fade .carousel-item-next.active, .carousel-fade .carousel-item-prev.active {{
                   opacity: 1;
               }}
               .carousel-inner {{
                   will-change: transform, opacity;
               }}
               .carousel-item {{
                   will-change: opacity;
               }}
           </style>
           
           <!-- Fix Modal Clickability -->
           <script>
               document.addEventListener('DOMContentLoaded', function() {{
                   // Fix modal z-index and clickability BEFORE it's shown
                   $(document).on('show.bs.modal', '.modal', function() {{
                       var $modal = $(this);
                       if ($modal.parent().is('body') === false) {{
                           $modal.appendTo('body');
                       }}
                   }});
                   
                   // Fix modal z-index and clickability when shown
                   $(document).on('shown.bs.modal', '.modal', function() {{
                       var $modal = $(this);
                       var $backdrop = $('.modal-backdrop');
                       $backdrop.css({{
                           'z-index': '2040',
                           'position': 'fixed',
                           'top': '0',
                           'left': '0',
                           'width': '100%',
                           'height': '100%',
                           'pointer-events': 'auto'
                       }});
                       $modal.css({{
                           'z-index': '2050',
                           'position': 'fixed',
                           'top': '0',
                           'left': '0',
                           'width': '100%',
                           'height': '100%',
                           'pointer-events': 'none'
                       }});
                       $modal.find('.modal-dialog').css({{
                           'z-index': '2051',
                           'position': 'relative',
                           'pointer-events': 'auto',
                           'margin': '1.75rem auto'
                       }});
                       $modal.find('.modal-content').css({{
                           'z-index': '2052',
                           'position': 'relative',
                           'pointer-events': 'auto',
                           'background-color': 'white',
                           'border-radius': '16px'
                       }});
                       $modal.find('.modal-content *').css('pointer-events', 'auto');
                   }});
                   
                   $(document).on('click', '.modal-content, .modal-header, .modal-body, .modal-footer', function(e) {{
                       e.stopPropagation();
                       e.stopImmediatePropagation();
                   }});
                   
                   $(document).on('click', '.modal input, .modal textarea, .modal select, .modal button:not(#submitReviewBtn):not(#submitLeadBtn):not(#submitServiceRequestBtn), .modal a:not([data-dismiss]), .modal .form-control, .modal label', function(e) {{
                       e.stopPropagation();
                       e.stopImmediatePropagation();
                   }});
                   
                   $(document).on('click', '.modal-backdrop', function(e) {{
                       e.stopPropagation();
                       $('.modal.show').each(function() {{
                           $(this).modal('hide');
                       }});
                   }});
                   
                   $(document).on('click', '.modal', function(e) {{
                       var $modal = $(this);
                       if ($(e.target).is('.modal') && !$(e.target).hasClass('modal-dialog') && !$(e.target).hasClass('modal-content')) {{
                           $modal.modal('hide');
                       }}
                   }});
                   
                   $(document).on('click', '.modal-content, .modal-header, .modal-body, .modal-footer', function(e) {{
                       e.stopPropagation();
                       e.stopImmediatePropagation();
                   }});
                   
                   // Carousel initialization
                   const carousel = document.getElementById('reviewsCarousel');
                   if (carousel) {{
                       // Remove carousel indicators completely to avoid overlapping with reviewer name
                       const indicators = carousel.querySelector('.carousel-indicators');
                       if (indicators) {{
                           indicators.remove();
                       }}
                       
                       const autoscrollSpeed = carousel.getAttribute('data-interval');
                       const intervalValue = autoscrollSpeed ? parseInt(autoscrollSpeed) : 5000;
                       $(carousel).carousel({{
                           interval: intervalValue > 0 ? intervalValue : false,
                           wrap: true,
                           touch: true,
                           pause: 'hover'
                       }});
                       
                       // Ensure indicators are removed after carousel initialization (in case Bootstrap generates them)
                       $(carousel).on('slide.bs.carousel', function() {{
                           const ind = this.querySelector('.carousel-indicators');
                           if (ind) {{
                               ind.remove();
                           }}
                       }});
                       
                       // Force show arrows on desktop
                       if (window.innerWidth > 768) {{
                           const prevBtn = carousel.querySelector('.carousel-control-prev');
                           const nextBtn = carousel.querySelector('.carousel-control-next');
                           if (prevBtn) {{
                               prevBtn.style.display = 'flex';
                               prevBtn.style.opacity = '0.9';
                               prevBtn.style.visibility = 'visible';
                           }}
                           if (nextBtn) {{
                               nextBtn.style.display = 'flex';
                               nextBtn.style.opacity = '0.9';
                               nextBtn.style.visibility = 'visible';
                           }}
                       }}
                       
                       // Periodically check and remove any dynamically generated indicators
                       setInterval(function() {{
                           const ind = carousel.querySelector('.carousel-indicators');
                           if (ind) {{
                               ind.remove();
                           }}
                       }}, 500);
                   }}
               }});

               // Auto-show lead form feature
               var wrapDiv = document.getElementById('wrap');
               if (wrapDiv) {{
                   var autoShowLead = wrapDiv.getAttribute('data-auto-show-lead');
                   if (autoShowLead === 'true') {{
                       setTimeout(function() {{
                           $('#leadModal').modal('show');
                       }}, 500);
                   }}
                   
                   // Auto-download vCard feature
                   var autoDownloadVcard = wrapDiv.getAttribute('data-auto-download-vcard');
                   if (autoDownloadVcard === 'true') {{
                       setTimeout(function() {{
                           var downloadUrl = wrapDiv.getAttribute('data-vcard-download-url');
                           if (downloadUrl) {{
                               window.location.href = downloadUrl;
                           }}
                       }}, 800);
                   }}
               }}
           </script>
           
        </t>
    </t>
       """

    def _build_creative_template(self, image_url, banner_url=None, referral_url=None):
        """Build the creative vCard template with floating background elements and QR share icon."""
        if referral_url is None:
            referral_url = self.get_referral_signup_url()
        # Start with Classic template and modify it
        template = self._build_classic_template(image_url, banner_url, referral_url)
        
        # Replace the class to add creative class
        template = template.replace(
            'class="oe_structure oe_empty"',
            'class="oe_structure oe_empty vcard-template-creative"'
        )
        
        # Add floating background elements before the container-fluid - MORE elements for mobile
        secondary_color = self.secondary_color or '#2563eb'
        floating_elements = f"""
                <!-- Floating Background Elements (Desktop) -->
                <div class="floating-elements" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 0; overflow: hidden;">
                    <div class="float-circle-1" style="position: absolute; width: 120px; height: 120px; border-radius: 50%; background-color: {secondary_color}; opacity: 0.1; top: 10%; left: -5%; animation: floatAnim1 20s ease-in-out infinite;"></div>
                    <div class="float-circle-2" style="position: absolute; width: 80px; height: 80px; border-radius: 50%; background-color: {secondary_color}; opacity: 0.15; top: 60%; right: -3%; animation: floatAnim2 15s ease-in-out infinite;"></div>
                    <div class="float-square-1" style="position: absolute; width: 60px; height: 60px; background-color: {secondary_color}; opacity: 0.08; transform: rotate(45deg); top: 30%; right: 10%; animation: floatAnim3 25s ease-in-out infinite;"></div>
                    <div class="float-circle-3" style="position: absolute; width: 100px; height: 100px; border-radius: 50%; background-color: {secondary_color}; opacity: 0.12; bottom: 20%; left: 8%; animation: floatAnim4 18s ease-in-out infinite;"></div>
                    <div class="float-triangle-1" style="position: absolute; width: 0; height: 0; border-left: 40px solid transparent; border-right: 40px solid transparent; border-bottom: 70px solid {secondary_color}; opacity: 0.1; bottom: 50%; right: 5%; animation: floatAnim5 22s ease-in-out infinite;"></div>
                    <!-- Additional elements for mobile visibility -->
                    <div class="float-circle-mobile-1" style="position: absolute; width: 60px; height: 60px; border-radius: 50%; background-color: {secondary_color}; opacity: 0.12; top: 40%; left: 2%; animation: floatAnimMobile1 8s ease-in-out infinite;"></div>
                    <div class="float-circle-mobile-2" style="position: absolute; width: 50px; height: 50px; border-radius: 50%; background-color: {secondary_color}; opacity: 0.15; top: 70%; right: 1%; animation: floatAnimMobile2 10s ease-in-out infinite;"></div>
                    <div class="float-square-mobile-1" style="position: absolute; width: 40px; height: 40px; background-color: {secondary_color}; opacity: 0.1; transform: rotate(45deg); top: 20%; left: 5%; animation: floatAnimMobile3 9s ease-in-out infinite;"></div>
                    <div class="float-circle-mobile-3" style="position: absolute; width: 70px; height: 70px; border-radius: 50%; background-color: {secondary_color}; opacity: 0.13; bottom: 10%; right: 3%; animation: floatAnimMobile4 7s ease-in-out infinite;"></div>
                    <div class="float-triangle-mobile-1" style="position: absolute; width: 0; height: 0; border-left: 25px solid transparent; border-right: 25px solid transparent; border-bottom: 45px solid {secondary_color}; opacity: 0.12; top: 55%; left: 8%; animation: floatAnimMobile5 11s ease-in-out infinite;"></div>
                </div>
                
"""
        
        # Insert floating elements after the opening wrap div
        wrap_div_pos = template.find('<div id="wrap"')
        if wrap_div_pos != -1:
            container_pos = template.find('<div class="container-fluid"', wrap_div_pos)
            if container_pos != -1:
                template = template[:container_pos] + floating_elements + template[container_pos:]
        
        # Add QR share icon button to profile picture
        profile_wrapper_pos = template.find('class="profile-picture-wrapper"')
        if profile_wrapper_pos != -1:
            img_start_pos = template.find('<img', profile_wrapper_pos)
            img_end_pos = template.find('>', img_start_pos)
            if img_start_pos != -1 and img_end_pos != -1:
                if template.find('position: relative', profile_wrapper_pos, img_start_pos) == -1:
                    img_tag_with_closing = template[img_start_pos:img_end_pos + 1]
                    qr_share_button = f"""
                    <div style="position: relative; display: inline-block;">
                        {img_tag_with_closing}
                        <!-- QR Share Icon Button -->
                        <a href="#" 
                           class="qr-share-btn"
                           data-toggle="modal" 
                           data-target="#qrCodeModal"
                           t-att-style="'position: absolute; top: -4px; right: -4px; width: 36px; height: 36px; background-color: ' + (partner.secondary_color or '{secondary_color}') + '; border: 2px solid white; border-radius: 8px; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 8px rgba(0,0,0,0.2); cursor: pointer; text-decoration: none; z-index: 11; transition: all 0.2s ease;'"
                           onmouseover="this.style.transform='scale(1.15)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';"
                           onmouseout="this.style.transform='scale(1)'; this.style.boxShadow='0 2px 8px rgba(0,0,0,0.2)';">
                            <i class="fa fa-qrcode" style="color: white; font-size: 16px;"></i>
                        </a>
                    </div>
"""
                    template = template[:img_start_pos] + qr_share_button + template[img_end_pos + 1:]
        
        # Update pointer-events to allow interaction with QR button
        template = template.replace(
            'pointer-events: none; overflow: visible;',
            'pointer-events: auto; overflow: visible;'
        )
        
        # Remove bottom QR Code button
        qr_button_bottom_start = template.find('<!-- Footer CTA - QR Code Button')
        if qr_button_bottom_start != -1:
            qr_button_bottom_end = template.find('</a>', qr_button_bottom_start)
            if qr_button_bottom_end != -1:
                # Find the closing div tag
                closing_div_pos = template.find('</div>', qr_button_bottom_end)
                if closing_div_pos != -1:
                    # Remove the entire footer CTA section
                    template = template[:qr_button_bottom_start] + template[closing_div_pos + 6:]
        
        # Redesign the About section to match the mockup
        about_section_start = template.find('<!-- Tagline/About section')
        if about_section_start != -1:
            # Find where the About section ends (before MAIN ACTION BUTTONS)
            about_section_end = template.find('<!-- MAIN ACTION BUTTONS', about_section_start)
            if about_section_end != -1:
                # Replace the About section with new design
                new_about_section = f"""
                    <!-- Creative About Section (Redesigned) -->
                    <div style="margin-top: 24px; margin-bottom: 32px; max-width: 700px; margin-left: auto; margin-right: auto; padding: 0 16px;">
                        <!-- About Card -->
                        <div t-att-style="'background: ' + (partner.primary_color or '#ffffff') + '; border: 1px solid rgba(0,0,0,0.1); border-radius: 16px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.05);'">
                            <!-- About Me Label -->
                            <div t-att-style="'background-color: ' + (partner.secondary_color or '{secondary_color}') + '; color: white; padding: 6px 16px; border-radius: 20px; display: inline-block; margin-bottom: 16px; font-size: 0.75rem; font-weight: 600;'">
                                About Me
                            </div>
                            
                            <!-- About Text -->
                            <div t-if="partner.about" style="margin-bottom: 20px; text-align: left;">
                                <p style="margin: 0; color: #374151; font-size: 0.9375rem; line-height: 1.6;">
                                    <t t-out="partner.about"/>
                                </p>
                            </div>
                            <div t-if="not partner.about and partner.function" style="margin-bottom: 20px; text-align: left;">
                                <p style="margin: 0; color: #374151; font-size: 0.9375rem; line-height: 1.6;">
                                    <t t-esc="partner.function"/>
                                </p>
                            </div>
                            
                            <!-- Specialties Section -->
                            <t t-if="partner.speciality_ids">
                                <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid rgba(0,0,0,0.1);">
                                    <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 12px;">
                                        <i class="fa fa-eye" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                        <span t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-weight: 600; font-size: 0.875rem;'">Specialties:</span>
                                    </div>
                                    <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                                        <t t-foreach="partner.speciality_ids" t-as="speciality">
                                            <span t-att-style="'background-color: rgba(59, 130, 246, 0.1); color: ' + (partner.secondary_color or '#3b82f6') + '; border: 1px solid rgba(59, 130, 246, 0.3); padding: 6px 12px; border-radius: 20px; font-size: 0.8125rem; font-weight: 500;'">
                                                <t t-esc="speciality.name"/>
                                            </span>
                                        </t>
                                    </div>
                                </div>
                            </t>
                            
                            <!-- Contact Information Section -->
                            <div style="margin-top: 20px; padding-top: 20px; border-top: 1px solid rgba(0,0,0,0.1);">
                                <!-- Phone & Email Row -->
                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px; margin-bottom: 16px;">
                                    <!-- Primary Phone -->
                                    <div t-if="partner.phone" style="text-align: left;">
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                            <i class="fa fa-phone" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                            <span style="color: #6b7280; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Primary Phone</span>
                                        </div>
                                        <p t-att-style="'color: ' + (partner.secondary_color or '#374151') + '; font-size: 0.875rem; font-weight: 500; margin: 0;'">
                                            <t t-esc="partner.phone"/>
                                        </p>
                                    </div>
                                    
                                    <!-- Mobile Phone -->
                                    <div t-if="partner.mobile" style="text-align: left;">
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                            <i class="fa fa-mobile" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                            <span style="color: #6b7280; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Mobile</span>
                                        </div>
                                        <p t-att-style="'color: ' + (partner.secondary_color or '#374151') + '; font-size: 0.875rem; font-weight: 500; margin: 0;'">
                                            <t t-esc="partner.mobile"/>
                                        </p>
                                    </div>
                                    
                                    <!-- Email -->
                                    <div t-if="partner.email" style="text-align: left;">
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                            <i class="fa fa-envelope" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                            <span style="color: #6b7280; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Email</span>
                                        </div>
                                        <p t-att-style="'color: ' + (partner.secondary_color or '#374151') + '; font-size: 0.875rem; font-weight: 500; margin: 0;'">
                                            <t t-esc="partner.email"/>
                                        </p>
                                    </div>
                                </div>
                                
                                <!-- Address, Company & Position Row -->
                                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px;">
                                    <!-- Address -->
                                    <div t-if="partner.street or partner.city or partner.state_id or partner.zip or partner.country_id" style="text-align: left;">
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                            <i class="fa fa-map-marker" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                            <span style="color: #6b7280; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Address</span>
                                        </div>
                                        <p t-att-style="'color: ' + (partner.secondary_color or '#374151') + '; font-size: 0.875rem; font-weight: 500; margin: 0 0 8px 0; line-height: 1.5;'">
                                            <t t-esc="partner.street" t-if="partner.street"/>
                                            <t t-if="partner.street and partner.city">, </t>
                                            <t t-esc="partner.city" t-if="partner.city"/>
                                            <t t-if="partner.city and partner.state_id">, </t>
                                            <t t-esc="partner.state_id.name" t-if="partner.state_id"/>
                                            <t t-if="partner.zip"> </t>
                                            <t t-esc="partner.zip" t-if="partner.zip"/>
                                            <t t-if="partner.country_id"><br/><t t-esc="partner.country_id.name"/></t>
                                        </p>
                                        <t t-set="google_maps_url" t-value="partner._get_google_maps_url()"/>
                                        <a t-if="google_maps_url" 
                                           t-att-href="google_maps_url" 
                                           target="_blank" 
                                           t-att-style="'background-color: ' + (partner.secondary_color or '{secondary_color}') + '; color: white; padding: 6px 12px; border-radius: 9999px; font-size: 0.8125rem; font-weight: 600; text-decoration: none; display: inline-flex; align-items: center; gap: 4px;'">
                                            <i class="fa fa-map" style="font-size: 12px;"></i>Directions
                                        </a>
                                    </div>
                                    
                                    <!-- Position -->
                                    <div t-if="partner.function" style="text-align: left;">
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                            <i class="fa fa-briefcase" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                            <span style="color: #6b7280; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Position</span>
                                        </div>
                                        <p t-att-style="'color: ' + (partner.secondary_color or '#374151') + '; font-size: 0.875rem; font-weight: 500; margin: 0;'">
                                            <t t-esc="partner.function"/>
                                        </p>
                                    </div>
                                    
                                    <!-- Company -->
                                    <div t-if="partner.company_name" style="text-align: left;">
                                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                            <i class="fa fa-building" t-att-style="'color: ' + (partner.secondary_color or '{secondary_color}') + '; font-size: 14px;'"></i>
                                            <span style="color: #6b7280; font-size: 0.75rem; font-weight: 600; text-transform: uppercase;">Company</span>
                                        </div>
                                        <p t-att-style="'color: ' + (partner.secondary_color or '#374151') + '; font-size: 0.875rem; font-weight: 500; margin: 0;'">
                                            <t t-esc="partner.company_name"/>
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
"""
                template = template[:about_section_start] + new_about_section + template[about_section_end:]
        
        # Add creative template CSS with faster mobile animations
        creative_css = f"""
                <style>
                    @keyframes floatAnim1 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(-30px) translateX(20px); }}
                        66% {{ transform: translateY(30px) translateX(-20px); }}
                    }}
                    @keyframes floatAnim2 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(25px) translateX(-15px); }}
                        66% {{ transform: translateY(-25px) translateX(15px); }}
                    }}
                    @keyframes floatAnim3 {{
                        0%, 100% {{ transform: rotate(45deg) translateY(0px) translateX(0px); }}
                        33% {{ transform: rotate(225deg) translateY(-20px) translateX(10px); }}
                        66% {{ transform: rotate(405deg) translateY(20px) translateX(-10px); }}
                    }}
                    @keyframes floatAnim4 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(-35px) translateX(15px); }}
                        66% {{ transform: translateY(35px) translateX(-15px); }}
                    }}
                    @keyframes floatAnim5 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(30px) translateX(-25px); }}
                        66% {{ transform: translateY(-30px) translateX(25px); }}
                    }}
                    
                    /* Faster mobile animations */
                    @keyframes floatAnimMobile1 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(-40px) translateX(30px); }}
                        66% {{ transform: translateY(40px) translateX(-30px); }}
                    }}
                    @keyframes floatAnimMobile2 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(35px) translateX(-25px); }}
                        66% {{ transform: translateY(-35px) translateX(25px); }}
                    }}
                    @keyframes floatAnimMobile3 {{
                        0%, 100% {{ transform: rotate(45deg) translateY(0px) translateX(0px); }}
                        33% {{ transform: rotate(225deg) translateY(-30px) translateX(20px); }}
                        66% {{ transform: rotate(405deg) translateY(30px) translateX(-20px); }}
                    }}
                    @keyframes floatAnimMobile4 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(-45px) translateX(25px); }}
                        66% {{ transform: translateY(45px) translateX(-25px); }}
                    }}
                    @keyframes floatAnimMobile5 {{
                        0%, 100% {{ transform: translateY(0px) translateX(0px); }}
                        33% {{ transform: translateY(40px) translateX(-35px); }}
                        66% {{ transform: translateY(-40px) translateX(35px); }}
                    }}
                    
                    .vcard-template-creative #wrap {{
                        position: relative;
                        overflow: hidden;
                    }}
                    
                    .vcard-template-creative .container-fluid {{
                        position: relative;
                        z-index: 1;
                    }}
                    
                    /* Hide mobile floating elements on desktop */
                    @media (min-width: 769px) {{
                        .float-circle-mobile-1,
                        .float-circle-mobile-2,
                        .float-circle-mobile-3,
                        .float-square-mobile-1,
                        .float-triangle-mobile-1 {{
                            display: none;
                        }}
                    }}
                    
                    /* Show mobile elements and make animations faster on mobile */
                    @media (max-width: 768px) {{
                        .float-circle-mobile-1,
                        .float-circle-mobile-2,
                        .float-circle-mobile-3,
                        .float-square-mobile-1,
                        .float-triangle-mobile-1 {{
                            display: block;
                        }}
                        .float-circle-1, .float-circle-2, .float-circle-3,
                        .float-square-1, .float-triangle-1 {{
                            animation-duration: 12s !important;
                        }}
                    }}
                    
                    /* Button animations and maximum rounding for Creative template */
                    .vcard-template-creative a[href],
                    .vcard-template-creative button,
                    .vcard-template-creative .btn,
                    .vcard-template-creative a[data-toggle],
                    .vcard-template-creative .service-request-btn,
                    .vcard-template-creative .qr-share-btn {{
                        border-radius: 9999px !important;
                        animation: subtleButtonFloat 3s ease-in-out infinite;
                        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
                    }}
                    
                    @keyframes subtleButtonFloat {{
                        0%, 100% {{
                            transform: translateY(0px);
                        }}
                        50% {{
                            transform: translateY(-2px);
                        }}
                    }}
                    
                    .vcard-template-creative a[href]:hover,
                    .vcard-template-creative button:hover,
                    .vcard-template-creative .btn:hover,
                    .vcard-template-creative a[data-toggle]:hover,
                    .vcard-template-creative .service-request-btn:hover,
                    .vcard-template-creative .qr-share-btn:hover {{
                        animation: none;
                        transform: translateY(-3px) scale(1.02);
                        box-shadow: 0 8px 16px rgba(0,0,0,0.15) !important;
                        transition: all 0.6s cubic-bezier(0.4, 0, 0.2, 1) !important;
                    }}
                    
                    /* Override inline styles for border-radius on buttons */
                    .vcard-template-creative a[style*="border-radius"] {{
                        border-radius: 9999px !important;
                    }}
                </style>
"""
        
        # Insert CSS before the last closing tags
        last_closing_pos = template.rfind('</t>')
        if last_closing_pos != -1:
            template = template[:last_closing_pos] + creative_css + '\n        ' + template[last_closing_pos:]
        
        return template
