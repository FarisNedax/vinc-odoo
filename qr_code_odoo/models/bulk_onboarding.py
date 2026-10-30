from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import json
import secrets
import string
import logging
from datetime import datetime, timedelta
import base64
import csv
import io
import re

_logger = logging.getLogger(__name__)

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
    _logger.warning("openpyxl not installed - Excel file upload will not work")

# Class-level cache for mailing lists during batch processing
# Key: batch_id, Value: mailing.list record
_batch_mailing_list_cache = {}


class BulkOnboardingBatch(models.Model):
    _name = 'bulk.onboarding.batch'
    _description = 'Bulk Onboarding Batch'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Batch Name', required=True, default=lambda self: f"Batch {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    created_by = fields.Many2one('res.users', string='Created By', required=True, default=lambda self: self.env.user)
    
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('partial', 'Partially Completed')
    ], string='Status', default='draft', tracking=True)
    
    total_reps = fields.Integer(string='Total Reps', compute='_compute_totals', store=True)
    completed_reps = fields.Integer(string='Completed Reps', compute='_compute_totals', store=True)
    failed_reps = fields.Integer(string='Failed Reps', compute='_compute_totals', store=True)
    invited_reps = fields.Integer(string='Invited Reps', compute='_compute_totals', store=True)
    activated_reps = fields.Integer(string='Activated Reps', compute='_compute_totals', store=True)
    
    # Progress tracking fields
    progress_current = fields.Integer(string='Current Progress', default=0, help='Number of users processed so far')
    progress_total = fields.Integer(string='Total to Process', default=0, help='Total number of users to process')
    progress_percent = fields.Float(string='Progress %', compute='_compute_progress', store=False)
    
    common_data = fields.Text(string='Common Data (JSON)', help='Shared company/branding data for all reps')
    rep_data = fields.Text(string='Rep Data (JSON)', help='Individual rep data')
    error_log = fields.Text(string='Error Log (JSON)', help='Errors encountered during processing')
    
    rep_ids = fields.One2many('bulk.onboarding.rep', 'batch_id', string='Reps')
    
    processing_started_at = fields.Datetime(string='Processing Started At')
    processing_completed_at = fields.Datetime(string='Processing Completed At')
    
    @api.depends('rep_ids', 'rep_ids.status')
    def _compute_totals(self):
        for batch in self:
            batch.total_reps = len(batch.rep_ids)
            batch.completed_reps = len(batch.rep_ids.filtered(lambda r: r.status == 'completed'))
            batch.failed_reps = len(batch.rep_ids.filtered(lambda r: r.status == 'failed'))
            batch.invited_reps = len(batch.rep_ids.filtered(lambda r: r.status in ['invited', 'activated', 'completed']))
            batch.activated_reps = len(batch.rep_ids.filtered(lambda r: r.status in ['activated', 'completed']))
    
    @api.depends('progress_current', 'progress_total')
    def _compute_progress(self):
        for batch in self:
            if batch.progress_total > 0:
                batch.progress_percent = (batch.progress_current / batch.progress_total) * 100.0
            else:
                batch.progress_percent = 0.0
    
    def get_common_data(self):
        """Parse and return common_data as dict"""
        if not self.common_data:
            return {}
        try:
            return json.loads(self.common_data)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_common_data(self, data):
        """Set common_data from dict"""
        self.common_data = json.dumps(data)
    
    def get_rep_data(self):
        """Parse and return rep_data as list of dicts"""
        if not self.rep_data:
            return []
        try:
            return json.loads(self.rep_data)
        except (json.JSONDecodeError, TypeError):
            return []
    
    def set_rep_data(self, data):
        """Set rep_data from list of dicts"""
        self.rep_data = json.dumps(data)
    
    def get_error_log(self):
        """Parse and return error_log as list"""
        if not self.error_log:
            return []
        try:
            return json.loads(self.error_log)
        except (json.JSONDecodeError, TypeError):
            return []
    
    def add_error(self, rep_email, error_message):
        """Add error to error log"""
        errors = self.get_error_log()
        errors.append({
            'rep_email': rep_email,
            'error': error_message,
            'timestamp': datetime.now().isoformat()
        })
        self.error_log = json.dumps(errors)

    @staticmethod
    def _clean_email(raw):
        """Normalise an email pulled from a CSV / Excel / form field.

        Spreadsheets routinely inject stray whitespace (e.g.
        ``robert@ noeticerp.com`` — a space after the @) and Excel sometimes
        concatenates trailing digits. We strip ALL internal whitespace first
        — that single step is what turned the Jobe-batch failure into a
        match against the real ``robert@noeticerp.com`` user — then extract
        the valid email pattern. Returns '' when nothing usable is left.
        """
        if not raw:
            return ''
        email = re.sub(r'\s+', '', str(raw)).strip().lower()
        match = re.match(r'^([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', email)
        if match:
            return match.group(1)
        # No clean pattern — drop trailing digits Excel may have appended.
        return re.sub(r'(\d+)$', '', email).strip()

    def _refresh_status(self):
        """Re-derive batch status after a rep was edited / retried / removed.

        Only meaningful once a batch has actually been processed — a draft or
        in-flight batch keeps its lifecycle status. Mirrors the terminal-state
        logic in _process_batch so a fixed-and-retried row can move a batch
        from 'failed' back to 'completed' / 'partial'.
        """
        self.ensure_one()
        if self.status in ('draft', 'pending', 'processing'):
            return
        if not self.rep_ids:
            return
        if self.failed_reps == 0:
            self.status = 'completed'
        elif self.invited_reps:
            self.status = 'partial'
        else:
            self.status = 'failed'
    
    def action_start_processing(self):
        """Start processing the batch - returns immediately, cron job will process"""
        self.ensure_one()  # Ensure we're working with a single record
        
        if self.status != 'draft':
            raise UserError("Only draft batches can be processed")
        
        if not self.rep_ids:
            raise UserError("No reps to process. Please add rep data first.")
        
        # Clear any existing cache for this batch
        global _batch_mailing_list_cache
        if self.id in _batch_mailing_list_cache:
            del _batch_mailing_list_cache[self.id]
        
        # Set status to processing and initialize progress tracking
        self.write({
            'status': 'processing',
            'processing_started_at': datetime.now(),
            'progress_current': 0,
            'progress_total': len(self.rep_ids),
        })
        self.env.cr.commit()
        
        _logger.info(f"Batch {self.id} queued for processing. Total users: {len(self.rep_ids)}")
        
        # Return immediately - cron job will pick this up and process it
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Processing Started',
                'message': f'Batch processing started! Processing {len(self.rep_ids)} users in the background. You can navigate away - refresh the batch list to see progress.',
                'type': 'success',
                'sticky': False,
            }
        }
    
    def _process_batch(self):
        """Process all reps in the batch"""
        global _batch_mailing_list_cache
        self.ensure_one()  # Ensure we're working with a single record
        
        common_data = self.get_common_data()
        
        # Pre-create mailing list if needed (to avoid race conditions during parallel processing)
        if common_data.get('show_form', False):
            mailing_list_name = common_data.get('mailing_list_name', 'Leads')
            mailing_list = self.env['mailing.list'].sudo().search([
                ('name', '=ilike', mailing_list_name)
            ], limit=1)
            
            if not mailing_list:
                mailing_list = self.env['mailing.list'].sudo().create({
                    'name': mailing_list_name,
                    'is_public': True
                })
            
            # Store in class-level cache keyed by batch ID
            _batch_mailing_list_cache[self.id] = mailing_list
        
        # Track emails we've processed in this batch to prevent duplicates
        processed_emails = set()
        
        # Track progress
        total_reps = len(self.rep_ids)
        processed_count = 0
        
        for rep in self.rep_ids:
            if rep.status in ['completed', 'failed']:
                continue
            
            # Skip if rep already has a user (might have been created in a previous attempt)
            if rep.user_id:
                _logger.info(f"Rep {rep.email} already has user {rep.user_id.id}. Skipping user creation.")
                rep.status = 'invited'
                continue
            
            # Get and clean email
            rep_data = rep.get_rep_data()
            email = rep_data.get('email', '').strip().lower()
            
            # Check for duplicates within this batch processing
            if email in processed_emails:
                _logger.warning(f"Duplicate email {email} detected during batch processing. Skipping rep {rep.id}.")
                rep.status = 'failed'
                rep.error_message = f"Duplicate email {email} in this batch"
                self.add_error(rep.email, f"Duplicate email in batch")
                continue
            
            processed_emails.add(email)
            
            try:
                self._create_rep_account(rep, common_data, rep_data)
                rep.status = 'invited'
                processed_count += 1
                
                # Update progress
                self.progress_current = processed_count
                
                # Commit every 10 users (or on last user) to reduce DB overhead
                if processed_count % 10 == 0 or processed_count == total_reps:
                    self.env.cr.commit()
                    _logger.info(f"Batch {self.id}: Processed {processed_count}/{total_reps} users")
            except Exception as e:
                _logger.error(f"Error processing rep {rep.email}: {str(e)}", exc_info=True)
                # Rollback the failed transaction
                self.env.cr.rollback()
                try:
                    # Save error state in a new transaction
                    rep.status = 'failed'
                    rep.error_message = str(e)
                    self.add_error(rep.email, str(e))
                    processed_count += 1
                    self.progress_current = processed_count
                    # Commit the error state
                    self.env.cr.commit()
                except Exception as save_error:
                    # If saving error state fails, log it and rollback
                    _logger.error(f"Failed to save error state for {rep.email}: {str(save_error)}", exc_info=True)
                    self.env.cr.rollback()
                    # Still increment counter to prevent infinite loop
                    processed_count += 1
                    self.progress_current = processed_count
                    try:
                        self.env.cr.commit()
                    except Exception as commit_err:
                        _logger.warning("Bulk onboarding commit failed for rep %s: %s", email, commit_err)
                # Remove from processed set so it can be retried if needed
                processed_emails.discard(email)
        
        # Update batch status
        if self.failed_reps == 0:
            self.status = 'completed'
        elif self.completed_reps > 0:
            self.status = 'partial'
        else:
            self.status = 'failed'
        
        self.processing_completed_at = datetime.now()
        self.env.cr.commit()
        
        # Clean up cache for this batch
        if self.id in _batch_mailing_list_cache:
            del _batch_mailing_list_cache[self.id]
        
        # Send completion email to admin
        self._send_completion_email()
    
    @api.model
    def _cron_process_pending_batches(self):
        """Cron job to process pending batches in the background"""
        # Find batches that are in 'processing' status
        batches = self.search([('status', '=', 'processing')], limit=5)
        
        if not batches:
            return
        
        _logger.info(f"Cron: Found {len(batches)} pending batch(es) to process")
        
        for batch in batches:
            try:
                # Use the batch creator's context for processing
                creator = batch.created_by
                if not creator:
                    _logger.error(f"Cron: No creator found for batch {batch.id}. Skipping.")
                    batch.sudo().write({
                        'status': 'failed',
                        'error_log': json.dumps(batch.get_error_log() + [{
                            'error': 'No creator found for this batch',
                            'timestamp': datetime.now().isoformat()
                        }])
                    })
                    self.env.cr.commit()
                    continue
                
                _logger.info(f"Cron: Processing batch {batch.id} ({batch.name}) - {batch.progress_current}/{batch.progress_total} users (as {creator.login})")
                
                # Process batch with creator user context
                batch.with_user(creator)._process_batch()
                _logger.info(f"Cron: Completed batch {batch.id}")
            except Exception as e:
                _logger.error(f"Cron error processing batch {batch.id}: {str(e)}", exc_info=True)
                # Mark batch as failed and log the error
                batch.sudo().write({
                    'status': 'failed',
                    'error_log': json.dumps(batch.get_error_log() + [{
                        'error': f'Cron processing error: {str(e)}',
                        'timestamp': datetime.now().isoformat()
                    }])
                })
                # Mark all pending reps as failed
                pending_reps = batch.rep_ids.filtered(lambda r: r.status == 'pending')
                if pending_reps:
                    pending_reps.sudo().write({
                        'status': 'failed',
                        'error_message': f'Batch processing failed: {str(e)}'
                    })
                self.env.cr.commit()
    
    def _create_rep_account(self, rep_record, common_data, rep_data):
        """Create user account and Card for a rep"""
        email = self._clean_email(rep_data.get('email', ''))

        if not email:
            raise ValidationError("Email is required for rep")

        # Validate email format
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            raise ValidationError(f"Invalid email format: {rep_data.get('email', '')}")
        
        # Check if user already exists (case-insensitive) - including uncommitted records
        # First check in database
        existing_user = self.env['res.users'].sudo().search([
            ('login', '=ilike', email)
        ], limit=1)
        
        # Also check if we're trying to create a user that was just created in this batch
        # (in the same transaction, before commit)
        if not existing_user:
            # Check all reps in this batch that have already been processed
            processed_reps = self.rep_ids.filtered(lambda r: r.user_id and r.user_id.login.lower() == email.lower())
            if processed_reps:
                existing_user = processed_reps[0].user_id
                _logger.warning(f"User {email} is being created again in the same batch. Found in rep {processed_reps[0].id}")
        
        # Bulk onboarding now *requires* the email to belong to an existing
        # Odoo user. Vinc is an app on top of Odoo — users come from the
        # standard Settings → Users flow. If the email isn't found, we fail
        # this row so the admin can either add the user to Odoo first or
        # remove the row from the CSV. Other rows in the batch keep going
        # via the existing per-row error handling.
        if not existing_user:
            raise ValidationError(
                f"No Odoo user found for {email}. Add this person under "
                f"Settings → Users & Companies → Users first, then re-run "
                f"the bulk upload."
            )

        # Defend against duplicate rep records for the same user in one batch.
        existing_rep = self.env['bulk.onboarding.rep'].sudo().search([
            ('user_id', '=', existing_user.id),
            ('batch_id', '=', self.id),
            ('id', '!=', rep_record.id),
        ], limit=1)
        if existing_rep:
            raise ValidationError(
                f"User {email} appears more than once in this batch."
            )

        user = existing_user
        rep_record.user_id = user.id

        # Always create a new vCard, even if the user already has one. Per
        # product decision: bulk uploads can legitimately seed a second card
        # (different role, different show, different audience).
        common_data = self.get_common_data()
        vcard_vals = self._prepare_vcard_vals(common_data, rep_data, user)
        vcard = self.env['partner.vcard'].sudo().with_context(skip_vcard_limit_check=True).create(vcard_vals)

        if vcard_vals.get('banner_image'):
            vcard.sudo()._update_banner_attachment_if_image_changed()
            self.env.cr.flush()

        # Publish the card immediately so a bulk card behaves like a normally
        # created one: this generates its website page and makes the public URL
        # live. Without it the card stays is_published=False — counted in card
        # lists but absent from published-only stats and not viewable, which
        # reads to the admin as "the upload created a card that doesn't work".
        try:
            vcard.sudo().is_published = True
        except Exception as e:
            _logger.warning(
                "Bulk onboarding: could not auto-publish vCard %s for %s: %s",
                vcard.id, email, e,
            )

        rep_record.vcard_id = vcard.id

        # No magic-link token needed: the user already has a working Odoo
        # login. The invitation email links straight to the new vCard form.
        self._send_invitation_email(user, rep_data, None, common_data, vcard=vcard)
        
        return user
    
    def _generate_magic_link_token(self, email, user_id):
        """Generate secure magic link token"""
        # Generate a secure random token
        token = secrets.token_urlsafe(32)
        
        # Store token in database and link it to the user
        self.env['bulk.onboarding.token'].sudo().create({
            'token': token,
            'email': email,
            'user_id': user_id,
            'batch_id': self.id,
            'expires_at': datetime.now() + timedelta(days=7),
            'used': False
        })
        
        return token
    
    def _prepare_vcard_vals(self, common_data, rep_data, user):
        """Prepare vCard values from common and rep data"""
        
        # Merge common data with rep-specific data
        vals = {
            'name': rep_data.get('name', '').strip(),
            'email': rep_data.get('email', '').strip().lower(),
            'phone': rep_data.get('phone', '').strip() or rep_data.get('mobile', '').strip(),
            'mobile': rep_data.get('mobile', '').strip(),
            'function': rep_data.get('function', '').strip() or rep_data.get('job_title', '').strip(),
            'company_name': common_data.get('company_name', ''),
            'website': common_data.get('company_website', ''),
            'about': rep_data.get('about', '').strip() or common_data.get('default_about', ''),
            'primary_color': '#ffffff',  # Always white for backgrounds
            'secondary_color': common_data.get('brand_color', '#4C75A3'),  # Default to Vinc blue
            'website_template': common_data.get('website_template', 'modern'),
            'qr_pattern': common_data.get('qr_pattern', 'square'),
            'show_services': common_data.get('show_services', False),
            'show_reviews': common_data.get('show_reviews', True) if 'show_reviews' in common_data else True,
            # Address: use rep-specific if provided, otherwise use company defaults
            'street': rep_data.get('street', '') or common_data.get('default_street', ''),
            'street2': rep_data.get('street2', '') or common_data.get('default_street2', ''),
            'city': rep_data.get('city', '') or common_data.get('default_city', ''),
            'zip': rep_data.get('zip', '') or common_data.get('default_zip', ''),
            'country_id': rep_data.get('country_id') or common_data.get('country_id') or False,
            'state_id': rep_data.get('state_id') or common_data.get('state_id') or False,
            'linkedin_url': rep_data.get('linkedin_url', '') or common_data.get('linkedin_url_company', ''),
            'linkedin_url_company': common_data.get('linkedin_url_company', ''),
            'facebook_url': rep_data.get('facebook_url', '') or common_data.get('facebook_url_company', ''),
            'facebook_url_company': common_data.get('facebook_url_company', ''),
            'twitter_url': rep_data.get('twitter_url', '') or common_data.get('twitter_url_company', ''),
            'twitter_url_company': common_data.get('twitter_url_company', ''),
            'instagram_url': rep_data.get('instagram_url', '') or common_data.get('instagram_url_company', ''),
            'instagram_url_company': common_data.get('instagram_url_company', ''),
            'whatsapp_url': rep_data.get('whatsapp_url', ''),
            'youtube_url': rep_data.get('youtube_url', ''),
            'calendly_url': rep_data.get('calendly_url', ''),
        }
        
        # Handle website slug
        website_slug = rep_data.get('website_slug', '').strip()
        if not website_slug:
            # Auto-generate from name
            name_slug = rep_data.get('name', '').lower().replace(' ', '-')
            import re
            name_slug = re.sub(r'[^a-z0-9-]', '', name_slug)
            website_slug = name_slug or f"rep-{user.id}"
        
        # Ensure uniqueness - use raw SQL to bypass any search overrides and check globally
        base_slug = website_slug
        counter = 1
        while True:
            # Use raw SQL to check for existing slug globally (bypasses search overrides)
            self.env.cr.execute("""
                SELECT id FROM partner_vcard
                WHERE website_slug = %s
                LIMIT 1
            """, (website_slug,))
            if not self.env.cr.fetchone():
                break  # Slug is unique, exit loop
            website_slug = f"{base_slug}-{counter}"
            counter += 1
            # Safety check to prevent infinite loop
            if counter > 1000:
                # Fallback to using user ID to ensure uniqueness
                website_slug = f"{base_slug}-{user.id}"
                break
        
        vals['website_slug'] = website_slug
        
        # Handle profile image (expect base64 encoded string)
        if rep_data.get('image_url'):
            # If it's a base64 string, use it directly; otherwise encode it
            if isinstance(rep_data['image_url'], str) and rep_data['image_url'].startswith('data:image'):
                # Extract base64 part from data URL
                vals['image_url'] = rep_data['image_url'].split(',')[1] if ',' in rep_data['image_url'] else rep_data['image_url']
            else:
                vals['image_url'] = rep_data['image_url']
        elif common_data.get('default_logo'):
            vals['image_url'] = common_data['default_logo']
        else:
            # Use default profile image if no image is provided
            default_profile = self.env['partner.vcard']._get_default_profile_image()
            if default_profile:
                vals['image_url'] = default_profile
        
        # Handle banner image
        if common_data.get('banner_image'):
            vals['banner_image'] = common_data['banner_image']
        else:
            # Use default banner if no banner is provided
            default_banner = self.env['partner.vcard']._get_default_banner_image()
            if default_banner:
                vals['banner_image'] = default_banner
        
        # Handle QR logo
        if common_data.get('qr_logo'):
            vals['qr_logo'] = common_data['qr_logo']
        
        # Lead collection settings
        if common_data.get('show_form', False):
            # Use cached mailing list from batch (created in _process_batch) to avoid race conditions
            # Use class-level cache keyed by batch ID
            global _batch_mailing_list_cache
            cached_mailing_list = _batch_mailing_list_cache.get(self.id) if self.id else None
            if cached_mailing_list:
                mailing_list = cached_mailing_list
            else:
                # Fallback: search for existing mailing list
                mailing_list_name = common_data.get('mailing_list_name', 'Leads')
                mailing_list = self.env['mailing.list'].sudo().search([
                    ('name', '=ilike', mailing_list_name)
                ], limit=1)
                
                if not mailing_list:
                    mailing_list = self.env['mailing.list'].sudo().create({
                        'name': mailing_list_name,
                        'is_public': True
                    })
                    # Cache it for subsequent Cards in this batch
                    # Store in class-level cache keyed by batch ID
                    if self.id:
                        _batch_mailing_list_cache[self.id] = mailing_list
            
            vals['show_form'] = True
            vals['mailing_list_id'] = mailing_list.id
            vals['lead_button_label'] = common_data.get('lead_button_label', 'Get In Touch')
            vals['form_thank_you_message'] = common_data.get('form_thank_you_message', '')
            vals['notify_on_new_lead'] = common_data.get('notify_on_new_lead', True)
            vals['intro_email_enabled'] = common_data.get('intro_email_enabled', False)
            vals['enable_instant_leadback'] = common_data.get('enable_instant_leadback', False)
            
            # Leadback settings
            if common_data.get('enable_instant_leadback', False):
                vals['leadback_send_email'] = common_data.get('leadback_send_email', False)
                vals['leadback_enable_messaging'] = common_data.get('leadback_enable_messaging', False)
                
                # Handle leadback channels - convert channel codes to IDs
                leadback_channels = common_data.get('leadback_channels', [])
                if leadback_channels and isinstance(leadback_channels, list):
                    channel_ids = []
                    for channel_code in leadback_channels:
                        if channel_code:  # Skip empty values
                            channel = self.env['leadback.messaging.channel'].sudo().search([
                                ('code', '=', channel_code)
                            ], limit=1)
                            if channel:
                                channel_ids.append(channel.id)
                    
                    if channel_ids:
                        vals['leadback_channels'] = [(6, 0, channel_ids)]
        
        return vals
    
    def _send_invitation_email(self, user, rep_data, token, common_data, vcard=None):
        """Notify the rep that their card is ready.

        Existing-user-only flow: the rep already has an Odoo login, so the
        email is just a "your card is ready, click to view" notification.
        The deep link routes through Odoo's standard auth — if they're not
        logged in, /web/login takes them there and back.

        `token` is kept in the signature for backward compatibility with
        action_resend_invitation but is unused in the new flow.
        """
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        if vcard is None:
            # Resend path — look up the card linked to this rep.
            rep = self.env['bulk.onboarding.rep'].sudo().search(
                [('user_id', '=', user.id), ('batch_id', '=', self.id)], limit=1
            )
            vcard = rep.vcard_id if rep else self.env['partner.vcard']
        if vcard:
            card_link = f"{base_url}/web#id={vcard.id}&model=partner.vcard&view_type=form"
        else:
            card_link = f"{base_url}/web"

        company_name = common_data.get('company_name', '') or 'Your Company'

        template = self.env.ref('qr_code_odoo.bulk_onboarding_invitation_email', raise_if_not_found=False)
        if template:
            template.sudo().with_context(
                card_link=card_link,
                current_year=datetime.now().year,
                company_name=company_name,
            ).send_mail(user.id, force_send=True)
    
    def _send_completion_email(self):
        """Send completion summary email to admin"""
        admin_email = self.created_by.email or self.created_by.login
        if not admin_email:
            return
        
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', 'http://localhost:8069')
        batch_url = f"{base_url}/bulk-onboard/batch/{self.id}"
        
        template = self.env.ref('qr_code_odoo.bulk_onboarding_completion_email', raise_if_not_found=False)
        
        if template:
            # Preload related fields to ensure they're available in the template
            batch_record = self.sudo().browse(self.id)
            _ = batch_record.name if batch_record else None
            _ = batch_record.total_reps if batch_record else None
            _ = batch_record.invited_reps if batch_record else None
            _ = batch_record.activated_reps if batch_record else None
            _ = batch_record.completed_reps if batch_record else None
            _ = batch_record.failed_reps if batch_record else None
            if batch_record.created_by:
                _ = batch_record.created_by.name if batch_record.created_by else None
                _ = batch_record.created_by.email if batch_record.created_by else None
                _ = batch_record.created_by.login if batch_record.created_by else None
            
            # Render subject manually to ensure it works
            batch_name = self.name or 'Batch'
            rendered_subject = f"Bulk Onboarding Batch \"{batch_name}\" Completed"
            
            # Use send_mail with email_values to override subject
            template.sudo().with_context(
                batch_url=batch_url, 
                current_year=datetime.now().year
            ).send_mail(self.id, force_send=True, email_values={
                'subject': rendered_subject,
            })
        else:
            # Fallback email
            mail_values = {
                'subject': f'Bulk Onboarding Batch "{self.name}" Completed',
                'body_html': f"""
                <p>Your bulk onboarding batch "{self.name}" has been processed.</p>
                <p><strong>Summary:</strong></p>
                <ul>
                    <li>Total Reps: {self.total_reps}</li>
                    <li>Successfully Invited: {self.invited_reps}</li>
                    <li>Failed: {self.failed_reps}</li>
                </ul>
                <p>View the batch details in your dashboard.</p>
                """,
                'email_to': admin_email,
                'email_from': self.env['partner.vcard']._get_notification_email(user=self.env.user),
            }
            self.env['mail.mail'].sudo().create(mail_values).send()
    
    @api.model
    def parse_csv_file(self, file_content, skip_explanation_row=True):
        """Parse CSV file and return list of dicts
        Supports format with:
        - Row 1: Explanations (optional, skipped if skip_explanation_row=True)
        - Row 2: Headers
        - Row 3+: Data rows
        """
        try:
            # Decode if bytes
            if isinstance(file_content, bytes):
                file_content = file_content.decode('utf-8')
            
            # Handle BOM
            if file_content.startswith('\ufeff'):
                file_content = file_content[1:]
            
            lines = file_content.strip().split('\n')
            
            # Skip row 1 (explanations) if present
            start_row = 1 if skip_explanation_row and len(lines) > 1 else 0
            
            # Get headers from row 2 (or row 1 if no explanation row)
            if len(lines) <= start_row:
                raise ValidationError("CSV file is empty or missing headers")
            
            header_line = lines[start_row]
            headers = [h.strip() for h in csv.reader([header_line]).__next__()]
            
            # Parse data rows starting from row 3 (or row 2 if no explanation row)
            rows = []
            for line in lines[start_row + 1:]:
                if not line.strip():
                    continue  # Skip empty lines
                
                reader = csv.reader([line])
                values = next(reader)
                
                # Create dict from headers and values
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(values) and values[i]:
                        value = values[i].strip()
                        # For email fields, normalise (strips stray spaces such
                        # as the "robert@ noeticerp.com" case) via the shared helper.
                        if header.lower() in ['email', 'email address']:
                            value = self._clean_email(value)
                        row_dict[header] = value
                    else:
                        row_dict[header] = ''
                
                # Map country and state names to IDs if provided
                if row_dict.get('country') and not row_dict.get('country_id'):
                    country = self.env['res.country'].sudo().search([
                        ('name', '=ilike', row_dict['country'].strip())
                    ], limit=1)
                    if country:
                        row_dict['country_id'] = country.id
                    # Remove the 'country' key as we use 'country_id'
                    row_dict.pop('country', None)
                
                if row_dict.get('state') and not row_dict.get('state_id'):
                    state = self.env['res.country.state'].sudo().search([
                        ('name', '=ilike', row_dict['state'].strip())
                    ], limit=1)
                    if state:
                        row_dict['state_id'] = state.id
                    # Remove the 'state' key as we use 'state_id'
                    row_dict.pop('state', None)
                
                # Only add row if it has at least name or email
                if row_dict.get('name') or row_dict.get('email'):
                    rows.append(row_dict)
            
            return rows
        except Exception as e:
            _logger.error(f"Error parsing CSV: {str(e)}", exc_info=True)
            raise ValidationError(f"Error parsing CSV file: {str(e)}")
    
    @api.model
    def parse_excel_file(self, file_content, skip_explanation_row=True):
        """Parse Excel file and return list of dicts
        Supports format with:
        - Row 1: Explanations (optional, skipped if skip_explanation_row=True)
        - Row 2: Headers
        - Row 3+: Data rows
        """
        if not HAS_OPENPYXL:
            raise ValidationError("Excel file support requires openpyxl. Please install it or use CSV format.")
        
        try:
            workbook = openpyxl.load_workbook(io.BytesIO(file_content))
            sheet = workbook.active
            
            # Skip row 1 (explanations) if present
            header_row = 2 if skip_explanation_row else 1
            data_start_row = 3 if skip_explanation_row else 2
            
            # Get headers from row 2 (or row 1 if no explanation row)
            headers = [cell.value.strip() if cell.value else '' for cell in sheet[header_row]]
            
            rows = []
            for row in sheet.iter_rows(min_row=data_start_row, values_only=False):
                if not any(cell.value for cell in row):
                    continue  # Skip empty rows
                
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(row):
                        value = row[i].value
                        # Convert to string and clean
                        if value is None:
                            row_dict[header] = ''
                        else:
                            # For email fields, ensure proper string conversion and cleaning
                            if header.lower() in ['email', 'email address']:
                                # Convert to string, but handle Excel number formatting
                                if isinstance(value, (int, float)):
                                    # If Excel treated email as number, convert back
                                    raw_email = str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)
                                else:
                                    raw_email = str(value).strip()
                                # Normalise via the shared helper (strips stray spaces).
                                cleaned = self._clean_email(raw_email)
                                row_dict[header] = cleaned if cleaned else raw_email.lower()
                            else:
                                row_dict[header] = str(value).strip() if value else ''
                    else:
                        row_dict[header] = ''
                
                # Map country and state names to IDs if provided
                if row_dict.get('country') and not row_dict.get('country_id'):
                    country = self.env['res.country'].sudo().search([
                        ('name', '=ilike', row_dict['country'].strip())
                    ], limit=1)
                    if country:
                        row_dict['country_id'] = country.id
                    # Remove the 'country' key as we use 'country_id'
                    row_dict.pop('country', None)
                
                if row_dict.get('state') and not row_dict.get('state_id'):
                    state = self.env['res.country.state'].sudo().search([
                        ('name', '=ilike', row_dict['state'].strip())
                    ], limit=1)
                    if state:
                        row_dict['state_id'] = state.id
                    # Remove the 'state' key as we use 'state_id'
                    row_dict.pop('state', None)
                
                # Only add row if it has at least name or email
                if row_dict.get('name') or row_dict.get('email'):
                    rows.append(row_dict)
            
            return rows
        except Exception as e:
            _logger.error(f"Error parsing Excel: {str(e)}", exc_info=True)
            raise ValidationError(f"Error parsing Excel file: {str(e)}")


class BulkOnboardingRep(models.Model):
    _name = 'bulk.onboarding.rep'
    _description = 'Bulk Onboarding Rep'
    _order = 'create_date desc'

    batch_id = fields.Many2one('bulk.onboarding.batch', string='Batch', required=True, ondelete='cascade')
    name = fields.Char(string='Name', required=True)
    email = fields.Char(string='Email', required=True)
    phone = fields.Char(string='Phone')
    
    status = fields.Selection([
        ('pending', 'Pending'),
        ('invited', 'Invited'),
        ('activated', 'Activated'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], string='Status', default='pending')
    
    user_id = fields.Many2one('res.users', string='User', readonly=True)
    vcard_id = fields.Many2one('partner.vcard', string='Card', readonly=True)
    
    magic_link_token = fields.Char(string='Magic Link Token', readonly=True)
    token_expires_at = fields.Datetime(string='Token Expires At', readonly=True)
    
    rep_data_json = fields.Text(string='Rep Data (JSON)')
    error_message = fields.Text(string='Error Message')
    
    def get_rep_data(self):
        """Parse and return rep_data_json as dict"""
        if not self.rep_data_json:
            return {}
        try:
            return json.loads(self.rep_data_json)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_rep_data(self, data):
        """Set rep_data_json from dict"""
        self.rep_data_json = json.dumps(data)
    
    def action_resend_invitation(self):
        """Resend invitation email for this rep"""
        if not self.user_id:
            raise UserError("No user account found for this rep")
        
        if not self.magic_link_token:
            # Generate new token
            self.magic_link_token = self.batch_id._generate_magic_link_token(self.email, self.user_id.id)
            self.token_expires_at = datetime.now() + timedelta(days=7)
        
        # Get rep data and common data
        rep_data = self.get_rep_data()
        common_data = self.batch_id.get_common_data()
        
        # Send invitation
        try:
            self.batch_id._send_invitation_email(self.user_id, rep_data, self.magic_link_token, common_data)
            # Update status to invited after successful send
            if self.status != 'completed':
                self.status = 'invited'
            return True
        except Exception as e:
            _logger.error(f"Error resending invitation for user {self.user_id.id}: {str(e)}", exc_info=True)
            raise UserError(f"Failed to resend invitation: {str(e)}")

    def action_reprocess(self):
        """Re-run account + card creation for this single rep.

        This is what the web 'Retry' button on a failed/pending row calls.
        Unlike a plain resend (which needs an already-created user), this
        actually creates the Odoo-user-linked card when one was never made —
        the case that left the Jobe batch stuck. If the rep already has a
        user and card, a retry degrades gracefully to a resend.

        Returns a dict {'success': bool, 'status': str, 'error': str|None}
        instead of raising, so the per-row UI can show the outcome inline.
        A savepoint isolates a failed attempt so we can still persist the
        'failed' status + error without poisoning the whole request.
        """
        self.ensure_one()
        if self.status == 'completed':
            return {'success': True, 'status': 'completed', 'error': None}

        batch = self.batch_id

        # Already provisioned — retry just resends the notification.
        if self.user_id and self.vcard_id:
            try:
                self.action_resend_invitation()
                return {'success': True, 'status': self.status, 'error': None}
            except Exception as e:
                return {'success': False, 'status': self.status, 'error': str(e)}

        common_data = batch.get_common_data()
        rep_data = self.get_rep_data()
        # Honour any inline edit to the rep's email before re-running.
        if self.email:
            rep_data['email'] = self.email
            self.set_rep_data(rep_data)

        try:
            with self.env.cr.savepoint():
                batch._create_rep_account(self, common_data, rep_data)
            self.status = 'invited'
            self.error_message = False
            batch._refresh_status()
            return {'success': True, 'status': 'invited', 'error': None}
        except Exception as e:
            _logger.error(f"Reprocess failed for rep {self.id} ({self.email}): {e}", exc_info=True)
            # The savepoint rolled back the partial vcard INSERT and the
            # rep.user_id / rep.vcard_id assignments at the DB level, but those
            # values may still sit in the ORM cache. Drop the cache before
            # recording the failure so we never flush a dangling foreign key.
            self.env.invalidate_all()
            self.status = 'failed'
            self.error_message = str(e)
            batch._refresh_status()
            return {'success': False, 'status': 'failed', 'error': str(e)}


class BulkOnboardingToken(models.Model):
    _name = 'bulk.onboarding.token'
    _description = 'Magic Link Token for Bulk Onboarding'
    _rec_name = 'email'

    token = fields.Char(string='Token', required=True, index=True)
    email = fields.Char(string='Email', required=True, index=True)
    batch_id = fields.Many2one('bulk.onboarding.batch', string='Batch')
    expires_at = fields.Datetime(string='Expires At', required=True)
    used = fields.Boolean(string='Used', default=False)
    used_at = fields.Datetime(string='Used At')
    user_id = fields.Many2one('res.users', string='User')

    _token_unique = models.Constraint('unique(token)', 'Token must be unique.')

    @api.model
    def validate_token(self, token):
        """Validate magic link token"""
        token_record = self.search([
            ('token', '=', token),
            ('used', '=', False)
        ], limit=1)
        
        if not token_record:
            return False, "Invalid or already used token"
        
        if token_record.expires_at < datetime.now():
            return False, "Token has expired"
        
        return True, token_record

