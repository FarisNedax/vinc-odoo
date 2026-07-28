# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
import qrcode
from PIL import Image, ImageDraw
import io
import base64
import re
from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup
from qrcode.image.styles.colormasks import SolidFillColorMask
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import CircleModuleDrawer, RoundedModuleDrawer, GappedSquareModuleDrawer, SquareModuleDrawer

class LeadTag(models.Model):
    _name = 'lead.tag'
    _description = 'Lead Tag'

    name = fields.Char(string="Tag Name", required=True, help="Name of the tag")

class FollowupReminder(models.Model):
    _name = 'followup.reminder'
    _description = 'Follow-up Reminder Template'
    _order = 'sequence, id'
    
    partner_vcard_id = fields.Many2one(
        'partner.vcard',
        string="Partner vCard",
        required=True,
        ondelete='cascade'
    )
    name = fields.Char(
        string="Reminder Name",
        required=True,
        help="Name for this reminder (e.g., 'First Follow-up', 'Check-in After 3 Days')"
    )
    sequence = fields.Integer(string="Sequence", default=10, help="Order in which reminders are scheduled")
    active = fields.Boolean(string="Active", default=True, help="Enable or disable this reminder")
    
    # Activity configuration
    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string="Activity Type",
        required=True,
        help="Type of activity to create (Call, Email, Meeting, etc.)"
    )
    summary = fields.Char(
        string="Summary",
        help="Short description for the activity. Leave empty to use activity type name."
    )
    note = fields.Text(
        string="Note",
        help="Additional notes for the activity"
    )
    
    # Timing configuration
    schedule_type = fields.Selection(
        [('after_creation', 'After Lead Creation'), ('after_previous_activity', 'After Previous Activity Completed')],
        string="Schedule Type",
        required=True,
        default='after_creation',
        help="When to schedule this reminder: immediately after lead creation, or after the previous activity is completed"
    )
    delay_amount = fields.Integer(
        string="Delay Amount",
        required=True,
        default=1,
        help="How long to wait before scheduling this reminder"
    )
    delay_type = fields.Selection(
        [('minutes', 'Minutes'), ('hours', 'Hours'), ('days', 'Days')],
        string="Delay Type",
        required=True,
        default='days',
        help="Unit for the delay"
    )
    
    # User assignment
    user_id = fields.Many2one(
        'res.users',
        string="Assigned To",
        help="User to assign the activity to. Leave empty to assign to vCard owner."
    )

class FollowupScheduledReminder(models.Model):
    _name = 'followup.scheduled.reminder'
    _description = 'Scheduled Follow-up Reminder'
    _order = 'scheduled_datetime asc'
    
    opportunity_id = fields.Many2one(
        'crm.lead',
        string="Opportunity",
        required=True,
        ondelete='cascade',
        help="The lead/opportunity this reminder is for"
    )
    contact_name = fields.Char(
        string="Contact Name",
        required=True,
        help="Name of the contact for placeholder replacement"
    )
    reminder_template_id = fields.Many2one(
        'followup.reminder',
        string="Reminder Template",
        required=True,
        ondelete='cascade',
        help="The reminder template this scheduled reminder is based on"
    )
    scheduled_datetime = fields.Datetime(
        string="Scheduled DateTime",
        required=True,
        index=True,
        help="Exact datetime when this activity should be created"
    )
    date_deadline = fields.Date(
        string="Activity Deadline",
        required=True,
        help="The date_deadline to set on the activity when it's created"
    )
    activity_type_id = fields.Many2one(
        'mail.activity.type',
        string="Activity Type",
        required=True,
        help="Type of activity to create"
    )
    summary = fields.Char(
        string="Summary",
        help="Activity summary (with placeholders already processed)"
    )
    note = fields.Text(
        string="Note",
        help="Activity notes"
    )
    user_id = fields.Many2one(
        'res.users',
        string="Assigned To",
        required=True,
        help="User to assign the activity to"
    )
    previous_activity_id = fields.Many2one(
        'mail.activity',
        string="Previous Activity",
        help="For 'after_previous_activity' type: the activity that must be completed before this reminder is scheduled"
    )
    processed = fields.Boolean(
        string="Processed",
        default=False,
        index=True,
        help="Whether this reminder has been processed and activity created"
    )
    activity_id = fields.Many2one(
        'mail.activity',
        string="Created Activity",
        readonly=True,
        help="The activity that was created from this scheduled reminder"
    )
    created_at = fields.Datetime(
        string="Created At",
        default=fields.Datetime.now,
        readonly=True,
        help="When this scheduled reminder was created"
    )
    processed_at = fields.Datetime(
        string="Processed At",
        readonly=True,
        help="When this scheduled reminder was processed"
    )
    
    @api.model
    def _cron_process_scheduled_reminders(self):
        """
        Cron job to process scheduled follow-up reminders and create activities.
        This runs every minute to check for reminders that are due.
        
        :return: Number of activities created
        """
        import logging
        _logger = logging.getLogger(__name__)
        
        _logger.info("=" * 80)
        _logger.info("FOLLOW-UP REMINDER CRON - Starting")
        _logger.info(f"Current datetime: {fields.Datetime.now()}")
        _logger.info("=" * 80)
        
        now_str = fields.Datetime.now()
        now_dt = fields.Datetime.from_string(now_str)
        
        # Find all unprocessed reminders that are due (scheduled_datetime <= now)
        # Exclude reminders waiting for previous activities (they'll be handled separately)
        due_reminders = self.sudo().search([
            ('processed', '=', False),
            ('scheduled_datetime', '<=', now_str),
            ('previous_activity_id', '=', False)  # Not waiting for previous activity
        ], order='scheduled_datetime asc')
        
        _logger.info(f"Found {len(due_reminders)} scheduled reminder(s) due for processing (excluding those waiting for previous activities)")
        
        # Also check for reminders waiting for completed activities
        completed_activities = self.env['mail.activity'].sudo().search([
            ('state', '=', 'done'),
            ('date_done', '!=', False),
        ])
        
        if completed_activities:
            # Find reminders waiting for these completed activities
            waiting_reminders = self.sudo().search([
                ('processed', '=', False),
                ('previous_activity_id', 'in', completed_activities.ids),
            ])
            
            if waiting_reminders:
                _logger.info(f"Found {len(waiting_reminders)} reminder(s) waiting for completed activities")
                # Process these reminders - recalculate their scheduled_datetime based on activity completion + delay
                for waiting_reminder in waiting_reminders:
                    try:
                        prev_activity = waiting_reminder.previous_activity_id
                        if prev_activity.state == 'done' and prev_activity.date_done:
                            # Calculate new scheduled_datetime based on completion date + delay
                            completion_dt = fields.Datetime.from_string(prev_activity.date_done)
                            template = waiting_reminder.reminder_template_id
                            
                            from datetime import timedelta
                            if template.delay_type == 'minutes':
                                new_scheduled_dt = completion_dt + timedelta(minutes=template.delay_amount)
                            elif template.delay_type == 'hours':
                                new_scheduled_dt = completion_dt + timedelta(hours=template.delay_amount)
                            elif template.delay_type == 'days':
                                new_scheduled_dt = completion_dt + timedelta(days=template.delay_amount)
                            else:
                                new_scheduled_dt = completion_dt
                            
                            # Update scheduled_datetime and date_deadline
                            if template.delay_type == 'days':
                                new_date_deadline = new_scheduled_dt.date()
                            else:
                                # For minutes/hours, if still today, set to tomorrow
                                if new_scheduled_dt.date() <= fields.Date.today():
                                    new_date_deadline = fields.Date.today() + timedelta(days=1)
                                else:
                                    new_date_deadline = new_scheduled_dt.date()
                            
                            waiting_reminder.write({
                                'scheduled_datetime': fields.Datetime.to_string(new_scheduled_dt),
                                'date_deadline': new_date_deadline,
                                'previous_activity_id': False,  # Clear the reference
                            })
                            
                            _logger.info(
                                f"  Updated reminder ID {waiting_reminder.id}: "
                                f"Previous activity {prev_activity.id} completed at {prev_activity.date_done}, "
                                f"New scheduled datetime: {new_scheduled_dt}, New deadline: {new_date_deadline}"
                            )
                    except Exception as e:
                        _logger.exception(f"Error updating waiting reminder ID {waiting_reminder.id}: {e}")
                
                # Re-fetch due reminders including the updated ones
                due_reminders = self.sudo().search([
                    ('processed', '=', False),
                    ('scheduled_datetime', '<=', now_str),
                    ('previous_activity_id', '=', False)
                ], order='scheduled_datetime asc')
        
        if not due_reminders:
            _logger.info("No reminders to process. Exiting.")
            _logger.info("=" * 80)
            return 0
        
        activities_created = 0
        errors = 0
        
        for reminder in due_reminders:
            try:
                _logger.info("-" * 80)
                _logger.info(f"Processing scheduled reminder ID {reminder.id}")
                _logger.info(f"  Opportunity ID: {reminder.opportunity_id.id}")
                _logger.info(f"  Contact Name: {reminder.contact_name}")
                _logger.info(f"  Reminder Template: {reminder.reminder_template_id.name}")
                _logger.info(f"  Scheduled for: {reminder.scheduled_datetime}")
                _logger.info(f"  Date Deadline: {reminder.date_deadline}")
                _logger.info(f"  Activity Type: {reminder.activity_type_id.name}")
                _logger.info(f"  Assigned To: {reminder.user_id.name}")
                
                # Check if opportunity still exists
                if not reminder.opportunity_id.exists():
                    _logger.warning(f"  ✗ Opportunity {reminder.opportunity_id.id} no longer exists. Marking as processed.")
                    reminder.write({
                        'processed': True,
                        'processed_at': fields.Datetime.now(),
                    })
                    continue
                
                # Create the activity using the stored date_deadline
                activity = reminder.opportunity_id.sudo().activity_schedule(
                    activity_type_id=reminder.activity_type_id.id,
                    summary=reminder.summary or reminder.activity_type_id.name or 'Follow-up',
                    note=reminder.note or '',
                    date_deadline=reminder.date_deadline,  # Use stored date_deadline
                    user_id=reminder.user_id.id,
                )
                
                # Mark as processed
                reminder.write({
                    'processed': True,
                    'processed_at': fields.Datetime.now(),
                    'activity_id': activity.id,
                })
                
                activities_created += 1
                
                _logger.info(
                    f"  ✓ Activity created successfully: ID {activity.id}, "
                    f"Assigned to: {reminder.user_id.name}, "
                    f"Due date: {reminder.date_deadline}"
                )
                
                # If there are any reminders waiting for this activity (for "after_previous_activity" type),
                # they will be picked up in the next cron run when this activity is marked as done
                
            except Exception as e:
                errors += 1
                _logger.exception(
                    f"  ✗ ERROR processing scheduled reminder ID {reminder.id}: {e}"
                )
                # Continue with other reminders even if one fails
                continue
        
        _logger.info("=" * 80)
        _logger.info(f"FOLLOW-UP REMINDER CRON - Completed")
        _logger.info(f"  Activities created: {activities_created}")
        _logger.info(f"  Errors: {errors}")
        _logger.info(f"  Total processed: {activities_created + errors}")
        _logger.info("=" * 80)
        
        return activities_created

class VcardDownloadTracking(models.Model):
    _name = 'vcard.download.tracking'
    _description = 'vCard Download Tracking'
    _order = 'download_date desc'
    
    partner_vcard_id = fields.Many2one(
        'partner.vcard',
        string="Partner vCard",
        required=True,
        ondelete='cascade',
        index=True,
        help="The vCard that was downloaded"
    )
    download_date = fields.Datetime(
        string="Download Date",
        default=fields.Datetime.now,
        required=True,
        index=True,
        help="When the vCard was downloaded"
    )
    
    # Tracking data (same as lead tracking)
    download_ip = fields.Char(
        string='Download IP',
        help='IP address captured when the vCard was downloaded'
    )
    download_user_agent = fields.Char(
        string='Download User Agent',
        help='Browser user agent string captured during download'
    )
    download_fingerprint_hash = fields.Char(
        string='Download Fingerprint',
        help='SHA-256 hash of browser fingerprint captured during download'
    )
    download_country = fields.Char(
        string='Download Country',
        help='Country detected from IP address geolocation'
    )
    download_city = fields.Char(
        string='Download City',
        help='City detected from IP address geolocation'
    )
    download_timezone = fields.Char(
        string='Download Timezone',
        help='Timezone detected from IP address or browser'
    )
    download_language = fields.Char(
        string='Download Language',
        help='Browser language preference (Accept-Language header)'
    )
    download_source_url = fields.Char(
        string='Source URL',
        help='The URL/referrer where the user came from before downloading'
    )
    download_utm_source = fields.Char(
        string='UTM Source',
        help='UTM source parameter from the URL (if present)'
    )
    download_utm_medium = fields.Char(
        string='UTM Medium',
        help='UTM medium parameter from the URL (if present)'
    )
    download_utm_campaign = fields.Char(
        string='UTM Campaign',
        help='UTM campaign parameter from the URL (if present)'
    )
    download_referral_code = fields.Char(
        string='Referral Code',
        help='Referral code (ref parameter) from the URL if the download came from a referral link'
    )
    download_device_type = fields.Char(
        string='Device Type',
        help='Detected device type (mobile, desktop, tablet) from user agent'
    )
    download_browser = fields.Char(
        string='Browser',
        help='Detected browser name from user agent'
    )
    download_os = fields.Char(
        string='Operating System',
        help='Detected operating system from user agent'
    )

class LeadbackMessagingChannel(models.Model):
    _name = 'leadback.messaging.channel'
    _description = 'Lead-Back Messaging Channel'
    _order = 'sequence, name'

    name = fields.Char(string="Channel Name", required=True)
    code = fields.Char(string="Channel Code", required=True, help="Internal code: whatsapp, viber, or telegram")
    sequence = fields.Integer(string="Sequence", default=10, help="Display order")
    active = fields.Boolean(string="Active", default=True)


class LeadbackScheduledEmail(models.Model):
    _name = 'leadback.scheduled.email'
    _description = 'Scheduled Lead-Back Email'
    _order = 'scheduled_time asc'
    
    partner_vcard_id = fields.Many2one(
        'partner.vcard',
        string="Partner vCard",
        required=True,
        ondelete='cascade'
    )
    contact_name = fields.Char(string="Contact Name", required=True)
    contact_email = fields.Char(string="Contact Email", required=True)
    opportunity_id = fields.Many2one(
        'crm.lead',
        string="Opportunity/Lead",
        ondelete='set null'
    )
    email_subject = fields.Char(string="Email Subject", required=True)
    email_body_html = fields.Html(string="Email Body (HTML)", required=True)
    scheduled_time = fields.Datetime(string="Scheduled Time", required=True, index=True)
    state = fields.Selection(
        [('pending', 'Pending'), ('sent', 'Sent'), ('failed', 'Failed')],
        string="State",
        default='pending',
        required=True
    )
    sent_time = fields.Datetime(string="Sent Time", readonly=True)
    error_message = fields.Text(string="Error Message", readonly=True)
    
    def action_send_now(self):
        """Manually send the scheduled email"""
        self.ensure_one()
        if self.state != 'pending':
            raise UserError("Only pending emails can be sent")
        
        self._send_email()
        return True
    
    def _send_email(self):
        """Send the scheduled email"""
        self.ensure_one()
        try:
            from datetime import datetime
            
            # Prepare mail values
            mail_values = {
                'subject': self.email_subject,
                'body_html': self.email_body_html,
                'email_to': self.contact_email,
                'email_from': self.env['partner.vcard']._get_notification_email(user=self.env.user),
                'auto_delete': False,
            }
            
            # Create and send mail
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()
            
            # Update state
            self.write({
                'state': 'sent',
                'sent_time': datetime.now()
            })
            
            # Log to opportunity if exists
            if self.opportunity_id:
                from markupsafe import Markup
                self.opportunity_id.message_post(
                    body=Markup(f"<p><strong>✓ Scheduled Email Sent</strong><br/>To: {self.contact_email}</p>"),
                    subject="Scheduled Lead-Back Email Sent"
                )
            
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(f"Scheduled email sent to {self.contact_email} for lead {self.opportunity_id.id if self.opportunity_id else 'N/A'}")
            
            return True
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception(f"Error sending scheduled email {self.id}: {e}")
            
            self.write({
                'state': 'failed',
                'error_message': str(e)
            })
            
            # Log error to opportunity if exists
            if self.opportunity_id:
                from markupsafe import Markup
                self.opportunity_id.message_post(
                    body=Markup(f"<p><strong>✗ Scheduled Email Failed</strong><br/>To: {self.contact_email}<br/>Error: {str(e)}</p>"),
                    subject="Scheduled Lead-Back Email Failed"
                )
            
            return False
    
    @api.model
    def _cron_send_scheduled_emails(self):
        """Cron job to send scheduled emails that are due"""
        from datetime import datetime
        
        now = datetime.now()
        pending_emails = self.search([
            ('state', '=', 'pending'),
            ('scheduled_time', '<=', now)
        ])
        
        import logging
        _logger = logging.getLogger(__name__)
        _logger.info(f"Processing {len(pending_emails)} scheduled emails")
        
        for email in pending_emails:
            email._send_email()
        
        return True

class CrmLead(models.Model):
    _inherit = 'crm.lead'
    partner_vcard_id = fields.Many2one('partner.vcard', string='Partner vCard')
    service_request_answers = fields.Text(
        string='Service Request Answers',
        help='Structured summary of custom answers provided in the service request form.',
    )

    # ====================================================================
    # Look-alike matches (rebuilt 2026-05-07)
    # --------------------------------------------------------------------
    # The job is NOT "find records with the same values". It is "give the
    # rep a memory aid so they can talk to a fresh prospect with context".
    # So we score on *useful overlap* (industry hierarchy, geo gradient,
    # deal-size bucket, tag word-overlap, free-text Jaccard) and surface
    # each match with its CONTEXT (outcome, deal amount, lost reason,
    # description snippet, last activity date, owner) — not just a name.
    #
    # Two buckets:
    #   * lookalike_partner_ids: companies in res.partner ("we work with")
    #   * lookalike_lead_ids:    open opportunities ("similar in pipeline")
    #
    # No external API. All signals come from the tenant's existing data.
    # ====================================================================
    lookalike_partner_ids = fields.Many2many(
        'res.partner', 'crm_lead_lookalike_partner_rel',
        'lead_id', 'partner_id',
        string='Look-alike Companies',
        compute='_compute_lookalike', store=False,
    )
    lookalike_partner_count = fields.Integer(
        string='# Look-alike Companies', compute='_compute_lookalike', store=False,
    )
    lookalike_lead_ids = fields.Many2many(
        'crm.lead', 'crm_lead_lookalike_lead_rel',
        'lead_id', 'related_lead_id',
        string='Look-alike Open Leads',
        compute='_compute_lookalike', store=False,
    )
    lookalike_lead_count = fields.Integer(
        string='# Look-alike Open Leads', compute='_compute_lookalike', store=False,
    )
    lookalike_summary = fields.Html(
        string='Look-alike Summary',
        compute='_compute_lookalike', store=False, sanitize=False,
        help="Per-match conversation-starter card with the context (outcome, "
             "amount, last note) attached to each look-alike.",
    )
    lookalike_hint = fields.Char(
        string='Look-alike Data Hint', compute='_compute_lookalike', store=False,
    )

    # Weights sum to 100; threshold below.
    _LOOKALIKE_WEIGHTS = {
        'industry':    35,   # exact = full, parent/sibling = half
        'geo':         25,   # city > state > country gradient
        'deal_size':   20,   # same bucket = full, adjacent = half
        'tag_fuzzy':   15,   # word-level overlap on tag names
        'description':  5,   # Jaccard on description tokens
    }
    _LOOKALIKE_MIN_SCORE = 25
    _LOOKALIKE_TOP_N = 3

    # Deal-size buckets in your default currency (whatever the lead uses).
    # Tweak in a follow-up if multi-currency tenants need bucketing per company.
    _DEAL_SIZE_BUCKETS = [
        (0,       10_000,  'micro'),
        (10_000,  50_000,  'small'),
        (50_000,  200_000, 'mid'),
        (200_000, 10**12,  'large'),
    ]

    @api.depends('email_from', 'phone', 'function', 'country_id', 'state_id',
                 'city', 'tag_ids', 'description', 'expected_revenue',
                 'partner_id')
    def _compute_lookalike(self):
        for lead in self:
            partner_matches, lead_matches, hint = lead._find_lookalike()
            partner_recs = lead.env['res.partner'].browse(
                [r.id for r, _, _ in partner_matches]
            )
            opp_recs = lead.env['crm.lead'].browse(
                [r.id for r, _, _ in lead_matches]
            )
            lead.lookalike_partner_ids = partner_recs
            lead.lookalike_partner_count = len(partner_recs)
            lead.lookalike_lead_ids = opp_recs
            lead.lookalike_lead_count = len(opp_recs)
            lead.lookalike_hint = hint
            lead.lookalike_summary = lead._render_lookalike_summary(
                partner_matches, lead_matches, hint,
            )

    def _find_lookalike(self):
        """Return (partner_matches, lead_matches, hint).

        Each match list element is (record, signals_matched, context_payload).
        """
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        Lead = self.env['crm.lead'].sudo()

        real_self_id = (
            self._origin.id
            if self._origin and isinstance(self._origin.id, int)
            else None
        )

        partner_domain = [
            ('is_company', '=', True),
            ('active', '=', True),
        ]
        if 'customer_rank' in Partner._fields and 'supplier_rank' in Partner._fields:
            partner_domain += ['|', ('customer_rank', '>', 0), ('supplier_rank', '=', 0)]
        if self.partner_id and isinstance(self.partner_id.id, int):
            partner_domain.append(('id', '!=', self.partner_id.id))
        partner_pool = Partner.search(partner_domain, limit=2000)

        lead_domain = [
            ('type', '=', 'opportunity'),
            ('active', '=', True),
            ('probability', '<', 100),
            ('probability', '>', 0),
        ]
        if real_self_id:
            lead_domain.insert(0, ('id', '!=', real_self_id))
        lead_pool = Lead.search(lead_domain, limit=2000)

        lead_industry = self.partner_id.industry_id if self.partner_id else False
        lead_country = self.country_id
        lead_state = self.state_id
        lead_city = (self.city or '').strip().lower() or None
        lead_size_bucket = self._lookalike_deal_bucket(self.expected_revenue or 0)
        lead_tag_words = self._lookalike_tokenize(
            ' '.join((t.name or '') for t in self.tag_ids)
        )
        lead_desc_tokens = self._lookalike_tokenize(self.description or '')

        signals_used = set()

        def score_record(record, tag_field, *, is_lead):
            score = 0
            signals = []

            rec_industry = (
                record.industry_id if hasattr(record, 'industry_id')
                else (record.partner_id.industry_id if record.partner_id else False)
            )
            if lead_industry and rec_industry:
                if lead_industry == rec_industry:
                    score += self._LOOKALIKE_WEIGHTS['industry']
                    signals.append("same industry (" + lead_industry.name + ")")
                    signals_used.add('industry')
                else:
                    # Sibling-industry path: only fires if the industry model has
                    # parent_id (Odoo Community has a flat list; some setups extend).
                    lead_parent = getattr(lead_industry, 'parent_id', False)
                    rec_parent = getattr(rec_industry, 'parent_id', False)
                    if lead_parent and rec_parent and lead_parent == rec_parent:
                        score += self._LOOKALIKE_WEIGHTS['industry'] // 2
                        signals.append("sibling industry (" + rec_industry.name + ")")
                        signals_used.add('industry')

            rec_country = getattr(record, 'country_id', False)
            rec_state = getattr(record, 'state_id', False)
            rec_city = (getattr(record, 'city', '') or '').strip().lower() or None
            if lead_city and rec_city and lead_city == rec_city:
                score += self._LOOKALIKE_WEIGHTS['geo']
                signals.append("same city (" + (record.city or '').title() + ")")
                signals_used.add('geo')
            elif lead_state and rec_state and lead_state == rec_state:
                score += int(self._LOOKALIKE_WEIGHTS['geo'] * 0.6)
                signals.append("same state (" + rec_state.name + ")")
                signals_used.add('geo')
            elif lead_country and rec_country == lead_country:
                score += int(self._LOOKALIKE_WEIGHTS['geo'] * 0.32)
                signals.append("same country (" + lead_country.name + ")")
                signals_used.add('geo')

            rec_revenue = (
                record.expected_revenue if is_lead
                else self._lookalike_partner_top_revenue(record)
            )
            rec_bucket = self._lookalike_deal_bucket(rec_revenue or 0)
            if lead_size_bucket and rec_bucket:
                if lead_size_bucket == rec_bucket:
                    score += self._LOOKALIKE_WEIGHTS['deal_size']
                    signals.append("same deal-size band (" + rec_bucket + ")")
                    signals_used.add('deal_size')
                elif self._lookalike_buckets_adjacent(lead_size_bucket, rec_bucket):
                    score += self._LOOKALIKE_WEIGHTS['deal_size'] // 2
                    signals.append("adjacent deal-size band (" + rec_bucket + ")")
                    signals_used.add('deal_size')

            tags = getattr(record, tag_field, False)
            if lead_tag_words and tags:
                rec_tag_words = self._lookalike_tokenize(
                    ' '.join((t.name or '') for t in tags)
                )
                shared_words = lead_tag_words & rec_tag_words
                if shared_words:
                    score += self._LOOKALIKE_WEIGHTS['tag_fuzzy']
                    signals.append("tag overlap (" + ", ".join(sorted(shared_words)[:3]) + ")")
                    signals_used.add('tag_fuzzy')

            rec_text = (
                record.description if is_lead
                else getattr(record, 'comment', '') or ''
            )
            if lead_desc_tokens and rec_text:
                rec_tokens = self._lookalike_tokenize(rec_text)
                if rec_tokens:
                    inter = len(lead_desc_tokens & rec_tokens)
                    union = len(lead_desc_tokens | rec_tokens)
                    if union:
                        jaccard = inter / union
                        if jaccard >= 0.05:
                            score += int(round(self._LOOKALIKE_WEIGHTS['description'] * min(jaccard * 4, 1)))
                            signals.append("similar notes")
                            signals_used.add('description')

            return score, signals

        scored_partners = []
        for p in partner_pool:
            score, signals = score_record(p, 'category_id', is_lead=False)
            if score >= self._LOOKALIKE_MIN_SCORE:
                payload = self._lookalike_partner_payload(p)
                scored_partners.append((score, p, signals, payload))
        scored_partners.sort(key=lambda x: -x[0])
        partner_matches = [
            (p, signals, payload)
            for _, p, signals, payload in scored_partners[:self._LOOKALIKE_TOP_N]
        ]

        scored_leads = []
        for l in lead_pool:
            score, signals = score_record(l, 'tag_ids', is_lead=True)
            if score >= self._LOOKALIKE_MIN_SCORE:
                payload = self._lookalike_lead_payload(l)
                scored_leads.append((score, l, signals, payload))
        scored_leads.sort(key=lambda x: -x[0])
        lead_matches = [
            (l, signals, payload)
            for _, l, signals, payload in scored_leads[:self._LOOKALIKE_TOP_N]
        ]

        if partner_matches or lead_matches:
            hint = "Matched on: " + ", ".join(sorted(signals_used)) + "."
        elif not lead_industry and not lead_country and not lead_tag_words:
            hint = ("No look-alikes — this lead has no industry, country, or "
                    "tags to match on. Fill in those fields to enable matching.")
        else:
            hint = ("Nothing crossed the similarity threshold. Add industry / "
                    "tags / better-populated descriptions to existing customers "
                    "to sharpen future matches.")
        return partner_matches, lead_matches, hint

    def _lookalike_partner_payload(self, partner):
        """Pull the conversation-starter context for a matched company."""
        Lead = self.env['crm.lead'].sudo()
        history = Lead.search(
            [('partner_id', '=', partner.id)],
            order='date_closed desc, write_date desc',
            limit=5,
        )
        won = history.filtered(lambda l: l.probability == 100)
        lost = history.filtered(lambda l: l.probability == 0 and l.active is False)
        active = history.filtered(lambda l: 0 < (l.probability or 0) < 100 and l.active)
        outcome_lead = (won[:1] or lost[:1] or active[:1] or history[:1])

        payload = {
            'subtitle_bits': [],
            'outcome': None,
            'snippet': (partner.comment or '').strip()[:120] or None,
            'owner': partner.user_id.name if partner.user_id else None,
            'last_seen': partner.write_date,
        }
        if partner.industry_id:
            payload['subtitle_bits'].append(partner.industry_id.name)
        if partner.city:
            payload['subtitle_bits'].append(partner.city.title())
        elif partner.country_id:
            payload['subtitle_bits'].append(partner.country_id.name)

        if outcome_lead:
            ol = outcome_lead
            label = ('Won' if ol.probability == 100 else 'Lost' if ol.probability == 0 and not ol.active else 'Active')
            amount = ol.expected_revenue or 0
            bits = [label + ' deal']
            if amount:
                bits.append("$" + format(amount, ',.0f'))
            if ol.date_closed:
                bits.append("closed " + ol.date_closed.strftime('%b %Y'))
            if ol.user_id:
                bits.append(ol.user_id.name)
            payload['outcome'] = " · ".join(bits)
            if not payload['snippet'] and ol.description:
                payload['snippet'] = ol.description.strip()[:120]
            if ol.lost_reason_id:
                payload['outcome'] += " — lost reason: " + ol.lost_reason_id.name
        return payload

    def _lookalike_lead_payload(self, lead):
        """Pull the conversation-starter context for a matched open lead."""
        amount = lead.expected_revenue or 0
        bits = [(lead.stage_id.name if lead.stage_id else "Active")]
        if amount:
            bits.append("$" + format(amount, ',.0f'))
        if lead.user_id:
            bits.append(lead.user_id.name)
        return {
            'subtitle_bits': [
                b for b in [
                    lead.partner_id.industry_id.name if lead.partner_id and lead.partner_id.industry_id else None,
                    lead.city.title() if lead.city else (lead.country_id.name if lead.country_id else None),
                ] if b
            ],
            'outcome': " · ".join(bits),
            'snippet': (lead.description or '').strip()[:120] or None,
            'owner': lead.user_id.name if lead.user_id else None,
            'last_seen': lead.write_date,
        }

    @api.model
    def _lookalike_partner_top_revenue(self, partner):
        Lead = self.env['crm.lead'].sudo()
        rec = Lead.search_read(
            [('partner_id', '=', partner.id)],
            ['expected_revenue'],
            order='expected_revenue desc',
            limit=1,
        )
        return rec[0]['expected_revenue'] if rec else 0

    @classmethod
    def _lookalike_deal_bucket(cls, amount):
        for low, high, label in cls._DEAL_SIZE_BUCKETS:
            if low <= (amount or 0) < high:
                return label
        return None

    @classmethod
    def _lookalike_buckets_adjacent(cls, a, b):
        labels = [lbl for _, _, lbl in cls._DEAL_SIZE_BUCKETS]
        try:
            return abs(labels.index(a) - labels.index(b)) == 1
        except ValueError:
            return False

    _LOOKALIKE_STOPWORDS = frozenset({
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
        'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'or', 'that',
        'the', 'to', 'was', 'were', 'will', 'with', 'this', 'they', 'we',
        'our', 'us', 'their', 'them', 'his', 'her',
    })

    @classmethod
    def _lookalike_tokenize(cls, text):
        import re
        if not text:
            return set()
        text = re.sub(r'<[^>]+>', ' ', text)
        words = re.findall(r"[a-zA-Z][a-zA-Z\-']{2,}", text.lower())
        return {w for w in words if w not in cls._LOOKALIKE_STOPWORDS}

    def _render_lookalike_summary(self, partner_matches, lead_matches, hint):
        from markupsafe import escape
        if not partner_matches and not lead_matches:
            return '<p style="color:#6c757d;font-style:italic;margin:0;">' + str(escape(hint)) + '</p>'

        def card(record, signals, payload, model_name):
            name = escape(record.name or '(unnamed)')
            href = "/web#id=" + str(record.id) + "&amp;model=" + model_name + "&amp;view_type=form"
            sig_str = escape(", ".join(signals)) if signals else ""
            subtitle = " · ".join(
                str(escape(b)) for b in (payload.get('subtitle_bits') or []) if b
            )
            outcome = escape(payload.get('outcome') or '')
            snippet = escape(payload.get('snippet') or '')
            parts = [
                '<div style="margin-bottom:12px;padding:8px 10px;background:#fff;border-radius:6px;border:1px solid #e5e7eb;">',
                '<div><a href="' + href + '" style="font-weight:600;color:#1e40af;text-decoration:none;font-size:1.02em;">' + str(name) + '</a>',
            ]
            if subtitle:
                parts.append(' <span style="color:#6c757d;">— ' + subtitle + '</span>')
            parts.append('</div>')
            if sig_str:
                parts.append('<div style="color:#6c757d;font-size:0.85em;margin-top:2px;">' + str(sig_str) + '</div>')
            if outcome:
                parts.append('<div style="font-size:0.9em;color:#374151;margin-top:4px;">' + str(outcome) + '</div>')
            if snippet:
                parts.append('<div style="font-size:0.88em;color:#4b5563;margin-top:4px;font-style:italic;">&ldquo;' + str(snippet) + '&rdquo;</div>')
            parts.append('</div>')
            return ''.join(parts)

        out = []
        if partner_matches:
            out.append('<div style="font-weight:600;color:#374151;margin-bottom:6px;">'
                       'We work with companies like this:</div>')
            for p, signals, payload in partner_matches:
                out.append(card(p, signals, payload, 'res.partner'))
        if lead_matches:
            out.append('<div style="font-weight:600;color:#374151;margin:10px 0 6px;">'
                       'Open opportunities that look similar:</div>')
            for l, signals, payload in lead_matches:
                out.append(card(l, signals, payload, 'crm.lead'))
        return ''.join(out)

    def action_view_lookalike_partners(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Look-alike Companies',
            'res_model': 'res.partner',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.lookalike_partner_ids.ids)],
            'context': {'create': False},
            'help': '<p class="o_view_nocontent_smiling_face">No look-alike companies for this lead.</p>',
        }

    def action_view_lookalike_leads(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Look-alike Open Leads',
            'res_model': 'crm.lead',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.lookalike_lead_ids.ids)],
            'context': {'create': False},
            'help': '<p class="o_view_nocontent_smiling_face">No similar open leads in your pipeline.</p>',
        }

    
    # Lead submission tracking (similar to referral tracking)
    submission_ip = fields.Char(
        string='Submission IP',
        help='IP address captured when the lead form was submitted'
    )
    submission_user_agent = fields.Char(
        string='Submission User Agent',
        help='Browser user agent string captured during form submission'
    )
    submission_fingerprint_hash = fields.Char(
        string='Submission Fingerprint',
        help='SHA-256 hash of browser fingerprint (IP, User-Agent, Accept headers, Language) captured during form submission'
    )
    submission_country = fields.Char(
        string='Submission Country',
        help='Country detected from IP address geolocation'
    )
    submission_city = fields.Char(
        string='Submission City',
        help='City detected from IP address geolocation'
    )
    submission_timezone = fields.Char(
        string='Submission Timezone',
        help='Timezone detected from IP address or browser'
    )
    submission_language = fields.Char(
        string='Submission Language',
        help='Browser language preference (Accept-Language header)'
    )
    submission_source_url = fields.Char(
        string='Source URL',
        help='The URL/referrer where the user came from before submitting the form'
    )
    submission_utm_source = fields.Char(
        string='UTM Source',
        help='UTM source parameter from the URL (if present)'
    )
    submission_utm_medium = fields.Char(
        string='UTM Medium',
        help='UTM medium parameter from the URL (if present)'
    )
    submission_utm_campaign = fields.Char(
        string='UTM Campaign',
        help='UTM campaign parameter from the URL (if present)'
    )
    submission_referral_code = fields.Char(
        string='Referral Code',
        help='Referral code (ref parameter) from the URL if the lead came from a referral link'
    )
    submission_device_type = fields.Char(
        string='Device Type',
        help='Detected device type (mobile, desktop, tablet) from user agent'
    )
    submission_browser = fields.Char(
        string='Browser',
        help='Detected browser name from user agent'
    )
    submission_os = fields.Char(
        string='Operating System',
        help='Detected operating system from user agent'
    )
    
    @api.model
    def default_get(self, fields_list):
        """Set default type to opportunity"""
        defaults = super().default_get(fields_list)
        if 'type' not in defaults:
            defaults['type'] = 'opportunity'
        return defaults
    
    @api.model_create_multi
    def create(self, vals_list):
        """Override create - ensure it's an opportunity by default."""
        for vals in vals_list:
            if 'type' not in vals:
                vals['type'] = 'opportunity'
        return super().create(vals_list)

class PartnerVCardSpeciality(models.Model):
    _name = 'partner.vcard.speciality'
    _description = 'Partner vCard Speciality'
    _order = 'name'
    
    name = fields.Char(string='Speciality', required=True)
    partner_id = fields.Many2one('partner.vcard', string='Partner vCard', required=True, ondelete='cascade')

class PartnerVCardService(models.Model):
    _name = 'partner.vcard.service'
    _description = 'Partner vCard Service'
    _order = 'sequence, name'
    
    name = fields.Char(string='Service Title', required=True)
    # Html (sanitized) so write-path strips scripts/handlers before the value
    # hits arch_db of the published card. Published templates also use t-esc
    # (not t-raw) as belt-and-suspenders.
    description = fields.Html(
        string='Description', required=True,
        sanitize=True, sanitize_tags=True, sanitize_attributes=True,
    )
    price = fields.Char(string='Pricing', help='Enter pricing information (e.g., "$100/hour", "Starting at $500", "Free consultation")')
    show_pricing = fields.Boolean(string='Show Pricing', default=True, help='Display pricing on the vCard')
    thank_you_message = fields.Char(
        string='Thank You Message',
        default="Thank you! Your service request has been sent. We'll be in touch shortly.",
        help='Custom message shown after service request submission. If empty, a default message will be used.'
    )
    partner_id = fields.Many2one('partner.vcard', string='Partner vCard', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10, help='Display order')
    active = fields.Boolean(string='Active', default=True, help='Archive this service to hide it from the vCard without deleting it')
    question_ids = fields.One2many(
        'partner.vcard.service.question',
        'service_id',
        string='Custom Questions',
        help='Additional questions to ask when someone requests this service.',
    )
    


class PartnerVCardServiceQuestion(models.Model):
    _name = 'partner.vcard.service.question'
    _description = 'Service Request Question'
    _order = 'sequence, id'

    service_id = fields.Many2one(
        'partner.vcard.service',
        string='Service',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(string='Question', required=True)
    field_type = fields.Selection(
        [
            ('short_text', 'Short text'),
            ('long_text', 'Long text'),
            ('number', 'Number'),
            ('checkbox', 'Yes / No'),
            ('select', 'Dropdown'),
        ],
        string='Answer Type',
        default='short_text',
        required=True,
    )
    is_required = fields.Boolean(string='Required', default=False)
    sequence = fields.Integer(string='Sequence', default=10)
    options = fields.Char(
        string='Options',
        help='Comma-separated options for dropdown questions (e.g. "Option A, Option B, Option C").',
    )

class PartnerVCard(models.Model):
    _name = 'partner.vcard'
    _description = 'Partner vCard'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='Name')
    company_name = fields.Char(string='Company Name')
    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street2')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    zip = fields.Char(string='ZIP')
    country_id = fields.Many2one('res.country', string='Country')
    function = fields.Char(string='Job Position')
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')
    email = fields.Char(string='Email')
    website = fields.Char(string='Website')
    image_url = fields.Binary(string='Image')
    banner_image = fields.Binary(string='Banner Image', help='Upload a banner image that appears behind your profile picture (similar to LinkedIn)')
    title_id = fields.Many2one('res.partner.title', string='Title')
    website_ids = fields.One2many('partner.vcard.website', 'partner_id', string="Websites")
    video_ids = fields.One2many('partner.vcard.videos', 'partner_id', string="Videos")
    review_ids = fields.One2many('partner.vcard.reviews', 'partner_id', string="Reviews")
    speciality_ids = fields.One2many('partner.vcard.speciality', 'partner_id', string="Specialities")
    service_ids = fields.One2many('partner.vcard.service', 'partner_id', string="Services")
    show_services = fields.Boolean(string="Show Services Section", default=False, 
                                  help="Display the services section on the website")
    calendly_url = fields.Char(string="Calendar URL", help="Enter your Calendly URL (e.g., https://calendly.com/username). This will be displayed in the Calendar tab of the Minimal template.")
    
    # Reviews section settings
    reviews_section_title = fields.Char(string="Reviews Section Title", default="Reviews", 
                                      help="Title for the reviews section on the website")
    show_reviews = fields.Boolean(string="Show Reviews Section", default=True, 
                                help="Display the reviews section on the website")
    max_reviews_display = fields.Integer(string="Max Reviews to Display", default=5, 
                                       help="Maximum number of reviews to show on the website")
    carousel_autoscroll_speed = fields.Integer(string="Carousel Autoscroll Speed (seconds)", default=5, 
                                             help="Time in seconds between automatic carousel transitions (0 to disable autoscroll)")
    review_thank_you_message = fields.Char(
        string="Review Thank You Message",
        default="Thank you for your review! We appreciate your feedback.",
        help="Message displayed after review submission"
    )
    
    # Website Template
    website_template = fields.Selection([
        ('modern', 'Modern'),
        ('classic', 'Classic'),
        ('minimal', 'Minimal'),
        ('corporate', 'Corporate'),
        ('creative', 'Creative'),
    ], string='Website Template', default='modern', required=True,
       help='Choose the design template for your vCard website')
    
    # QR Code fields
    qr_pattern = fields.Selection(
        [
            ('square', 'Square'),
            ('dots', 'Dots'),
            ('classy', 'Classy'),
            ('classy-rounded', 'Classy Rounded'),
            ('rounded', 'Rounded')
        ],
        string="QR Code Pattern",
        default='square',
        help="Select the QR code pattern."
    )
    qr_logo = fields.Binary(
        string="QR Logo",
        help="Upload a logo to display in the center of the QR code."
    )
    qr_code = fields.Binary(string="QR Code")
    qr_code_data = fields.Char(
        string="QR Code Data",
        readonly=True,
        help="The data encoded in the QR code, generated once upon creation."
    )
    qr_code_scan_count = fields.Integer(string='QR Code Scan Count', default=0)
    page_view_count = fields.Integer(string='Page View Count', default=0, help='Total number of times the vCard page has been viewed')
    vcard_download_count = fields.Integer(string='vCard Download Count', default=0, help='Total number of times the vCard has been downloaded')
    download_tracking_ids = fields.One2many(
        'vcard.download.tracking',
        'partner_vcard_id',
        string='Download History',
        help='Detailed tracking records of all vCard downloads'
    )

    website_slug = fields.Char(string='Website Slug', help='Editable part of the website URL', required=False)
    website_full_url = fields.Char(string='Website URL', compute='_compute_website_full_url', store=True)
    website_page_id = fields.Many2one('website.page', string="Website Page", readonly=True)
    preview_template_hash = fields.Char(string='Preview Template Hash', copy=False, help='sha256 of inputs that produced the current preview arch_db; used by /vcard/preview to short-circuit no-op rebuilds')
    is_published = fields.Boolean(string='Published', compute='_compute_is_published', inverse='_inverse_is_published', store=False, help='Whether this vCard is published and accessible publicly')
    # copy=False: a duplicated card must get its own attachment rows. Sharing
    # them made the two cards serve one image, so regenerating either card's
    # website overwrote the other card's picture.
    attachment_id = fields.Many2one('ir.attachment', string='Image Attachment', readonly=True, copy=False)
    banner_attachment_id = fields.Many2one('ir.attachment', string='Banner Image Attachment', readonly=True, copy=False)
    primary_color = fields.Char(string="Primary Color", help="This color is used as the background color for all vCard templates.", default="#ffffff")
    secondary_color = fields.Char(string="Brand Color", help="This color is used for all accent elements (buttons, sections, highlights) across all templates.", default="#4C75A3")
    # Sanitised on write. Published-card templates render `about` into the
    # HTML served to every visitor, so unsanitised input here is a stored-XSS
    # vector for anyone who can edit the card (creator or Vinc Manager).
    about = fields.Html(
        string="About",
        sanitize=True, sanitize_tags=True, sanitize_attributes=True,
        help="HTML description (sanitised on save).",
    )
    
    # Social media URLs
    whatsapp_url = fields.Char(string="WhatsApp URL", help="Enter the WhatsApp click-to-chat URL, e.g., https://wa.me/1XXXXXXXXXX")
    linkedin_url = fields.Char(string="LinkedIn URL", help="Enter the LinkedIn profile URL, e.g., https://www.linkedin.com/in/username")
    linkedin_url_company = fields.Char(string="LinkedIn URL (Company)", help="Enter the LinkedIn profile URL, e.g., https://www.linkedin.com/in/username")
    youtube_url = fields.Char(string="YouTube URL", help="Enter the YouTube channel or video URL, e.g., https://www.youtube.com/channel/CHANNEL_ID")
    facebook_url = fields.Char(string="Facebook URL", help="Enter the Facebook profile URL, e.g., https://www.facebook.com/username")
    facebook_url_company = fields.Char(string="Facebook URL (Company)", help="Enter the Facebook profile URL, e.g., https://www.facebook.com/username")
    telegram_url = fields.Char(string="Telegram URL", help="Enter the Telegram URL, e.g., https://t.me/username")
    instagram_url = fields.Char(string="Instagram URL", help="Enter the Instagram profile URL, e.g., https://www.instagram.com/username")
    instagram_url_company = fields.Char(string="Instagram URL (Company)", help="Enter the Instagram profile URL, e.g., https://www.instagram.com/username")
    tumblr_url = fields.Char(string="Tumblr URL", help="Enter the Tumblr profile URL, e.g., https://username.tumblr.com")
    xing_url = fields.Char(string="Xing URL", help="Enter the Xing profile URL, e.g., https://www.xing.com/profile/username")
    github_url = fields.Char(string="GitHub URL", help="Enter the GitHub profile URL, e.g., https://github.com/username")
    vimeo_url = fields.Char(string="Vimeo URL", help="Enter the Vimeo profile URL, e.g., https://vimeo.com/username")
    messenger_url = fields.Char(string="Facebook Messenger URL", help="Enter the Messenger URL, e.g., https://m.me/username")
    dribbble_url = fields.Char(string="Dribbble URL", help="Enter the Dribbble profile URL, e.g., https://dribbble.com/username")
    skype_url = fields.Char(string="Skype URL", help="Enter the Skype username, e.g., skype:username?call")
    doordash_url = fields.Char(string="DoorDash URL", help="Enter the DoorDash store URL, e.g., https://www.doordash.com/store/restaurant")
    tripadvisor_url = fields.Char(string="TripAdvisor URL", help="Enter the TripAdvisor profile URL, e.g., https://www.tripadvisor.com/Profile/username")
    yelp_url = fields.Char(string="Yelp URL", help="Enter the Yelp business URL, e.g., https://www.yelp.com/biz/username")
    twitter_url = fields.Char(string="Twitter URL", help="Enter the Twitter profile URL, e.g., https://www.twitter.com/username")
    twitter_url_company = fields.Char(string="Twitter URL (Company)", help="Enter the Twitter profile URL, e.g., https://www.twitter.com/username")
    google_reviews_url = fields.Char(string="Google Reviews URL", help="Enter the Google Reviews URL, e.g., https://g.page/username/review")
    ubereats_url = fields.Char(string="Uber Eats URL", help="Enter the Uber Eats store URL, e.g., https://www.ubereats.com/store/restaurant")
    line_url = fields.Char(string="Line URL", help="Enter the Line URL, e.g., https://line.me/R/ti/p/username")
    vkontakte_url = fields.Char(string="Vkontakte URL", help="Enter the Vkontakte profile URL, e.g., https://vk.com/username")
    reddit_url = fields.Char(string="Reddit URL", help="Enter the Reddit profile URL, e.g., https://www.reddit.com/user/username")
    viber_url = fields.Char(string="Viber URL", help="Enter the Viber URL, e.g., viber://chat?number=number")
    pinterest_url = fields.Char(string="Pinterest URL", help="Enter the Pinterest profile URL, e.g., https://www.pinterest.com/username")
    tiktok_url = fields.Char(string="TikTok URL", help="Enter the TikTok profile URL, e.g., https://www.tiktok.com/@username")
    snapchat_url = fields.Char(string="Snapchat URL", help="Enter the Snapchat profile URL, e.g., https://www.snapchat.com/add/username")
    signal_url = fields.Char(string="Signal URL", help="Enter the Signal phone number URL, e.g., https://signal.me/#p/number")
    
    # CRM and Opportunity fields
    crm_opportunity_ids = fields.One2many('crm.lead', 'partner_vcard_id', string='Opportunities', domain=[('type', '=', 'opportunity')])
    show_form = fields.Boolean(string="Show the lead collection form")
    lead_tag_ids = fields.Many2many('crm.tag', string='Lead Tags')
    active_event_id = fields.Many2one(
        'event.event',
        string='Active Event',
        domain="[('date_end', '>=', context_today())]",
        help="Stamp every lead captured by this card with this event. "
             "Use it for trade shows, conferences, or open houses. "
             "Clear it when the show ends.",
    )
    lead_button_label = fields.Char(string="Lead Button Label", default="Leave Your Info", help="Label for the lead form button")
    form_thank_you_message = fields.Char(
        string="Form Thank You Message",
        help="Message displayed after form submission. If empty, a default message will be used."
    )
    notify_on_new_lead = fields.Boolean(
        string="Notify on New Lead",
        default=True,
        help="Send an email notification when a new lead is submitted through the form"
    )
    mailing_list_id = fields.Many2one(
        'mailing.list',
        string="Email Marketing List",
        help="Leads from this vCard will be added to this mailing list. Required if lead form is enabled.",
    )
    
    # Introduction Email Configuration
    intro_email_enabled = fields.Boolean(
        string="Send intro email automatically",
        default=False,
        help="Automatically send an introduction email to new leads. The email will be sent from notifications@vinculumapp.com with you CC'd and as the Reply-To address."
    )
    intro_email_template = fields.Html(
        string="Intro email template",
        default="<p>Hi {contact_name},</p><p>Great meeting you today. I'm {owner_name} (cc'd), here's my info and how to reach me:</p><p><strong>Email:</strong> {owner_email}<br/><strong>Phone:</strong> {owner_phone}<br/><strong>My vCard:</strong> <a href='{vcard_url}'>{vcard_url}</a></p>{if booking_url}<p>If you'd like to schedule a time to connect, you can book a slot here:</p><p><a href='{booking_url}'>{booking_url}</a></p>{/if}<p>Looking forward to connecting!<br/>{owner_name}</p>",
        help="HTML email template for the introduction email. Use placeholders like {contact_name}, {first_name}, {vcard_url}, {booking_url}, {owner_name}, {owner_email}, {owner_phone}. Use {placeholder|fallback} for fallback values. Use {if field}...{/if} for conditional blocks."
    )
    auto_show_lead_form = fields.Boolean(
        string="Auto-show lead collection form",
        default=False,
        help="Automatically open the lead collection form when visitors open the vCard. Only works if lead collection form is enabled."
    )
    auto_download_vcard = fields.Boolean(
        string="Auto-download vCard for visitors",
        default=False,
        help="Automatically start downloading the vCard file when visitors open the vCard page."
    )

    
    # Follow-up Reminders Configuration
    followup_reminders_enabled = fields.Boolean(
        string="Enable follow-up reminders",
        default=False,
        help="Automatically schedule follow-up activities for new leads based on your reminder templates"
    )
    followup_reminder_ids = fields.One2many(
        'followup.reminder',
        'partner_vcard_id',
        string="Follow-up Reminders",
        help="Configure one or more reminder templates to automatically schedule activities for new leads"
    )
    
    # Instant Lead-Back Configuration
    enable_instant_leadback = fields.Boolean(
        string="Instant Lead-Back",
        default=False,
        help="Automatically send email and messaging links to new contacts within 10 seconds of form submission"
    )
    leadback_send_email = fields.Boolean(
        string="Enable Automated Email",
        default=True,
        help="Automatically send an email to new leads using your email marketing system",
    )
    leadback_enable_messaging = fields.Boolean(
        string="Enable Click to Chat",
        default=True,
        help="Generate click-to-chat links for messaging platforms (WhatsApp, Viber, Telegram)",
    )
    leadback_email_template_preset = fields.Selection(
        [
            ('friendly', 'Friendly & Simple'),
            ('professional', 'Professional & Polished'),
            ('event', 'Event Mode'),
            ('follow_up', 'Follow-Up'),
            ('appointment', 'Appointment Booking'),
            ('custom', 'Custom'),
        ],
        string="Email Template",
        default='friendly',
        help="Choose a pre-built email template or create your own",
    )
    leadback_email_subject = fields.Char(
        string="Subject",
        default="Great connecting with you",
        help="Subject line for the automated welcome email",
    )
    leadback_email_template = fields.Html(
        string="Email Body",
        default="<p>Hi {contact_name},</p><p>Thanks again for sharing your contact details. Just wanted to let you know I received your message.</p>{if booking_url}<p>If you'd like to continue our conversation or set up some time, you can book a slot here:</p><p><a href='{booking_url}'>{booking_url}</a></p>{/if}<p>Talk soon,<br/>{owner_name}</p>",
        help="HTML email template. Use placeholders like {contact_name}, {first_name}, {vcard_url}, {booking_url}, {owner_name}. Use {placeholder|fallback} for fallback values. Use {if field}...{/if} for conditional blocks.",
    )
    leadback_email_delay_preset = fields.Selection(
        [
            ('immediate', 'Immediate (0 min)'),
            ('1_min', '1 minute'),
            ('5_min', '5 minutes'),
            ('15_min', '15 minutes'),
            ('1_hour', '1 hour'),
            ('custom', 'Custom'),
        ],
        string="Email Delay Preset",
        default='immediate',
        help="Quick preset for email delay, or choose Custom to set manually",
    )
    leadback_email_delay_type = fields.Selection(
        [('minutes', 'Minutes'), ('hours', 'Hours'), ('days', 'Days')],
        string="Email Send Delay Type",
        default='minutes',
        help="Delay type for sending automated email (only used when Custom preset is selected)",
    )
    leadback_email_delay = fields.Integer(
        string="Email Delay",
        default=0,
        help="How long to wait before sending the email (only used when Custom preset is selected)",
    )
    leadback_message_template_preset = fields.Selection(
        [
            ('friendly', 'Friendly & Short'),
            ('event', 'Event Mode'),
            ('professional', 'Professional'),
            ('follow_up', 'Follow-Up'),
            ('custom', 'Custom'),
        ],
        string="Message Template",
        default='friendly',
        help="Choose a pre-built message template or create your own",
    )
    leadback_message_template = fields.Text(
        string="Message Body",
        default="Hi {contact_name}! Thanks for sharing your details — I got your message.\n\n{if booking_url}If you'd like to continue the conversation or set up a time, here's my booking link:\n{booking_url}{/if}",
        help="Template for messaging links (WhatsApp/Viber/Telegram). Use placeholders like {contact_name}, {first_name}, {vcard_url}, {booking_url}, {owner_name}. Use {placeholder|fallback} for fallback values. Use {if field}...{/if} for conditional blocks.",
    )
    leadback_message_delay_preset = fields.Selection(
        [
            ('immediate', 'Immediate (0 min)'),
            ('1_min', '1 minute'),
            ('5_min', '5 minutes'),
            ('15_min', '15 minutes'),
            ('1_hour', '1 hour'),
            ('custom', 'Custom'),
        ],
        string="Message Delay Preset",
        default='immediate',
        help="Quick preset for message delay, or choose Custom to set manually",
    )
    leadback_message_delay_type = fields.Selection(
        [('minutes', 'Minutes'), ('hours', 'Hours'), ('days', 'Days')],
        string="Message Send Delay Type",
        default='minutes',
        help="Delay type for generating messaging links (only used when Custom preset is selected)",
    )
    leadback_message_delay = fields.Integer(
        string="Message Delay",
        default=0,
        help="How long to wait before generating messaging links (only used when Custom preset is selected)",
    )
    leadback_channels = fields.Many2many(
        'leadback.messaging.channel',
        'partner_vcard_leadback_channel_rel',
        'partner_vcard_id',
        'channel_id',
        string="Messaging Channels",
        help="Select one or more messaging channels to send instant lead-back messages",
        default=lambda self: self._default_leadback_channels(),
    )

    @api.model
    def _default_leadback_channels(self):
        """Pre-select WhatsApp on new cards so the user can flip Click to Chat
        on without immediately tripping the 'pick a channel' validator."""
        whatsapp = self.env.ref(
            'qr_code_odoo.leadback_channel_whatsapp', raise_if_not_found=False
        )
        return [(6, 0, [whatsapp.id])] if whatsapp else False

    @api.onchange('enable_instant_leadback')
    def _onchange_enable_instant_leadback_default_channel(self):
        """When an admin toggles Click to Chat on for an existing card that
        has no channels selected yet, auto-select WhatsApp. Doesn't override
        an explicit selection."""
        for record in self:
            if record.enable_instant_leadback and not record.leadback_channels:
                whatsapp = self.env.ref(
                    'qr_code_odoo.leadback_channel_whatsapp', raise_if_not_found=False
                )
                if whatsapp:
                    record.leadback_channels = [(4, whatsapp.id)]
    
    # Digest Email Settings
    digest_enabled = fields.Boolean(
        string="Enable Digest Emails",
        default=True,
        help="Receive weekly digest emails with your card statistics"
    )
    digest_frequency = fields.Selection(
        [
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('daily', 'Daily (only if activity)'),
        ],
        string="Digest Frequency",
        default='weekly',
        help="How often to receive digest emails. Daily emails are only sent if there's new activity."
    )
    last_digest_sent = fields.Datetime(
        string="Last Digest Sent",
        readonly=True,
        help="Timestamp of when the last digest email was sent"
    )
    
    # Computed fields
    vcard_opportunity_count = fields.Integer(compute='_compute_vcard_opportunity_count')
    vcard_email_contact_count = fields.Integer(compute='_compute_vcard_email_contact_count')
    has_socials = fields.Boolean(
        string="Has Social Media",
        compute="_compute_has_socials",
        store=False
    )
    referral_signup_url = fields.Char(
        string="Referral Signup URL",
        compute="_compute_referral_signup_url",
        store=True,  # Store it so it's always available in templates
        help="Signup URL with referral code for this vCard owner"
    )
    
    # Plan-based access fields
    has_grow_features = fields.Boolean(
        string="Has Grow Features",
        compute='_compute_plan_features',
        help="Whether the tenant has access to Grow plan features"
    )
    has_scale_features = fields.Boolean(
        string="Has Scale Features",
        compute='_compute_plan_features',
        help="Whether the tenant has access to Scale plan features"
    )
    subscription_plan = fields.Char(
        string="Subscription Plan",
        compute='_compute_plan_features',
        help="Current subscription plan code"
    )
    is_launch_plan = fields.Boolean(
        string="Is Launch Plan",
        compute='_compute_plan_features',
        help="Whether the tenant is on Launch plan"
    )
    template_readonly = fields.Boolean(
        string="Template Readonly",
        compute='_compute_template_readonly',
        help="Whether template selection should be readonly (Launch plan users can only use Modern)"
    )
    
    @api.depends()
    def _compute_plan_features(self):
        """Compute plan-based feature access - all features enabled"""
        for record in self:
            record.has_grow_features = True
            record.has_scale_features = True
            record.subscription_plan = 'scale'
            record.is_launch_plan = False
    
    @api.depends('website_template')
    def _compute_template_readonly(self):
        """Compute if template should be readonly - always False (all templates available)"""
        for record in self:
            record.template_readonly = False
    
    @api.depends()
    def _compute_referral_signup_url(self):
        """Compute the referral signup URL - simplified to /get-started"""
        for vcard in self:
            vcard.referral_signup_url = '/get-started'

    @api.depends(
        'whatsapp_url', 'linkedin_url', 'linkedin_url_company', 'youtube_url',
        'facebook_url', 'facebook_url_company', 'telegram_url',
        'instagram_url', 'instagram_url_company', 'tumblr_url', 'xing_url',
        'github_url', 'vimeo_url', 'messenger_url', 'dribbble_url',
        'skype_url', 'doordash_url', 'tripadvisor_url', 'yelp_url',
        'twitter_url', 'twitter_url_company', 'google_reviews_url',
        'ubereats_url', 'line_url', 'vkontakte_url', 'reddit_url',
        'viber_url', 'pinterest_url', 'tiktok_url', 'snapchat_url', 'signal_url'
    )
    def _compute_has_socials(self):
        for rec in self:
            social_urls = [
                rec.whatsapp_url, rec.linkedin_url, rec.linkedin_url_company, rec.youtube_url,
                rec.facebook_url, rec.facebook_url_company, rec.telegram_url,
                rec.instagram_url, rec.instagram_url_company, rec.tumblr_url, rec.xing_url,
                rec.github_url, rec.vimeo_url, rec.messenger_url, rec.dribbble_url,
                rec.skype_url, rec.doordash_url, rec.tripadvisor_url, rec.yelp_url,
                rec.twitter_url, rec.twitter_url_company, rec.google_reviews_url,
                rec.ubereats_url, rec.line_url, rec.vkontakte_url, rec.reddit_url,
                rec.viber_url, rec.pinterest_url, rec.tiktok_url, rec.snapchat_url, rec.signal_url
            ]
            rec.has_socials = any(social_urls)
            

    def get_referral_signup_url(self):
        """Get the referral signup URL - simplified to /get-started"""
        self.ensure_one()
        return '/get-started'
    
    @api.model
    def _get_default_banner_image(self):
        """Load the default banner image from static files"""
        try:
            import os
            import base64
            # Get the addon path
            addon_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            banner_path = os.path.join(addon_path, 'qr_code_odoo', 'static', 'description', 'Banner.png')
            
            if os.path.exists(banner_path):
                with open(banner_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            else:
                _logger.warning(f"Default banner image not found at {banner_path}")
                return False
        except Exception as e:
            _logger.error(f"Error loading default banner image: {e}")
            return False
    
    @api.model
    def _get_notification_email(self, user=None):
        """
        Get the universal notification email address.
        Uses Odoo's mail.default.from system parameter, or falls back to user email.
        
        :param user: Optional user record. If not provided, uses current user.
        :return: Email address string
        """
        # First, try to get mail.default.from system parameter
        default_from = self.env['ir.config_parameter'].sudo().get_param('mail.default.from', '')
        if default_from:
            # If it's a full email, use it; otherwise combine with catchall domain
            if '@' in default_from:
                return default_from
            else:
                # Combine with catchall domain
                catchall_domain = self.env['ir.config_parameter'].sudo().get_param('mail.catchall.domain', '')
                if catchall_domain:
                    return f"{default_from}@{catchall_domain}"
        
        # Fallback to user's email
        if user:
            if hasattr(user, 'email') and user.email:
                return user.email
            if hasattr(user, 'login') and user.login and '@' in user.login:
                return user.login
        
        # Fallback to current user
        current_user = self.env.user
        if hasattr(current_user, 'email') and current_user.email:
            return current_user.email
        if hasattr(current_user, 'login') and current_user.login and '@' in current_user.login:
            return current_user.login
        
        # Final fallback to catchall alias
        catchall_alias = self.env['ir.config_parameter'].sudo().get_param('mail.catchall.alias', 'noreply')
        catchall_domain = self.env['ir.config_parameter'].sudo().get_param('mail.catchall.domain', '')
        if catchall_domain:
            return f"{catchall_alias}@{catchall_domain}"
        
        # Last resort
        return 'noreply@localhost'
    
    @api.model
    def _get_default_profile_image(self):
        """Load the default profile image from static files"""
        try:
            import os
            import base64
            # Get the addon path
            addon_path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            profile_path = os.path.join(addon_path, 'qr_code_odoo', 'static', 'description', 'user.png')
            
            if os.path.exists(profile_path):
                with open(profile_path, 'rb') as f:
                    return base64.b64encode(f.read()).decode('utf-8')
            else:
                _logger.warning(f"Default profile image not found at {profile_path}")
                return False
        except Exception as e:
            _logger.error(f"Error loading default profile image: {e}")
            return False
    
    @api.model
    def default_get(self, fields_list):
        """Override default_get - no limits applied"""
        result = super().default_get(fields_list)
        return result
    
    @api.constrains('show_form', 'mailing_list_id')
    def _check_mailing_list_required(self):
        """Ensure mailing list is set when form is enabled"""
        for record in self:
            if record.show_form and not record.mailing_list_id:
                raise ValidationError(
                    'Please select an Email Marketing List. '
                    'This is required when the lead collection form is enabled.'
                )
    
    _sql_constraints = [
        ('website_slug_unique', 'unique(website_slug)', 
         'Website slug must be unique. Please choose a different slug. '
         'Note: Multiple NULL slugs are allowed (for unpublished vCards).')
    ]
    
    def copy(self, default=None):
        """Override copy to set slug to null so user must provide a unique slug"""
        if default is None:
            default = {}
        
        # Set slug to null - user must provide a unique slug before publishing
        default['website_slug'] = False
        default['website_page_id'] = False  # Don't copy the website page reference
        default['name'] = default.get('name', f"{self.name} (Copy)" if self.name else "Copy")
        default['is_published'] = False  # Unpublish the copy
        # The copy owns no attachment rows yet - it must never point at the
        # original's, or writing one card's image would rewrite the other's.
        default['attachment_id'] = False
        default['banner_attachment_id'] = False
        
        return super().copy(default)
    
    @api.constrains('website_slug', 'is_published')
    def _check_website_slug(self):
        """Validate website slug format and uniqueness - required when published"""
        for record in self:
            # Slug is only required when published or when generating website
            if record.is_published or record.website_page_id:
                if not record.website_slug:
                    raise ValidationError(
                        'Website slug is required to publish a vCard. Please enter a unique URL slug.'
                    )
                
                # Check for valid slug format (alphanumeric, hyphens, underscores)
                import re
                if not re.match(r'^[a-zA-Z0-9_-]+$', record.website_slug):
                    raise ValidationError(
                        'Website slug can only contain letters, numbers, hyphens, and underscores.'
                    )
                
                # Check uniqueness (slug must be globally unique)
                existing = self.search([
                    ('website_slug', '=', record.website_slug),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(
                        f'Website slug "{record.website_slug}" is already taken. Please choose a different slug.'
                    )
    
    @api.constrains('enable_instant_leadback', 'leadback_channels')
    def _check_leadback_config_required(self):
        """Click-to-Chat requires at least one messaging channel selected."""
        for record in self:
            if record.enable_instant_leadback:
                if not record.leadback_channels:
                    raise ValidationError(
                        'Please select at least one Message Channel '
                        '(WhatsApp, Viber, or Telegram) when Click to Chat is enabled.'
                    )

                # Vestigial branch retained for the legacy code below it; the
                # block always evaluates True so unreachable validators below
                # don't fire.
                if record.leadback_enable_messaging:
                    if not record.leadback_channels:
                        raise ValidationError(
                            'Please select at least one Message Channel. '
                            'This is required when "Enable Click to Chat" is enabled.'
                        )
    
    @api.depends('crm_opportunity_ids')
    def _compute_vcard_opportunity_count(self):
        import logging
        _logger = logging.getLogger(__name__)
        
        for partner in self:
            _logger.info(f"=== COMPUTING VCARD OPPORTUNITY COUNT ===")
            _logger.info(f"Partner ID: {partner.id}")
            _logger.info(f"Current user: {self.env.user.name} (ID: {self.env.user.id})")
            
            # Check with sudo (all leads)
            all_leads = self.env['crm.lead'].sudo().search([
                ('partner_vcard_id', '=', partner.id),
                ('type', '=', 'opportunity')
            ])
            _logger.info(f"Total leads (with sudo): {len(all_leads)}")
            
            # Check without sudo (what user can see)
            user_leads = partner.crm_opportunity_ids
            _logger.info(f"Leads visible to user (crm_opportunity_ids): {len(user_leads)}")
            for lead in user_leads:
                _logger.info(f"  Lead ID: {lead.id}")
            
            partner.vcard_opportunity_count = len(partner.crm_opportunity_ids)
    
    def _compute_vcard_email_contact_count(self):
        """Count email contacts that came from this vCard's leads"""
        for partner in self:
            # Count contacts where email matches any lead from this vCard
            if partner.crm_opportunity_ids:
                lead_emails = partner.crm_opportunity_ids.mapped('email_from')
                contact_count = self.env['mailing.contact'].search_count([
                    ('email', 'in', lead_emails)
                ])
                partner.vcard_email_contact_count = contact_count
            else:
                partner.vcard_email_contact_count = 0

    def action_view_vcard_opportunities(self):
        """Action to view vCard opportunities."""
        self.ensure_one()
        
        import logging
        _logger = logging.getLogger(__name__)
        
        _logger.info(f"=== ACTION VIEW VCARD OPPORTUNITIES ===")
        _logger.info(f"Current user: {self.env.user.name} (ID: {self.env.user.id})")
        _logger.info(f"vCard ID: {self.id}")
        
        # Check what leads exist for this vCard
        all_leads = self.env['crm.lead'].sudo().search([
            ('partner_vcard_id', '=', self.id),
            ('type', '=', 'opportunity')
        ])
        _logger.info(f"Total leads for vCard (with sudo): {len(all_leads)}")
        for lead in all_leads:
            _logger.info(f"  Lead ID: {lead.id}, name: {lead.name}")
        
        # Check what leads the user can see (without sudo)
        user_leads = self.env['crm.lead'].search([
            ('partner_vcard_id', '=', self.id),
            ('type', '=', 'opportunity')
        ])
        _logger.info(f"Leads visible to user (without sudo): {len(user_leads)}")
        for lead in user_leads:
            _logger.info(f"  Lead ID: {lead.id}, name: {lead.name}")
    
        return {
            'type': 'ir.actions.act_window',
            'name': 'Leads',
            'view_mode': 'list,form',
            'res_model': 'crm.lead',
            'domain': [('partner_vcard_id', '=', self.id), ('type', '=', 'opportunity')],
            'context': {
                'default_partner_vcard_id': self.id,
                'default_type': 'opportunity',
            },
        }
    
    def action_view_tenant_mailing_lists(self):
        """Action to view mailing lists"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'My Mailing Lists',
            'view_mode': 'kanban,list,form',
            'res_model': 'mailing.list',
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    Create your first mailing list!
                </p>
                <p>
                    Mailing lists help you organize your email contacts.
                    Create lists for different audiences (e.g., "Hot Leads", "Newsletter Subscribers").
                </p>
            """,
        }
    
    def action_view_vcard_email_contacts(self):
        """Action to view email contacts from this vCard's leads"""
        self.ensure_one()
        
        # Get all email addresses from leads collected via this vCard
        lead_emails = self.crm_opportunity_ids.mapped('email_from')
        
        return {
            'type': 'ir.actions.act_window',
            'name': f'Email Contacts from {self.name}',
            'view_mode': 'kanban,list,form',
            'res_model': 'mailing.contact',
            'domain': [
                ('email', 'in', lead_emails)
            ],
            'context': {
                'default_company_id': self.env.company.id,
                'search_default_exclude_optout': 1,
            },
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    No email contacts yet from this vCard!
                </p>
                <p>
                    Email contacts will appear here when people fill out the lead form on this vCard page.
                </p>
            """,
        }
    
    def action_open_website(self):
        """Open the vCard website in a new tab, generate if needed"""
        self.ensure_one()
        if not self.website_full_url:
            # Generate the website first
            self.action_generate_website_page()
        
        if self.website_full_url:
            return {
                'type': 'ir.actions.act_url',
                'url': self.website_full_url,
                'target': 'new',
            }
        else:
            raise ValidationError('Website URL is not available. Please generate the website first.')

    def action_open_nfc_guide(self):
        """Open the NFC card programming guide"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        nfc_guide_url = f"{base_url}/nfc/setup/{self.id}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': nfc_guide_url,
            'target': 'new',
        }

    def action_download_qr_code(self):
        """Download QR code - redirects to download URL"""
        self.ensure_one()
        if not self.qr_code:
            raise ValidationError('QR code is not available. Please generate the website first.')
        # Relative URL resolves against the current origin — avoids leaking a
        # hardcoded localhost:8069 fallback when web.base.url isn't configured.
        return {
            'type': 'ir.actions.act_url',
            'url': f'/vcard/qr_code/download/{self.id}',
            'target': 'self',
        }
    
    def action_open_vinculum_guide(self):
        """Open the How to Use Vinc guide"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        guide_url = f"{base_url}/vinculum/guide"
        
        return {
            'type': 'ir.actions.act_url',
            'url': guide_url,
            'target': 'new',
        }
    
    @api.depends('website_page_id', 'website_page_id.is_published')
    def _compute_is_published(self):
        """Compute published status from website page"""
        for record in self:
            record.is_published = record.website_page_id.is_published if record.website_page_id else False
    
    def _inverse_is_published(self):
        """Publish/unpublish vCard by updating website page"""
        import logging
        _logger = logging.getLogger(__name__)
        for record in self:
            if record.website_page_id:
                record.website_page_id.sudo().write({'is_published': record.is_published})
                _logger.info(f"vCard {record.id} ({record.name}) publish status changed to: {record.is_published}")
            elif record.is_published and record.website_slug:
                # If trying to publish but page doesn't exist, generate it first
                record.action_generate_website_page()
                if record.website_page_id:
                    record.website_page_id.sudo().write({'is_published': True})
                    _logger.info(f"Generated and published vCard {record.id} ({record.name})")

    def action_toggle_published(self):
        """Smart-button toggle: publish or unpublish the vCard's website page.
        Generates the page first if it doesn't exist yet."""
        for record in self:
            record.is_published = not record.is_published
        return True
    
    def _get_digest_stats(self, period_start=None, period_end=None):
        """Gather statistics for digest email"""
        self.ensure_one()
        from datetime import datetime, timedelta
        
        if not period_end:
            period_end = datetime.now()
        if not period_start:
            # Default to last 7 days for weekly, 30 for monthly, 1 for daily
            if self.digest_frequency == 'daily':
                period_start = period_end - timedelta(days=1)
            elif self.digest_frequency == 'monthly':
                period_start = period_end - timedelta(days=30)
            else:  # weekly
                period_start = period_end - timedelta(days=7)
        
        # Get all leads for this vCard
        all_leads = self.crm_opportunity_ids
        
        # Leads captured in the period
        new_leads = all_leads.filtered(
            lambda l: l.create_date and period_start <= l.create_date <= period_end
        )
        total_leads = len(all_leads)
        
        # Leads without follow-up (no activity scheduled at all - any type)
        leads_without_followup = all_leads.filtered(
            lambda l: not l.activity_ids.filtered(
                lambda a: a.date_deadline  # Any activity with a due date
            )
        )
        
        # Follow-up reminders (activities due or overdue - these ARE scheduled but need attention)
        today = datetime.now().date()
        due_followups = []
        for lead in all_leads:
            # Check for any activity with a due date (not just reminders)
            activities = lead.activity_ids.filtered(
                lambda a: a.date_deadline
            )
            for activity in activities:
                if activity.date_deadline and activity.date_deadline <= today:
                    due_followups.append({
                        'lead_name': lead.name,
                        'activity_summary': activity.summary or activity.activity_type_id.name or 'Follow-up',
                        'date_deadline': activity.date_deadline,
                        'overdue': activity.date_deadline < today
                    })
        
        # Leads per stage (CRM pipeline stages)
        leads_by_stage = {}
        for lead in all_leads:
            stage_name = lead.stage_id.name if lead.stage_id else 'New'
            if stage_name not in leads_by_stage:
                leads_by_stage[stage_name] = 0
            leads_by_stage[stage_name] += 1
        
        # Usage stats
        scans_count = self.qr_code_scan_count  # Total QR code scans (tracked via /qr/<partner_id> route)
        page_views = self.page_view_count  # Total page views (tracked when someone visits /{slug})
        
        return {
            'new_leads_count': len(new_leads),
            'total_leads_count': total_leads,
            'leads_without_followup_count': len(leads_without_followup),
            'due_followups': due_followups,
            'due_followups_count': len(due_followups),
            'leads_by_stage': leads_by_stage,
            'scans_count': scans_count,
            'page_views': page_views,
            'period_start': period_start,
            'period_end': period_end,
        }
    
    def _send_digest_email(self, force_send=False):
        """Send digest email to vCard owner

        Args:
            force_send: If True, bypass daily activity check (for testing)
        """
        self.ensure_one()

        if not self.digest_enabled or not self.email:
            return False

        brand_name = self.env['qr_code_odoo.brand'].sudo().get_brand_name()
        
        # For daily frequency, check if there's activity (unless force_send is True)
        if self.digest_frequency == 'daily' and not force_send:
            stats = self._get_digest_stats()
            if stats['new_leads_count'] == 0 and stats['due_followups_count'] == 0:
                # No activity, skip sending
                return False
        
        # Gather stats
        stats = self._get_digest_stats()
        
        # Get email template
        template = self.env.ref('qr_code_odoo.email_template_digest', raise_if_not_found=False)
        if not template:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning("Digest email template not found")
            return False
        
        # Prepare email context
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        vcard_url = self.website_full_url or f"{base_url}/web#id={self.id}&model=partner.vcard"
        
        # Format period for display
        period_display = ""
        if self.digest_frequency == 'daily':
            period_display = "Today"
        elif self.digest_frequency == 'weekly':
            period_display = "This Week"
        else:  # monthly
            period_display = "This Month"
        
        # Render the template with context
        email_ctx = {
            'vcard': self,
            'stats': stats,
            'vcard_url': vcard_url,
            'period_display': period_display,
            'base_url': base_url,
        }
        
        # Send email
        try:
            # Build the email body using Python string formatting for reliability
            from markupsafe import Markup
            
            # Format follow-ups list
            followups_html = ""
            if stats['due_followups']:
                followups_list = ""
                for followup in stats['due_followups'][:5]:
                    overdue_text = " <span style='color: #dc3545;'>(Overdue)</span>" if followup.get('overdue') else ""
                    followups_list += f"<li style='margin-bottom: 5px;'><strong>{followup.get('lead_name', 'Lead')}</strong> - {followup.get('activity_summary', 'Follow-up')}{overdue_text}</li>"
                
                if len(stats['due_followups']) > 5:
                    followups_list += f"<p style='margin: 10px 0 0 0; color: #666; font-size: 12px;'>... and {len(stats['due_followups']) - 5} more</p>"
                
                followups_html = f"""
                    <ul style="margin: 10px 0 0 0; padding-left: 20px; color: #666;">
                        {followups_list}
                    </ul>
                """
            else:
                followups_html = "<p style='margin: 10px 0 0 0; color: #28a745;'>✓ All caught up! No follow-ups due.</p>"
            
            # Format leads by stage
            leads_by_stage_html = ""
            if stats.get('leads_by_stage'):
                stage_items = []
                for stage_name, count in sorted(stats['leads_by_stage'].items()):
                    stage_items.append(f"<div style='display: flex; justify-content: space-between; margin-bottom: 8px;'><span style='color: #666;'>{stage_name}:</span><strong style='color: #333; font-size: 16px;'>{count}</strong></div>")
                leads_by_stage_html = "".join(stage_items)
            else:
                leads_by_stage_html = "<p style='color: #999; font-size: 12px; margin: 0;'>No leads yet</p>"
            
            # QR code status
            qr_status = "✓ <span style='color: #28a745; font-weight: bold;'>Yes</span>" if stats['qr_code_programmed'] else "✗ <span style='color: #dc3545; font-weight: bold;'>Not yet</span>"
            qr_link = "" if stats['qr_code_programmed'] else f"""
                <p style="margin: 5px 0 0 0; font-size: 12px; color: #666;">
                    <a href="{base_url}/web#id={self.id}&model=partner.vcard&view_type=form" 
                       style="color: #007bff; text-decoration: none;">Program your card →</a>
                </p>
            """
            
            # Build HTML body
            body_html = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
                <!-- Header -->
                <div style="text-align: center; padding: 20px 0; border-bottom: 2px solid #e0e0e0;">
                    <h1 style="margin: 0; color: #333; font-size: 24px;">📊 Your {brand_name} Card Digest</h1>
                    <p style="margin: 10px 0 0 0; color: #666; font-size: 14px;">{period_display}</p>
                </div>

                <!-- Stats Overview -->
                <div style="padding: 30px 0;">
                    <h2 style="color: #333; font-size: 20px; margin: 0 0 20px 0;">📈 Quick Stats</h2>
                    
                    <!-- Leads Section -->
                    <div style="background: ' + (partner.primary_color or '#ffffff') + '; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                        <h3 style="color: #333; font-size: 18px; margin: 0 0 15px 0;">🎯 Leads Captured</h3>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                            <span style="color: #666;">New Leads:</span>
                            <strong style="color: #007bff; font-size: 18px;">{stats['new_leads_count']}</strong>
                        </div>
                        <p style="margin: 0 0 10px 0; color: #999; font-size: 11px; font-style: italic;">Leads captured in the {period_display.lower()}</p>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                            <span style="color: #666;">Total Leads:</span>
                            <strong style="color: #333; font-size: 18px;">{stats['total_leads_count']}</strong>
                        </div>
                        <p style="margin: 0 0 10px 0; color: #999; font-size: 11px; font-style: italic;">All-time total leads captured from this {brand_name} Card</p>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="color: #666;">Without Follow-up:</span>
                            <strong style="color: #dc3545; font-size: 18px;">{stats['leads_without_followup_count']}</strong>
                        </div>
                        <p style="margin: 0 0 15px 0; color: #999; font-size: 11px; font-style: italic;">Leads that have NO scheduled activity (any type) with a due date</p>
                        
                        <!-- Leads by Stage -->
                        <div style="border-top: 1px solid #dee2e6; padding-top: 15px; margin-top: 15px;">
                            <h4 style="color: #333; font-size: 16px; margin: 0 0 10px 0;">Leads by Stage</h4>
                            {leads_by_stage_html}
                            <p style="margin: 10px 0 0 0; color: #999; font-size: 11px; font-style: italic;">Breakdown of leads across your CRM pipeline stages</p>
                        </div>
                    </div>

                    <!-- Follow-ups Section -->
                    <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #ffc107;">
                        <h3 style="color: #333; font-size: 18px; margin: 0 0 15px 0;">⏰ Follow-up Reminders</h3>
                        <p style="margin: 0 0 10px 0; color: #666;">
                            <strong style="color: #dc3545; font-size: 18px;">{stats['due_followups_count']}</strong> 
                            <span style="color: #666;">due or overdue</span>
                        </p>
                        <p style="margin: 0 0 10px 0; color: #999; font-size: 11px; font-style: italic;">Leads that HAVE scheduled activities (any type) with due dates on or before today (these need your attention now)</p>
                        {followups_html}
                    </div>

                    <!-- Onboarding Section -->
                    <div style="background: rgba(69, 126, 184, 0.1); padding: 20px; border-radius: 8px; margin-bottom: 20px; border-left: 4px solid #457eb8;">
                        <h3 style="color: #333; font-size: 18px; margin: 0 0 15px 0;">🚀 Onboarding Status</h3>
                        <div style="margin-bottom: 10px;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                                <span style="color: #666;">Profile Completeness:</span>
                                <strong style="color: #457eb8; font-size: 18px;">{stats['profile_completeness']}%</strong>
                            </div>
                            <div style="background: #e9ecef; height: 8px; border-radius: 4px; overflow: hidden; margin-top: 5px;">
                                <div style="background: #457eb8; height: 100%; width: {stats['profile_completeness']}%;"></div>
                            </div>
                            <p style="margin: 5px 0 0 0; color: #999; font-size: 11px; font-style: italic;">Based on core info (40%), contact details (20%), address (15%), content & branding (15%), and social links (10%)</p>
                        </div>
                        <div style="margin-top: 15px;">
                            <span style="color: #666;">QR Code Programmed:</span> {qr_status}
                            {qr_link}
                            <p style="margin: 5px 0 0 0; color: #999; font-size: 11px; font-style: italic;">Whether your QR code has been generated and is ready to use</p>
                        </div>
                    </div>

                    <!-- Usage Section -->
                    <div style="background: ' + (partner.primary_color or '#ffffff') + '; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                        <h3 style="color: #333; font-size: 18px; margin: 0 0 15px 0;">📱 Usage Stats</h3>
                        <div style="display: flex; justify-content: space-between; margin-bottom: 10px;">
                            <span style="color: #666;">Page Views:</span>
                            <strong style="color: #333; font-size: 18px;">{stats['page_views']}</strong>
                        </div>
                        <p style="margin: 0 0 10px 0; color: #999; font-size: 11px; font-style: italic;">Total number of times your {brand_name} Card page has been viewed (via your unique URL)</p>
                        <div style="display: flex; justify-content: space-between;">
                            <span style="color: #666;">QR Code Scans:</span>
                            <strong style="color: #333; font-size: 18px;">{stats['scans_count']}</strong>
                        </div>
                        <p style="margin: 5px 0 0 0; color: #999; font-size: 11px; font-style: italic;">Total number of times your QR code has been scanned</p>
                    </div>

                    <!-- Referral Stats Section -->
                    {self._get_referral_stats_html(stats.get('referral_stats', {}))}
                </div>

                <!-- CTA Section -->
                <div style="text-align: center; padding: 30px 0; border-top: 2px solid #e0e0e0;">
                    <a href="{vcard_url}" 
                       style="display: inline-block; background-color: #457eb8; color: #ffffff; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                        View Your {brand_name} Card →
                    </a>
                    <p style="margin: 20px 0 0 0; color: #666; font-size: 12px;">
                        <a href="{base_url}/web#id={self.id}&model=partner.vcard&view_type=form&active_id={self.id}" 
                           style="color: #007bff; text-decoration: none;">Manage Digest Settings</a>
                    </p>
                </div>

                <!-- Footer -->
                <div style="text-align: center; padding: 20px 0; border-top: 1px solid #e0e0e0; color: #999; font-size: 12px;">
                    <p style="margin: 0;">This is an automated digest email from {brand_name}.</p>
                    <p style="margin: 5px 0 0 0;">You can change your digest preferences in your {brand_name} Card settings.</p>
                </div>
            </div>
            """
            
            # Create mail values
            mail_values = {
                'subject': f"{period_display}'s Digest - {self.name or f'Your {brand_name} Card'}",
                'body_html': Markup(body_html),
                'email_from': self._get_notification_email(user=self.env.user),
                'email_to': self.email,
                'auto_delete': True,
                'model': 'partner.vcard',
                'res_id': self.id,
            }
            
            # Send the email
            mail = self.env['mail.mail'].sudo().create(mail_values)
            mail.send()
            
            # Update last_digest_sent
            self.write({'last_digest_sent': fields.Datetime.now()})
            return True
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"Error sending digest email to {self.email}: {str(e)}")
            return False
    
    @api.model
    @staticmethod
    def _lookup_geolocation(ip_address):
        """Look up IP geolocation via free public providers.

        Returns a dict with country / city / timezone / country_code / region,
        or None if all providers fail or the IP is local. Called from
        _cron_enrich_geolocation — never on a user-facing request path.
        """
        if not ip_address or ip_address in ('127.0.0.1', 'localhost', '::1'):
            return None
        import urllib.request
        import urllib.error
        providers = (
            (
                'geojs.io',
                f'https://get.geojs.io/v1/ip/geo/{ip_address}.json',
                lambda d: {
                    'country': d.get('country', ''),
                    'city': d.get('city', ''),
                    'timezone': d.get('timezone', ''),
                    'country_code': d.get('country_code', ''),
                    'region': d.get('region', ''),
                } if d else None,
            ),
            (
                'ip-api.com',
                f'http://ip-api.com/json/{ip_address}?fields=status,country,countryCode,city,timezone,regionName',
                lambda d: {
                    'country': d.get('country', ''),
                    'city': d.get('city', ''),
                    'timezone': d.get('timezone', ''),
                    'country_code': d.get('countryCode', ''),
                    'region': d.get('regionName', ''),
                } if d and d.get('status') == 'success' else None,
            ),
        )
        for name, url, parser in providers:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Vinc-Odoo/1.0'})
                with urllib.request.urlopen(req, timeout=4) as resp:
                    import json as _json
                    data = _json.loads(resp.read().decode())
                    result = parser(data)
                    if result:
                        return result
            except Exception as err:
                _logger.debug("Geolocation provider %s failed for %s: %s", name, ip_address, err)
                continue
        return None

    @api.model
    def _cron_enrich_geolocation(self, batch_size=50, window_days=180):
        """Backfill country / city / timezone on recent leads and downloads.

        Runs every 5 minutes. Processes up to `batch_size` rows per model per
        tick so a large backlog is drained smoothly instead of blocking the
        cron worker. Considers rows created in the last `window_days` days
        (default 180) — wide enough to fill an accumulated backlog (e.g. rows
        that piled up while this cron was disabled) on the next few ticks,
        while still letting very old, permanently-unresolvable IPs age out so
        the cron doesn't retry them forever.
        """
        from datetime import datetime, timedelta
        recent_cutoff = datetime.now() - timedelta(days=window_days)

        # Leads submitted through the public /create_lead handler.
        leads = self.env['crm.lead'].sudo().search([
            ('submission_ip', '!=', False),
            ('submission_ip', '!=', ''),
            ('submission_country', 'in', (False, '')),
            ('create_date', '>=', recent_cutoff),
        ], limit=batch_size)
        for lead in leads:
            geo = self._lookup_geolocation(lead.submission_ip)
            if not geo:
                continue
            lead.sudo().write({
                'submission_country': geo.get('country', ''),
                'submission_city': geo.get('city', ''),
                'submission_timezone': geo.get('timezone', ''),
            })

        # vCard download tracking rows.
        downloads = self.env['vcard.download.tracking'].sudo().search([
            ('download_ip', '!=', False),
            ('download_ip', '!=', ''),
            ('download_country', 'in', (False, '')),
            ('create_date', '>=', recent_cutoff),
        ], limit=batch_size)
        for dl in downloads:
            geo = self._lookup_geolocation(dl.download_ip)
            if not geo:
                continue
            dl.sudo().write({
                'download_country': geo.get('country', ''),
                'download_city': geo.get('city', ''),
                'download_timezone': geo.get('timezone', ''),
            })

    def _cron_send_digest_emails(self):
        """Cron job to send digest emails to all eligible vCards"""
        from datetime import datetime, timedelta
        
        now = datetime.now()
        
        # Get all vCards with digest enabled
        vcards = self.search([
            ('digest_enabled', '=', True),
            ('email', '!=', False),
        ])
        
        for vcard in vcards:
            # Check if it's time to send based on frequency
            should_send = False
            
            if not vcard.last_digest_sent:
                # Never sent, send now
                should_send = True
            else:
                last_sent = fields.Datetime.from_string(vcard.last_digest_sent)
                time_since_last = now - last_sent
                
                if vcard.digest_frequency == 'daily':
                    # Daily: send if 24+ hours have passed
                    should_send = time_since_last >= timedelta(days=1)
                elif vcard.digest_frequency == 'weekly':
                    # Weekly: send if 7+ days have passed
                    should_send = time_since_last >= timedelta(days=7)
                elif vcard.digest_frequency == 'monthly':
                    # Monthly: send if 30+ days have passed
                    should_send = time_since_last >= timedelta(days=30)
            
            if should_send:
                vcard._send_digest_email()
    
    def action_send_test_digest(self):
        """Send a test digest email immediately (for testing purposes)"""
        self.ensure_one()
        
        if not self.email:
            brand_name = self.env['qr_code_odoo.brand'].sudo().get_brand_name()
            raise UserError(f'Please set an email address on your {brand_name} Card to receive digest emails.')
        
        if not self.digest_enabled:
            raise UserError('Please enable digest emails first.')
        
        result = self._send_digest_email(force_send=True)
        
        if result:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': f'Test digest email sent to {self.email}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            raise UserError('Failed to send digest email. Please check the logs for details.')
    
    def action_test_intro_email(self):
        """Preview intro email template with sample data"""
        self.ensure_one()
        from odoo.exceptions import UserError
        
        if not self.intro_email_enabled:
            raise UserError("Please enable 'Send intro email automatically' first.")
        
        # Prepare template variables
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        vcard_url = self.website_full_url or f"{base_url}/{self.website_slug}" if self.website_slug else base_url
        booking_url = self.calendly_url or vcard_url
        
        template_vars = {
            'contact_name': 'John Smith',
            'first_name': 'John',
            'vcard_url': vcard_url,
            'booking_url': booking_url,
            'owner_name': self.name or 'Your Name',
            'owner_phone': self.phone or self.mobile or '+1234567890',
            'owner_email': self.email or 'you@example.com',
            'company_name': self.company_name or 'Your Company',
            'owner_title': self.function or 'Your Title',
        }
        
        # Get email template and process it
        email_template = self.intro_email_template or "<p>Hi {contact_name},</p><p>Great meeting you today. I'm {owner_name} (cc'd), here's my info and how to reach me:</p><p><strong>Email:</strong> {owner_email}<br/><strong>Phone:</strong> {owner_phone}<br/><strong>My vCard:</strong> <a href='{vcard_url}'>{vcard_url}</a></p><p>Looking forward to connecting!<br/>{owner_name}</p>"
        
        # Process template with fallbacks and conditionals
        body_html = self._process_template(email_template, template_vars, escape_html=True)
        subject = f'Great meeting you today - {self.name or "Your Name"}'
        
        # Create preview record
        preview = self.env['leadback.preview'].create({
            'preview_type': 'email',
            'subject': subject,
            'body_html': body_html,
            'email_to': 'john.smith@example.com',
            'email_from': self._get_notification_email(user=self.env.user),
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Intro Email Preview',
            'res_model': 'leadback.preview',
            'res_id': preview.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_preview_type': 'email'},
        }
    
    def action_test_email(self):
        """Preview email template with sample data"""
        self.ensure_one()
        from odoo.exceptions import UserError
        
        if not self.leadback_send_email:
            raise UserError("Please enable 'Enable Automated Email' first.")
        
        # Prepare template variables
        vcard_url = self.website_full_url or f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/{self.website_slug}"
        booking_url = self.calendly_url or ''
        
        template_vars = {
            'contact_name': 'John Smith',
            'first_name': 'John',
            'vcard_url': vcard_url,
            'short_vcard_url': vcard_url,
            'booking_url': booking_url,
            'owner_name': self.name or 'Your Name',
            'owner_phone': self.phone or self.mobile or '+1234567890',
            'owner_email': self.email or 'you@example.com',
            'company_name': self.company_name or 'Your Company',
            'owner_title': self.function or 'Your Title',
            'lead_source': 'QR Code',
            'event_name': 'Sample Event',
            'profile_variant': 'Standard',
        }
        
        # Process templates
        subject = self._process_template(self.leadback_email_subject or 'Test Email', template_vars, escape_html=False)
        body_html = self._process_template(self.leadback_email_template or '<p>Test email</p>', template_vars, escape_html=True)
        
        # Create preview record
        preview = self.env['leadback.preview'].create({
            'preview_type': 'email',
            'subject': subject,
            'body_html': body_html,
            'email_to': 'john.smith@example.com',
            'email_from': self.email or self.env.user.email or 'you@example.com',
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Email Preview',
            'res_model': 'leadback.preview',
            'res_id': preview.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_preview_type': 'email'},
        }
    
    def action_test_message(self):
        """Generate test messaging links"""
        self.ensure_one()
        from odoo.exceptions import UserError
        
        if not self.leadback_enable_messaging:
            raise UserError("Please enable 'Enable Click to Chat' first.")
        
        if not self.leadback_channels:
            raise UserError("Please select at least one messaging channel.")
        
        # Prepare template variables
        vcard_url = self.website_full_url or f"{self.env['ir.config_parameter'].sudo().get_param('web.base.url')}/{self.website_slug}"
        booking_url = self.calendly_url or ''
        
        template_vars = {
            'contact_name': 'Test Contact',
            'first_name': 'Test',
            'vcard_url': vcard_url,
            'short_vcard_url': vcard_url,
            'booking_url': booking_url,
            'owner_name': self.name or 'me',
            'owner_phone': self.phone or self.mobile or '',
            'owner_email': self.email or '',
            'company_name': self.company_name or '',
            'owner_title': self.function or '',
            'lead_source': 'Test',
            'event_name': '',
            'profile_variant': '',
        }
        
        # Process message template
        message_text = self._process_template(self.leadback_message_template or 'Test message', template_vars)
        
        # Generate test links (using a test phone number)
        test_phone = '+1234567890'
        links = []
        channel_names = []
        
        for channel in self.leadback_channels:
            channel_names.append(channel.name)
            if channel.name == 'WhatsApp':
                result = self._send_whatsapp_message(test_phone, message_text)
                if result.get('status') == 'success' and result.get('url'):
                    links.append({
                        'name': 'WhatsApp',
                        'url': result['url'],
                        'icon': '💬'
                    })
            elif channel.name == 'Viber':
                result = self._send_viber_message(test_phone, message_text)
                if result.get('status') == 'success' and result.get('url'):
                    links.append({
                        'name': 'Viber',
                        'url': result['url'],
                        'icon': '💜'
                    })
            elif channel.name == 'Telegram':
                result = self._send_telegram_message(test_phone, message_text)
                if result.get('status') == 'success' and result.get('url'):
                    links.append({
                        'name': 'Telegram',
                        'url': result['url'],
                        'icon': '✈️'
                    })
        
        if not links:
            raise UserError("Failed to generate test links. Please check your channel configuration.")
        
        # Create links HTML
        links_html = '<br/>'.join([
            f'<div style="margin: 8px 0;"><strong>{link["icon"]} {link["name"]}:</strong> <a href="{link["url"]}" target="_blank" style="color: #0066cc; word-break: break-all;">{link["url"]}</a></div>'
            for link in links
        ])
        
        # Create preview record
        preview = self.env['leadback.preview'].create({
            'preview_type': 'message',
            'message_preview': message_text,
            'message_to': '+1234567890 (Test Phone)',
            'channels': ', '.join(channel_names),
            'links_html': links_html,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Message Preview',
            'res_model': 'leadback.preview',
            'res_id': preview.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_preview_type': 'message'},
        }
    
    def _send_instant_leadback_message(self, contact_name, contact_phone, contact_email, opportunity):
        """
        Send instant lead-back message to a new contact via email (automated) and messaging links (click-to-chat).
        
        :param contact_name: Name of the contact
        :param contact_phone: Phone number of the contact
        :param contact_email: Email of the contact
        :param opportunity: CRM lead/opportunity record
        :return: dict with status and message
        """
        self.ensure_one()
        
        try:
            if not self.enable_instant_leadback:
                return {'status': 'disabled', 'message': 'Instant lead-back is disabled'}
            
            # Email side is now handled exclusively by the Intro Email path —
            # leadback_send_email is deprecated UI-side and force-disabled here
            # so existing records with the old flag still set don't double-send.
            has_email = False
            # Click-to-Chat is the entire purpose of this feature now; the
            # leadback_enable_messaging sub-toggle was dropped from the UI in
            # favor of treating enable_instant_leadback itself as the chat toggle.
            has_messaging = bool(contact_phone and self.leadback_channels)

            # If messaging is enabled on the card but a precondition is missing,
            # leave a trail so it's not mysteriously silent. Common case: the
            # visitor didn't fill the phone field, so there's nowhere to send
            # click-to-chat URLs.
            if self.leadback_enable_messaging and not has_messaging and opportunity:
                if not contact_phone:
                    reason = "visitor did not provide a phone number"
                elif not self.leadback_channels:
                    reason = "no messaging channels selected on this card"
                else:
                    reason = "messaging precondition missing"
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(f"Instant lead-back messaging skipped for opportunity {opportunity.id}: {reason}")
                opportunity.message_post(
                    body=f"<p><strong>Messaging links not generated</strong></p>"
                         f"<p>Reason: {reason}.</p>"
                         f"<p>Click-to-chat URLs (WhatsApp/Viber/Telegram) need a destination phone. Ask the visitor to include a phone on the lead form, or disable messaging on this card.</p>",
                    subject="Instant Lead-Back — messaging skipped"
                )

            if not has_email and not has_messaging:
                return {'status': 'error', 'message': 'Either email or phone messaging must be configured'}
            
            # Validate messaging requirements if messaging is enabled
            if self.leadback_enable_messaging and contact_phone:
                if not self.leadback_channels:
                    return {'status': 'error', 'message': 'No messaging channels selected'}
            
            # Prepare template variables
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            vcard_url = self.website_full_url or f"{base_url}/{self.website_slug}" if self.website_slug else base_url
            booking_url = self.calendly_url or vcard_url
            
            # Extract first name from contact name
            first_name = contact_name.split()[0] if contact_name and ' ' in contact_name else (contact_name or 'there')
            
            template_vars = {
                'contact_name': contact_name or 'there',
                'first_name': first_name,
                'vcard_url': vcard_url,
                'short_vcard_url': vcard_url,
                'booking_url': booking_url,
                'owner_name': self.name or 'me',
                'owner_phone': self.phone or self.mobile or '',
                'owner_email': self.email or '',
                'company_name': self.company_name or '',
                'owner_title': self.function or '',
                'lead_source': 'QR Code',
                'event_name': '',
                'profile_variant': '',
            }
            
            # Process message template with fallbacks and conditionals
            message_template = (self.leadback_message_template or 
                              "Hi {first_name|there}! 👋\n\nGreat meeting you — here's my contact card:\n{vcard_url}")
            message = self._process_template(message_template, template_vars)
            
            # Schedule or send messages to all selected channels (only if messaging is enabled)
            results = []
            channel_names = []
            
            if self.leadback_enable_messaging and has_messaging:
                # Calculate message delay
                message_delay_amount = self.leadback_message_delay or 0
                message_delay_type = self.leadback_message_delay_type or 'minutes'
                
                try:
                    # If there's a delay, we'll generate links immediately but log them as scheduled
                    # (Since click-to-chat links can't be "scheduled", we generate them but note the delay)
                    for channel in self.leadback_channels:
                        try:
                            if channel.code == 'whatsapp':
                                result = self._send_whatsapp_message(contact_phone, message)
                            elif channel.code == 'viber':
                                result = self._send_viber_message(contact_phone, message)
                            elif channel.code == 'telegram':
                                result = self._send_telegram_message(contact_phone, message)
                            else:
                                result = {'status': 'error', 'message': f'Unknown channel code: {channel.code}'}
                            
                            results.append({
                                'channel': channel.name,
                                'code': channel.code,
                                'result': result
                            })
                            channel_names.append(channel.name)
                            
                        except Exception as e:
                            import logging
                            _logger = logging.getLogger(__name__)
                            _logger.exception(f"Error sending message via {channel.name}: {e}")
                            results.append({
                                'channel': channel.name,
                                'code': channel.code,
                                'result': {'status': 'error', 'message': str(e)}
                            })
                except Exception as e:
                    import logging
                    _logger = logging.getLogger(__name__)
                    _logger.exception(f"Error in messaging loop: {e}")
            
            # Schedule or send automated email if enabled
            email_scheduled = False
            if self.leadback_send_email and contact_email:
                try:
                    email_result = self._schedule_automated_email(contact_name, contact_email, opportunity, template_vars)
                    email_scheduled = email_result.get('status') in ['success', 'scheduled']
                except Exception as e:
                    import logging
                    _logger = logging.getLogger(__name__)
                    _logger.exception(f"Error scheduling automated email: {e}")
            
            # Log messages to lead timeline
            if opportunity:
                # Build status message
                status_parts = []
                if email_scheduled:
                    delay_info = self._get_delay_info(self.leadback_email_delay_type, self.leadback_email_delay)
                    if delay_info:
                        status_parts.append(f"Email: Scheduled ({delay_info})")
                    else:
                        status_parts.append("Email: Sent")
                if results:
                    success_count = sum(1 for r in results if r['result'].get('status') == 'success')
                    total_count = len(results)
                    delay_info = self._get_delay_info(self.leadback_message_delay_type, self.leadback_message_delay)
                    if delay_info:
                        status_parts.append(f"Messaging: Scheduled ({delay_info})")
                    else:
                        status_parts.append(f"Messaging: {success_count}/{total_count} links")
                
                status_str = " | ".join(status_parts) if status_parts else "No actions"
                
                # Build message content
                message_parts = []
                if email_scheduled:
                    delay_info = self._get_delay_info(self.leadback_email_delay_type, self.leadback_email_delay)
                    if delay_info:
                        message_parts.append(f"<p><strong>✓ Automated Email Scheduled</strong><br/>To: {contact_email}<br/>Will send in: {delay_info}</p>")
                    else:
                        message_parts.append(f"<p><strong>✓ Automated Email Sent</strong><br/>To: {contact_email}</p>")
                
                if results:
                    success_count = sum(1 for r in results if r['result'].get('status') == 'success')
                    if success_count > 0:
                        channels_str = ', '.join(channel_names)
                        task_links = []
                        for result_item in results:
                            if result_item['result'].get('status') == 'success' and result_item['result'].get('url'):
                                url = result_item['result'].get('url')
                                task_links.append(
                                    f"<li><a href='{url}' target='_blank'>{result_item['channel']}</a></li>"
                                )
                        
                        if task_links:
                            links_html = "".join(task_links)
                            message_parts.append(
                                f"<p><strong>Messaging Links Generated ({channels_str})</strong><br/>"
                                f"To: {contact_phone}<br/>"
                                f"Links: <ul style='margin: 5px 0;'>{links_html}</ul></p>"
                            )
                
                if message_parts:
                    body_message = Markup(
                        f"<p><strong>Instant Lead-Back Sent</strong></p>"
                        f"{''.join(message_parts)}"
                        f"<p><em>Status: {status_str}</em></p>"
                    )
                    opportunity.message_post(
                        body=body_message,
                        subject="Instant Lead-Back"
                    )
                    
                    # Log individual failures
                    for result_item in results:
                        if result_item['result'].get('status') != 'success':
                            opportunity.message_post(
                                body=f"<p><strong>Instant Lead-Back Message Failed</strong></p>"
                                     f"<p>Channel: {result_item['channel']}</p>"
                                     f"<p>To: {contact_phone}</p>"
                                     f"<p>Error: {result_item['result'].get('message', 'Unknown error')}</p>",
                                subject=f"Instant Lead-Back Failed - {result_item['channel']}"
                            )
                
                # Return summary
                success_count = sum(1 for r in results if r['result'].get('status') == 'success')
                if success_count == len(results):
                    return {'status': 'success', 'message': f'Messages sent via {", ".join(channel_names)}', 'results': results}
                elif success_count > 0:
                    return {'status': 'partial', 'message': f'{success_count}/{len(results)} messages sent', 'results': results}
                else:
                    return {'status': 'error', 'message': 'All message attempts failed', 'results': results}
                    
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception(f"Error sending instant lead-back message: {e}")
            
            # Log error to lead timeline
            if opportunity:
                opportunity.message_post(
                    body=f"<p><strong>Instant Lead-Back Message Error</strong></p>"
                         f"<p>Error: {str(e)}</p>",
                    subject="Instant Lead-Back Message Error"
                )
            
            return {'status': 'error', 'message': str(e)}
    
    def _process_template(self, template, template_vars, escape_html=False):
        """
        Process template with fallback syntax and conditional blocks.

        Supports:
        - Fallbacks: {placeholder|fallback} - uses fallback if placeholder is empty
        - Conditionals: {if field}...{/if} - shows content only if field exists and is not empty

        :param template: Template string with placeholders.
        :param template_vars: Dictionary of variable values.
        :param escape_html: When True, substituted values are HTML-escaped
            before they are injected into the template. Pass True whenever the
            output is sent as ``body_html`` or rendered as HTML — otherwise an
            attacker-controlled field (e.g. a lead's ``contact_name``) can
            inject phishing links or markup into the owner's trusted intro
            email. Fallback strings and template literal content are kept as
            authored so owners can still write HTML templates.
        :return: Processed template string.
        """
        import re
        from markupsafe import escape as _esc

        def _fmt(value):
            if value is None:
                return ''
            s = str(value)
            return str(_esc(s)) if escape_html else s

        # First, process conditional blocks {if field}...{/if}
        def process_conditionals(text):
            # Pattern to match {if field}...{/if}
            pattern = r'\{if\s+(\w+)\}(.*?)\{/if\}'

            def replace_conditional(match):
                field_name = match.group(1)
                content = match.group(2)
                # Check if field exists and is not empty
                field_value = template_vars.get(field_name, '')
                if field_value and str(field_value).strip():
                    return content
                return ''

            return re.sub(pattern, replace_conditional, text, flags=re.DOTALL)

        # Process conditionals first
        processed = process_conditionals(template)

        # Then process fallbacks {placeholder|fallback}
        def process_fallbacks(text):
            # Pattern to match {placeholder|fallback}
            pattern = r'\{(\w+)\|([^}]+)\}'

            def replace_fallback(match):
                placeholder = match.group(1)
                fallback = match.group(2)
                value = template_vars.get(placeholder, '')
                if value and str(value).strip():
                    return _fmt(value)
                return fallback

            return re.sub(pattern, replace_fallback, text)

        processed = process_fallbacks(processed)

        # Finally, replace remaining placeholders. Escape values when asked.
        safe_vars = {k: _fmt(v) for k, v in template_vars.items()} if escape_html else template_vars
        try:
            return processed.format(**safe_vars)
        except KeyError as e:
            # If placeholder doesn't exist, leave it as is
            import logging
            _logger = logging.getLogger(__name__)
            _logger.warning(f"Missing placeholder in template: {e}")
            # Replace missing placeholders with empty string
            pattern = r'\{(\w+)\}'
            return re.sub(pattern, '', processed)
    
    def _get_delay_info(self, delay_type, delay_amount):
        """Get human-readable delay information"""
        if not delay_amount or delay_amount == 0:
            return None
        if delay_type == 'minutes':
            return f"{delay_amount} minute{'s' if delay_amount != 1 else ''}"
        elif delay_type == 'hours':
            return f"{delay_amount} hour{'s' if delay_amount != 1 else ''}"
        elif delay_type == 'days':
            return f"{delay_amount} day{'s' if delay_amount != 1 else ''}"
        return None
    
    def _schedule_followup_reminders(self, opportunity, contact_name):
        """
        Schedule follow-up reminder activities for a new lead based on configured reminder templates.
        
        For day-based delays: Creates activities immediately with the correct date_deadline.
        For minute/hour delays: Stores reminders in a queue to be processed by a cron job.
        
        :param opportunity: CRM lead/opportunity record
        :param contact_name: Name of the contact
        :return: Tuple of (activities_created_immediately, reminders_queued)
        """
        self.ensure_one()
        
        import logging
        _logger = logging.getLogger(__name__)
        
        _logger.info("=" * 80)
        _logger.info(f"FOLLOW-UP REMINDER SCHEDULING - Starting")
        _logger.info(f"vCard ID: {self.id}, vCard Name: {self.name}")
        _logger.info(f"Opportunity ID: {opportunity.id}, Contact Name: {contact_name}")
        _logger.info(f"Follow-up reminders enabled: {self.followup_reminders_enabled}")
        _logger.info("=" * 80)
        
        if not self.followup_reminders_enabled:
            _logger.info("Follow-up reminders are disabled for this vCard. Skipping.")
            return (0, 0)
        
        # Get active reminders, ordered by sequence
        reminders = self.followup_reminder_ids.filtered(lambda r: r.active)
        _logger.info(f"Found {len(reminders)} active reminder template(s)")
        
        if not reminders:
            _logger.info("No active reminder templates found. Skipping.")
            return (0, 0)
        
        from datetime import datetime, timedelta, date
        
        activities_created = 0
        reminders_queued = 0
        
        # Use Odoo's timezone-aware datetime
        now_dt_str = fields.Datetime.now()
        now_dt = fields.Datetime.from_string(now_dt_str)
        now_date = fields.Date.today()
        
        _logger.info(f"Current datetime: {now_dt_str} (parsed: {now_dt})")
        _logger.info(f"Current date: {now_date}")
        
        # Track created activities for "after_previous_activity" scheduling
        previous_activity_id = None
        
        for reminder in reminders:
            try:
                _logger.info("-" * 80)
                _logger.info(f"Processing reminder template: '{reminder.name}' (ID: {reminder.id})")
                _logger.info(f"  Schedule Type: {reminder.schedule_type}")
                _logger.info(f"  Delay: {reminder.delay_amount} {reminder.delay_type}")
                _logger.info(f"  Activity Type: {reminder.activity_type_id.name if reminder.activity_type_id else 'N/A'}")
                
                # Determine the base datetime for calculation
                if reminder.schedule_type == 'after_previous_activity' and previous_activity_id:
                    # For "after_previous_activity", we need to wait for the previous activity to be completed
                    # We'll queue this reminder with a reference to the previous activity
                    # The cron will check when the previous activity is done
                    _logger.info(f"  Schedule type is 'after_previous_activity', will wait for previous activity ID {previous_activity_id}")
                    # Set scheduled_datetime to a far future date initially - will be updated when previous activity completes
                    due_datetime = now_dt + timedelta(days=365)  # Placeholder, will be recalculated
                    base_for_calculation = now_dt  # Will be updated when previous activity completes
                else:
                    # For "after_creation", use current datetime
                    base_for_calculation = now_dt
                    # Calculate the due datetime based on delay
                    if reminder.delay_type == 'minutes':
                        due_datetime = base_for_calculation + timedelta(minutes=reminder.delay_amount)
                    elif reminder.delay_type == 'hours':
                        due_datetime = base_for_calculation + timedelta(hours=reminder.delay_amount)
                    elif reminder.delay_type == 'days':
                        due_datetime = base_for_calculation + timedelta(days=reminder.delay_amount)
                    else:
                        _logger.warning(f"  Unknown delay_type '{reminder.delay_type}', defaulting to now")
                        due_datetime = base_for_calculation
                
                # Calculate the date_deadline (for the activity's deadline field)
                if reminder.delay_type == 'days':
                    date_deadline = due_datetime.date()
                elif reminder.delay_type == 'hours':
                    # For hour delays, if it's still today, set to tomorrow
                    if due_datetime.date() <= now_date:
                        date_deadline = now_date + timedelta(days=1)
                    else:
                        date_deadline = due_datetime.date()
                else:  # minutes
                    # For minute delays, if it's still today, set to tomorrow
                    if due_datetime.date() <= now_date:
                        date_deadline = now_date + timedelta(days=1)
                    else:
                        date_deadline = due_datetime.date()
                
                _logger.info(f"  Calculated due_datetime: {due_datetime}")
                _logger.info(f"  Calculated date_deadline: {date_deadline}")
                
                # Process summary with placeholders
                summary = reminder.summary or reminder.activity_type_id.name or 'Follow-up'
                original_summary = summary
                if '{contact_name}' in summary:
                    summary = summary.replace('{contact_name}', contact_name or 'Contact')
                    _logger.info(f"  Summary placeholder replaced: '{original_summary}' -> '{summary}'")
                else:
                    _logger.info(f"  Summary: '{summary}' (no placeholders to replace)")
                
                # Determine assigned user
                assigned_user = reminder.user_id
                if not assigned_user:
                    _logger.info("  No user specified in reminder template, trying to find from vCard owner email")
                    # Try to get user from vCard owner's email
                    if self.email:
                        user = self.env['res.users'].sudo().search([
                            ('login', '=', self.email)
                        ], limit=1)
                        if user:
                            assigned_user = user
                            _logger.info(f"  Found user from email '{self.email}': {assigned_user.name} (ID: {assigned_user.id})")
                        else:
                            _logger.info(f"  No user found with email '{self.email}'")
                    # Fallback to current user
                    if not assigned_user:
                        assigned_user = self.env.user
                        _logger.info(f"  Using current user as fallback: {assigned_user.name} (ID: {assigned_user.id})")
                else:
                    _logger.info(f"  Using user from reminder template: {assigned_user.name} (ID: {assigned_user.id})")
                
                # Handle scheduling based on schedule_type and delay_type
                if reminder.schedule_type == 'after_previous_activity':
                    if not previous_activity_id:
                        _logger.warning(f"  'After previous activity' type but no previous activity exists. This reminder will be skipped.")
                        continue
                    
                    # Queue for processing after previous activity completes
                    _logger.info(f"  'After previous activity' type: Queueing reminder to wait for activity ID {previous_activity_id}")
                    
                    scheduled_reminder = self.env['followup.scheduled.reminder'].sudo().create({
                        'opportunity_id': opportunity.id,
                        'contact_name': contact_name or 'Contact',
                        'reminder_template_id': reminder.id,
                        'scheduled_datetime': fields.Datetime.to_string(due_datetime),  # Placeholder, will be updated when previous activity completes
                        'date_deadline': date_deadline,  # Placeholder, will be recalculated
                        'activity_type_id': reminder.activity_type_id.id,
                        'summary': summary,
                        'note': reminder.note or '',
                        'user_id': assigned_user.id,
                        'previous_activity_id': previous_activity_id,
                    })
                    reminders_queued += 1
                    
                    _logger.info(
                        f"  ✓ Reminder queued (waiting for previous activity): Scheduled reminder ID {scheduled_reminder.id}, "
                        f"Previous activity ID: {previous_activity_id}, Assigned to: {assigned_user.name}"
                    )
                    # Don't update previous_activity_id - this reminder's activity will be created later
                    continue  # Skip to next reminder
                    
                elif reminder.delay_type == 'days':
                    # Day-based delay: create activity immediately
                    _logger.info(f"  Day-based delay: Creating activity immediately with date_deadline: {date_deadline}")
                    
                    # Create the activity using activity_schedule method
                    activity = opportunity.sudo().activity_schedule(
                        activity_type_id=reminder.activity_type_id.id,
                        summary=summary,
                        note=reminder.note or '',
                        date_deadline=date_deadline,
                        user_id=assigned_user.id,
                    )
                    activities_created += 1
                    previous_activity_id = activity.id  # Track for next reminder
                    
                    _logger.info(
                        f"  ✓ Activity created immediately: ID {activity.id}, "
                        f"Due date: {date_deadline}, Assigned to: {assigned_user.name}"
                    )
                    
                else:
                    # Minute or hour delay - queue for cron processing
                    _logger.info(f"  Minute/hour delay: Queueing reminder for scheduled processing at {due_datetime}")
                    
                    scheduled_reminder = self.env['followup.scheduled.reminder'].sudo().create({
                        'opportunity_id': opportunity.id,
                        'contact_name': contact_name or 'Contact',
                        'reminder_template_id': reminder.id,
                        'scheduled_datetime': fields.Datetime.to_string(due_datetime),
                        'date_deadline': date_deadline,
                        'activity_type_id': reminder.activity_type_id.id,
                        'summary': summary,
                        'note': reminder.note or '',
                        'user_id': assigned_user.id,
                    })
                    reminders_queued += 1
                    
                    # For "after_creation" type with minute/hour delays, we can't track the activity yet
                    # But we can update previous_activity_id when the activity is created by the cron
                    # For now, we'll track it via the scheduled_reminder's activity_id after creation
                    
                    _logger.info(
                        f"  ✓ Reminder queued: Scheduled reminder ID {scheduled_reminder.id}, "
                        f"Will be processed at {due_datetime}, Date deadline: {date_deadline}, Assigned to: {assigned_user.name}"
                    )
                
            except Exception as e:
                _logger.exception(
                    f"  ✗ ERROR scheduling follow-up reminder '{reminder.name}' (ID: {reminder.id}) "
                    f"for lead {opportunity.id}: {e}"
                )
                # Continue with other reminders even if one fails
                continue
        
        _logger.info("=" * 80)
        _logger.info(f"FOLLOW-UP REMINDER SCHEDULING - Completed")
        _logger.info(f"  Activities created immediately: {activities_created}")
        _logger.info(f"  Reminders queued for cron processing: {reminders_queued}")
        _logger.info(f"  Total reminders processed: {activities_created + reminders_queued}")
        _logger.info("=" * 80)
        
        return (activities_created, reminders_queued)
    
    def _schedule_automated_email(self, contact_name, contact_email, opportunity, template_vars):
        """
        Schedule or send automated email to new lead using Odoo's email system.
        
        :param contact_name: Name of the contact
        :param contact_email: Email address of the contact
        :param opportunity: CRM lead/opportunity record
        :param template_vars: Dictionary with template variables
        :return: dict with status and message
        """
        try:
            from datetime import datetime, timedelta
            
            # Get email template and process it with fallbacks and conditionals
            email_template = (self.leadback_email_template or 
                            "<p>Hi {contact_name|there}!</p><p>Great meeting you earlier! Here's my digital card: <a href='{vcard_url}'>{vcard_url}</a></p>")
            
            # Process template with fallbacks and conditionals
            email_body_html = self._process_template(email_template, template_vars, escape_html=True)
            
            # Get email subject and process it
            email_subject = self.leadback_email_subject or "Great meeting you!"
            email_subject = self._process_template(email_subject, template_vars)
            
            # Calculate scheduled time
            delay_amount = self.leadback_email_delay or 0
            delay_type = self.leadback_email_delay_type or 'minutes'
            
            if delay_amount > 0:
                now = datetime.now()
                if delay_type == 'minutes':
                    scheduled_time = now + timedelta(minutes=delay_amount)
                elif delay_type == 'hours':
                    scheduled_time = now + timedelta(hours=delay_amount)
                elif delay_type == 'days':
                    scheduled_time = now + timedelta(days=delay_amount)
                else:
                    scheduled_time = now
            else:
                scheduled_time = None  # Send immediately
            
            # Prepare mail values
            mail_values = {
                'subject': email_subject,
                'body_html': email_body_html,
                'email_to': contact_email,
                'email_from': self._get_notification_email(user=self.env.user),
                'auto_delete': False,
            }
            
            # Schedule or send immediately
            if scheduled_time:
                # Store scheduled email for cron to process
                scheduled_email = self.env['leadback.scheduled.email'].sudo().create({
                    'partner_vcard_id': self.id,
                    'contact_name': contact_name,
                    'contact_email': contact_email,
                    'opportunity_id': opportunity.id if opportunity else False,
                    'email_subject': email_subject,
                    'email_body_html': email_body_html,
                    'scheduled_time': scheduled_time,
                    'state': 'pending'
                })
                
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(f"Email scheduled for {scheduled_time} to {contact_email} for lead {opportunity.id if opportunity else 'N/A'}")
                
                return {
                    'status': 'scheduled',
                    'message': f'Email scheduled to send in {self._get_delay_info(delay_type, delay_amount)}',
                    'scheduled_email_id': scheduled_email.id,
                    'scheduled_time': scheduled_time.isoformat() if scheduled_time else None
                }
            else:
                # Queue for the mail cron instead of blocking on SMTP here.
                # state='outgoing' is the default on create, so the cron picks
                # it up within a minute without this request waiting.
                mail = self.env['mail.mail'].sudo().create(mail_values)

                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(f"Automated leadback email queued (id={mail.id}) for {contact_email}, lead {opportunity.id if opportunity else 'N/A'}")
                
                return {
                    'status': 'success',
                    'message': f'Email sent to {contact_email}',
                    'email_id': mail.id
                }
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception(f"Error scheduling automated email: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def _send_whatsapp_message(self, contact_phone, message):
        """
        Send WhatsApp message using click-to-chat link or WhatsApp Business API.
        
        Note: Click-to-chat links only work if the phone number is registered on WhatsApp.
        For automated sending, integrate with WhatsApp Business API.
        """
        try:
            # Clean phone number (remove non-digits except +)
            # Also remove extension (ext, x, etc. and numbers after them)
            import re
            from urllib.parse import quote
            
            # Remove extension patterns (ext, x, etc. and following numbers/spaces)
            phone_without_ext = re.sub(r'\s*(ext|Ext|EXT|x|X|ext\.|Ext\.|EXT\.|x\.|X\.)\s*\d+.*$', '', contact_phone, flags=re.IGNORECASE)
            
            clean_phone = re.sub(r'[^\d+]', '', phone_without_ext)
            if not clean_phone.startswith('+'):
                # Assume it's a local number, add +1 for US (adjust as needed)
                clean_phone = '+1' + clean_phone
            
            # Remove + for WhatsApp URL
            phone_digits = clean_phone.replace('+', '')
            
            # Properly encode the message for URL
            encoded_message = quote(message)
            
            # Generate WhatsApp click-to-chat URL
            # WARNING: This only works if the phone number is registered on WhatsApp
            # If the number doesn't exist on WhatsApp, clicking the link will show an error
            whatsapp_url = f"https://wa.me/{phone_digits}?text={encoded_message}"
            
            # For now, we'll log the URL and return success
            # In production, integrate with WhatsApp Business API here for actual validation
            # Example with WhatsApp Business API:
            # import requests
            # api_url = "https://api.whatsapp.com/v1/messages"
            # headers = {"Authorization": f"Bearer {api_token}"}
            # payload = {"to": phone_digits, "text": message}
            # response = requests.post(api_url, json=payload, headers=headers)
            # The API will return an error if the number doesn't exist
            
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(f"WhatsApp message URL generated: {whatsapp_url}")
            _logger.warning("WhatsApp click-to-chat link may not work if phone number is not registered on WhatsApp")
            
            return {
                'status': 'success',
                'message': 'WhatsApp click-to-chat link generated (not automatically sent - requires Business API for automated sending)',
                'url': whatsapp_url,
                'warning': 'This is a click-to-chat link. It must be opened/clicked to send the message. Phone number must be registered on WhatsApp for this link to work. For automated sending, integrate with WhatsApp Business API.'
            }
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception(f"Error sending WhatsApp message: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def _send_viber_message(self, contact_phone, message):
        """
        Send Viber message using Viber click-to-chat link or Viber Business API.
        
        Note: Click-to-chat links only work if the phone number is registered on Viber.
        For automated sending, integrate with Viber Business API.
        """
        try:
            # Clean phone number (remove non-digits except +)
            # Also remove extension (ext, x, etc. and numbers after them)
            import re
            from urllib.parse import quote
            
            # Remove extension patterns (ext, x, etc. and following numbers/spaces)
            phone_without_ext = re.sub(r'\s*(ext|Ext|EXT|x|X|ext\.|Ext\.|EXT\.|x\.|X\.)\s*\d+.*$', '', contact_phone, flags=re.IGNORECASE)
            
            clean_phone = re.sub(r'[^\d+]', '', phone_without_ext)
            if not clean_phone.startswith('+'):
                # Assume it's a local number, add +1 for US (adjust as needed)
                clean_phone = '+1' + clean_phone
            
            # Remove + for Viber URL
            phone_digits = clean_phone.replace('+', '')
            
            # Properly encode the message for URL
            encoded_message = quote(message)
            
            # Generate Viber click-to-chat URL
            # WARNING: This only works if the phone number is registered on Viber
            # Format: viber://chat?number=PHONE&text=MESSAGE
            viber_url = f"viber://chat?number={phone_digits}&text={encoded_message}"
            
            # Alternative web-based URL (if available)
            # viber_url = f"https://chats.viber.com/{phone_digits}?text={encoded_message}"
            
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(f"Viber message URL generated: {viber_url}")
            _logger.warning("Viber click-to-chat link may not work if phone number is not registered on Viber")
            return {
                'status': 'success',
                'message': 'Viber click-to-chat link generated (not automatically sent - requires Business API for automated sending)',
                'url': viber_url,
                'warning': 'This is a click-to-chat link. It must be opened/clicked to send the message. Phone number must be registered on Viber for this link to work. For automated sending, integrate with Viber Business API.'
            }
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception(f"Error sending Viber message: {e}")
            return {'status': 'error', 'message': str(e)}
    
    def _send_telegram_message(self, contact_phone, message):
        """
        Send Telegram message using Telegram click-to-chat link.
        
        Note: Phone number-based links only work if the number is registered on Telegram.
        """
        try:
            from urllib.parse import quote
            
            # Telegram uses phone number for click-to-chat links
            if not contact_phone:
                return {'status': 'error', 'message': 'Phone number is required for Telegram'}
            
            # Remove any non-digit characters except +
            clean_phone = ''.join(c for c in contact_phone if c.isdigit() or c == '+')
            if not clean_phone.startswith('+'):
                clean_phone = '+' + clean_phone
            
            encoded_message = quote(message)
            # Telegram phone link format
            telegram_url = f"https://t.me/{clean_phone}?text={encoded_message}"
            
            import logging
            _logger = logging.getLogger(__name__)
            _logger.info(f"Telegram message URL generated: {telegram_url}")
            
            return {
                'status': 'success',
                'message': 'Telegram click-to-chat link generated (not automatically sent - requires Bot API for automated sending)',
                'url': telegram_url,
                'method': 'phone',
                'warning': 'This is a click-to-chat link. It must be opened/clicked to send the message. For automated sending, integrate with Telegram Bot API.'
            }
            
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.exception(f"Error sending Telegram message: {e}")
            return {'status': 'error', 'message': str(e)}

    @api.onchange('leadback_email_template_preset')
    def _onchange_email_template_preset(self):
        """Automatically populate email subject and template based on preset"""
        if self.leadback_email_template_preset == 'friendly':
            self.leadback_email_subject = "Great connecting with you"
            self.leadback_email_template = """<p>Hi {contact_name},</p>
<p>Thanks again for sharing your contact details. Just wanted to let you know I received your message.</p>
{if booking_url}<p>If you'd like to continue our conversation or set up some time, you can book a slot here:</p>
<p><a href='{booking_url}'>{booking_url}</a></p>{/if}
<p>Talk soon,<br/>{owner_name}</p>"""
        elif self.leadback_email_template_preset == 'professional':
            self.leadback_email_subject = "Good speaking with you"
            self.leadback_email_template = """<p>Hi {contact_name},</p>
<p>It was great connecting — I got your details.</p>
{if booking_url}<p>If you'd like to pick up the conversation, here's my booking link:</p>
<p><a href='{booking_url}'>{booking_url}</a></p>{/if}
<p>Best regards,<br/>{owner_name}{if owner_title}<br/>{owner_title}{/if}{if company_name}<br/>{company_name}{/if}</p>"""
        elif self.leadback_email_template_preset == 'event':
            self.leadback_email_subject = "Thanks for connecting"
            self.leadback_email_template = """<p>Hi {contact_name},</p>
<p>Thanks for sharing your details — I received your message.</p>
{if booking_url}<p>If you'd like to continue the conversation or set up a time, here's my booking link:</p>
<p><a href='{booking_url}'>{booking_url}</a></p>{/if}
<p>If you ever want to save my contact card again, here's the link:</p>
<p><a href='{vcard_url}'>{vcard_url}</a></p>
<p>Best,<br/>{owner_name}</p>"""
        elif self.leadback_email_template_preset == 'follow_up':
            self.leadback_email_subject = "Follow-up from earlier"
            self.leadback_email_template = """<p>Hi {contact_name},</p>
<p>Just following up — I received your contact information.</p>
{if booking_url}<p>If you'd like to book a call or ask anything, you can pick a time here:</p>
<p><a href='{booking_url}'>{booking_url}</a></p>{/if}
<p>Best,<br/>{owner_name}{if company_name}<br/>{company_name}{/if}</p>"""
        elif self.leadback_email_template_preset == 'appointment':
            self.leadback_email_subject = "Let's schedule a time to connect"
            self.leadback_email_template = """<p>Hi {contact_name},</p>
<p>Thanks for sharing your details — I got your message.</p>
{if booking_url}<p>I'd love to schedule some time to chat further. Please book a time that works for you:</p>
<p><a href='{booking_url}'>{booking_url}</a></p>{/if}
<p>Talk soon,<br/>{owner_name}</p>"""
        # For 'custom', leave the fields as they are so user can edit
    
    @api.onchange('leadback_message_template_preset')
    def _onchange_message_template_preset(self):
        """Automatically populate message template based on preset"""
        if self.leadback_message_template_preset == 'friendly':
            self.leadback_message_template = """Hi {contact_name}! Thanks for sharing your details — I got your message.

{if booking_url}If you'd like to continue the conversation or set up a time, here's my booking link:
{booking_url}{/if}"""
        elif self.leadback_message_template_preset == 'event':
            self.leadback_message_template = """Hi {contact_name}! Thanks for sharing your details — I got your message.

If you'd like to save my info again later, here's my card: {vcard_url}

{if booking_url}Booking link: {booking_url}{/if}"""
        elif self.leadback_message_template_preset == 'professional':
            self.leadback_message_template = """Hi {contact_name}! Just confirming I received your info.

{if booking_url}Here's my booking link if you want to chat:
{booking_url}{/if}"""
        elif self.leadback_message_template_preset == 'follow_up':
            self.leadback_message_template = """Hi {contact_name}, got your info — thank you!

{if booking_url}Book a time here: {booking_url}{/if}"""
        # For 'custom', leave the field as it is so user can edit
    
    @api.onchange('leadback_email_delay_preset')
    def _onchange_email_delay_preset(self):
        """Automatically set email delay amount and type based on preset"""
        if self.leadback_email_delay_preset == 'immediate':
            self.leadback_email_delay = 0
            self.leadback_email_delay_type = 'minutes'
        elif self.leadback_email_delay_preset == '1_min':
            self.leadback_email_delay = 1
            self.leadback_email_delay_type = 'minutes'
        elif self.leadback_email_delay_preset == '5_min':
            self.leadback_email_delay = 5
            self.leadback_email_delay_type = 'minutes'
        elif self.leadback_email_delay_preset == '15_min':
            self.leadback_email_delay = 15
            self.leadback_email_delay_type = 'minutes'
        elif self.leadback_email_delay_preset == '1_hour':
            self.leadback_email_delay = 1
            self.leadback_email_delay_type = 'hours'
        # For 'custom', leave the fields as they are so user can edit
    
    @api.onchange('leadback_message_delay_preset')
    def _onchange_message_delay_preset(self):
        """Automatically set message delay amount and type based on preset"""
        if self.leadback_message_delay_preset == 'immediate':
            self.leadback_message_delay = 0
            self.leadback_message_delay_type = 'minutes'
        elif self.leadback_message_delay_preset == '1_min':
            self.leadback_message_delay = 1
            self.leadback_message_delay_type = 'minutes'
        elif self.leadback_message_delay_preset == '5_min':
            self.leadback_message_delay = 5
            self.leadback_message_delay_type = 'minutes'
        elif self.leadback_message_delay_preset == '15_min':
            self.leadback_message_delay = 15
            self.leadback_message_delay_type = 'minutes'
        elif self.leadback_message_delay_preset == '1_hour':
            self.leadback_message_delay = 1
            self.leadback_message_delay_type = 'hours'
        # For 'custom', leave the fields as they are so user can edit
    
    @api.onchange('qr_pattern')
    def _onchange_qr_pattern(self):
        """Regenerate the QR code image when the pattern changes."""
        if self.qr_code_data:
            self._generate_qr_code_image()

    def _get_card_owner_user(self):
        """Resolve the Odoo user this card belongs to, keyed by the card email.

        res_users keeps partner email in sync with login, so a login/email
        match is reliable. We deliberately do NOT fall back to create_uid:
        for bulk-onboarded cards that is OdooBot, and applying a card's
        signature to the wrong person's user would ride their outgoing email.
        No email match => no owner, and the caller surfaces a clear error.
        """
        self.ensure_one()
        if not self.email:
            return self.env['res.users'].browse()
        User = self.env['res.users'].sudo()
        user = User.search([('login', '=ilike', self.email)], limit=1)
        if not user:
            user = User.search([('partner_id.email', '=ilike', self.email)], limit=1)
        return user

    def action_apply_email_signature(self, signature_html):
        """Set the generated Vinc signature as the owning user's Odoo email
        signature (res.users.signature) — the block appended when that user
        sends mail from Odoo.

        Authorization: the caller must have write access to THIS card (the
        standard record rules already gate who can open its form). Given that,
        we set the owner's signature with elevated rights so a manager can do
        this for a rep they onboard. The Html field sanitizes on write.
        """
        self.ensure_one()
        if not signature_html or not signature_html.strip():
            raise UserError("Generate a signature preview before applying it.")
        # Gate on write access to this card.
        self.check_access_rights('write')
        self.check_access_rule('write')
        user = self._get_card_owner_user()
        if not user:
            raise UserError(
                "Couldn't find an Odoo user for this card. Its email must match "
                "a user's login or email to set that user's signature."
            )
        user.sudo().write({'signature': signature_html})
        return {'user_id': user.id, 'user_name': user.name, 'login': user.login}

    @api.constrains('qr_logo')
    def _check_qr_logo_is_raster(self):
        """Reject QR logos PIL can't rasterize (e.g. SVG) at upload time.

        Company logos are frequently stored as SVG. The image widget renders
        SVG fine in the browser, so the upload *looks* successful — but PIL
        can't open it, so the logo silently never appears on the generated QR.
        Fail fast with an actionable message instead.
        """
        for record in self:
            if not record.qr_logo:
                continue
            try:
                Image.open(io.BytesIO(base64.b64decode(record.qr_logo))).verify()
            except Exception:
                raise ValidationError(
                    "That QR logo couldn't be read as an image. Please upload a "
                    "PNG or JPG (vector formats like SVG aren't supported for the "
                    "QR logo)."
                )

    def _generate_qr_code_data(self):
        """Generate and store QR code data based on the partner's information."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        redirect_url = f"{base_url}/qr/{self.id}"
        self.qr_code_data = redirect_url
    
    def action_regenerate_qr_code(self):
        """Regenerate QR code using the same logic as signup."""
        self.ensure_one()
        # Regenerate QR code data (ensures URL is correct)
        self._generate_qr_code_data()
        # Regenerate QR code image with current pattern and logo
        self._generate_qr_code_image()
        # Reload the form to show the updated QR code image
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'partner.vcard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
            'context': {'form_view_initial_mode': 'edit'},
        }
    
    def _generate_qr_code_image(self):
        """Generate QR code image based on stored data and current pattern."""
        if not self.qr_code_data:
            return
    
        # Generate QR code image using stored data
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(self.qr_code_data)
        qr.make(fit=True)
    
        # Select the appropriate pattern for the QR code
        module_drawer = {
            'dots': CircleModuleDrawer(),
            'rounded': RoundedModuleDrawer(),
            'classy-rounded': GappedSquareModuleDrawer(),
            'classy': GappedSquareModuleDrawer(),
            'square': SquareModuleDrawer()
        }.get(self.qr_pattern, SquareModuleDrawer())
    
        # Generate the QR code with the selected pattern
        img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=module_drawer,
            fill_color='black',
            back_color='white',
        )
    
        # Overlay the logo: per-user upload wins, otherwise fall back to the
        # globally configured brand icon (if one is set in Settings → Vinc).
        logo_bytes = None
        if self.qr_logo:
            logo_bytes = base64.b64decode(self.qr_logo)
        else:
            logo_bytes = self.env['qr_code_odoo.brand'].sudo().get_brand_icon_binary()
        if logo_bytes:
            img = self._add_logo_to_qr_code(img, logo_bytes)
    
        # Save QR code image
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        image_data = base64.b64encode(buffer.getvalue())
        self.qr_code = image_data

    def _add_logo_to_qr_code(self, img, logo_bytes=None):
        """Overlay the provided logo on the QR code.

        The logo is drawn on a white rounded backing plate for two reasons:
        (1) a light/transparent logo (very common — brand marks are often
        white-on-transparent) is otherwise invisible against the white QR
        background, which reads to the user as "my logo didn't show up";
        (2) the plate carves a clean quiet-zone around the logo so the QR
        stays scannable. The logo is capped at ~22% of the QR width so the
        ERROR_CORRECT_H redundancy (tolerates ~30% obscuration) can still
        recover the code.

        Note: PIL cannot open vector formats (SVG). If an SVG is passed here
        it raises UnidentifiedImageError, which we log clearly and skip. The
        `_check_qr_logo_is_raster` constraint rejects such uploads up front so
        the user gets an actionable error instead of a silently logo-less QR.
        """
        import logging
        _logger = logging.getLogger(__name__)
        try:
            if logo_bytes is None:
                logo_bytes = base64.b64decode(self.qr_logo)
            logo = Image.open(io.BytesIO(logo_bytes))

            # Convert logo to RGBA if it's not already
            if logo.mode != 'RGBA':
                logo = logo.convert('RGBA')

            qr_width, qr_height = img.size

            # Cap the logo at ~22% of the QR (keeps it scannable under H-level
            # error correction), preserving the logo's aspect ratio.
            logo_box = int(min(qr_width, qr_height) * 0.22)
            # Image.LANCZOS, not Image.Resampling.LANCZOS: the Resampling enum
            # only exists on Pillow >= 9.1, and on older Pillow the AttributeError
            # got swallowed below — silently dropping the logo for every upload
            # regardless of file type. The legacy alias works on all versions.
            logo.thumbnail((logo_box, logo_box), Image.LANCZOS)
            logo_width, logo_height = logo.size

            # White rounded backing plate a touch larger than the logo.
            pad = max(6, int(logo_box * 0.14))
            plate_w, plate_h = logo_width + 2 * pad, logo_height + 2 * pad
            plate = Image.new('RGBA', (plate_w, plate_h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(plate)
            radius = max(4, int(min(plate_w, plate_h) * 0.18))
            try:
                draw.rounded_rectangle(
                    [(0, 0), (plate_w - 1, plate_h - 1)],
                    radius=radius, fill=(255, 255, 255, 255),
                )
            except AttributeError:
                # Older Pillow without rounded_rectangle: square plate.
                draw.rectangle([(0, 0), (plate_w - 1, plate_h - 1)],
                               fill=(255, 255, 255, 255))

            # Compose logo onto the plate, then plate onto the QR (centered).
            plate.paste(logo, (pad, pad), logo)
            plate_position = (
                (qr_width - plate_w) // 2,
                (qr_height - plate_h) // 2,
            )
            img.paste(plate, plate_position, plate)
            return img
        except Exception as e:
            # Keep QR generation resilient: a bad logo must never block the
            # whole QR. Log loudly so this doesn't disappear silently again.
            _logger.warning(
                "QR logo overlay failed for vCard %s (%s): %s — QR generated "
                "without a logo. If the logo is an SVG, re-upload it as PNG/JPG.",
                self.id, type(e).__name__, e,
            )
            return img


    def _get_lead_tag_ids_str(self):
        """Get comma-separated string of lead tag IDs for use in templates"""
        if not self.lead_tag_ids:
            return ''
        return ','.join(str(tag_id) for tag_id in self.lead_tag_ids.ids)

    def _stamp_event_on_lead(self, lead_vals, contact_name, email, phone):
        """If this card has an active_event_id, attribute the captured lead to
        that event by setting event_id on the lead vals.

        We deliberately do NOT create an event.registration here: that would
        fire Odoo's standard "thanks for registering" email plus any scheduled
        event reminders to the prospect, which is wrong for a lead-capture
        scan. The event_id on the lead is enough for "leads from this show"
        reporting; an admin can manually add the prospect to the attendee
        list later if they want.
        """
        self.ensure_one()
        if self.active_event_id:
            lead_vals['event_id'] = self.active_event_id.id
    
    def _get_google_maps_url(self):
        """Build Google Maps URL for the address"""
        if not any([self.street, self.city, self.state_id, self.country_id]):
            return None
        
        # Build address string
        address_parts = []
        if self.street:
            address_parts.append(self.street)
        if self.street2:
            address_parts.append(self.street2)
        if self.city:
            address_parts.append(self.city)
        if self.state_id and self.state_id.name:
            address_parts.append(self.state_id.name)
        if self.zip:
            address_parts.append(self.zip)
        if self.country_id and self.country_id.name:
            address_parts.append(self.country_id.name)
        
        if not address_parts:
            return None
        
        # Join address parts and URL encode
        import urllib.parse
        address = ', '.join(address_parts)
        encoded_address = urllib.parse.quote_plus(address)
        return f"https://www.google.com/maps/search/?api=1&query={encoded_address}"
    
    def _get_page_view_tracking_script(self):
        """Get JavaScript code to track page views"""
        if not self.website_slug:
            return ""
        slug_escaped = self.website_slug.replace("'", "\\'")
        return f"""
        <script>
        (function() {{
            // Track page view when page loads
            function trackPageView() {{
                // Only track once per page load
                var storageKey = 'vcard_view_tracked_{slug_escaped}';
                if (sessionStorage.getItem(storageKey)) {{
                    return;
                }}
                
                // Track the view
                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/track_page_view/{slug_escaped}', true);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.onreadystatechange = function() {{
                    if (xhr.readyState === 4) {{
                        if (xhr.status === 200) {{
                            try {{
                                var response = JSON.parse(xhr.responseText);
                                if (response.success) {{
                                    console.log('Page view tracked successfully. Total views:', response.views);
                                }}
                            }} catch(e) {{
                                console.log('Page view tracking response parse error:', e);
                            }}
                        }} else {{
                            console.log('Page view tracking failed with status:', xhr.status);
                        }}
                        // Mark as tracked for this session regardless of success
                        sessionStorage.setItem(storageKey, 'true');
                    }}
                }};
                xhr.send(JSON.stringify({{}}));
            }}
            
            // Track when page is ready
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', trackPageView);
            }} else {{
                trackPageView();
            }}
        }})();
        </script>
        """
    
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        for partner in partners:
            # Generate QR code data + initial image for every new vCard.
            partner._generate_qr_code_data()
            partner._generate_qr_code_image()
            partner._compute_referral_signup_url()
        return partners

    # Field set whose changes should auto-regenerate the published website page.
    # Mirrors the inputs read by _build_dynamic_template plus the image/banner
    # attachments and the website_template selector. Adding a new template-input
    # field elsewhere REQUIRES adding it here, or backend edits won't reflect on
    # the published site without a manual "Generate" click.
    _TEMPLATE_AFFECTING_FIELDS = frozenset({
        'name', 'company_name', 'function', 'about',
        'street', 'street2', 'city', 'zip', 'state_id', 'country_id',
        'phone', 'mobile', 'email', 'website', 'calendly_url',
        'primary_color', 'secondary_color', 'website_template',
        'image_url', 'banner_image',
        'whatsapp_url', 'linkedin_url', 'linkedin_url_company',
        'youtube_url', 'facebook_url', 'facebook_url_company',
        'twitter_url', 'instagram_url', 'tiktok_url', 'pinterest_url',
        'github_url', 'snapchat_url',
        'lead_button_label', 'form_thank_you_message', 'show_form',
        'show_reviews', 'mailing_list_id',
        'enable_instant_leadback', 'leadback_send_email',
        'leadback_enable_messaging', 'leadback_channels',
        'qr_pattern', 'qr_logo',
    })

    def write(self, vals):
        res = super(PartnerVCard, self).write(vals)
        # If the pattern or logo changes, regenerate the QR code image
        if 'qr_pattern' in vals or 'qr_logo' in vals:
            self._generate_qr_code_image()
        # Auto-regenerate the published website page when any template-affecting
        # field changes. Skip for preview vCards (the /vcard/preview controller
        # handles those explicitly) and for records without a published page yet
        # (creation flow generates them on first publish). The arch_db-skip guard
        # in action_generate_website_page makes this idempotent when the rendered
        # template happens to be unchanged.
        if not self.env.context.get('skip_auto_regen') and (vals.keys() & self._TEMPLATE_AFFECTING_FIELDS):
            for record in self:
                if record.website_page_id and not (record.website_slug or '').startswith('preview-'):
                    try:
                        record.with_context(skip_auto_regen=True).action_generate_website_page()
                    except Exception as e:
                        _logger.warning(f"Auto-regen skipped for vCard {record.id} ({record.name}): {e}")
        return res
    
    # Imperative normaliser invoked from the @api.onchange methods on each
    # social-URL field. It mutates `self` via setattr(...) to prepend the
    # correct prefix when the user types a slug — which is NOT a compute's
    # job and would recurse if the @api.depends actually triggered. Kept here
    # as a regular method; decorator removed.
    def _compute_social_media_urls(self):
        """Automatically format the social media URLs if the user enters a slug (or correct the format)."""
        url_patterns = {
            'whatsapp_url': ('https://wa.me/', r'^\d+$'),
            'linkedin_url': ('https://www.linkedin.com/in/', r'^[a-zA-Z0-9_-]+$'),
            'linkedin_url_company': ('https://www.linkedin.com/company/', r'^[a-zA-Z0-9_-]+$'),
            'youtube_url': ('https://www.youtube.com/channel/', r'^[a-zA-Z0-9_-]+$'),
            'facebook_url': ('https://www.facebook.com/', r'^[a-zA-Z0-9._-]+$'),
            'facebook_url_company': ('https://www.facebook.com/', r'^[a-zA-Z0-9._-]+$'),
            'telegram_url': ('https://t.me/', r'^[a-zA-Z0-9_-]+$'),
            'instagram_url': ('https://www.instagram.com/', r'^[a-zA-Z0-9._-]+$'),
            'instagram_url_company': ('https://www.instagram.com/', r'^[a-zA-Z0-9._-]+$'),
            'tumblr_url': ('https://', r'^[a-zA-Z0-9_-]+\.tumblr\.com$'),
            'xing_url': ('https://www.xing.com/profile/', r'^[a-zA-Z0-9_-]+$'),
            'github_url': ('https://github.com/', r'^[a-zA-Z0-9_-]+$'),
            'vimeo_url': ('https://vimeo.com/', r'^[a-zA-Z0-9_-]+$'),
            'messenger_url': ('https://m.me/', r'^[a-zA-Z0-9._-]+$'),
            'dribbble_url': ('https://dribbble.com/', r'^[a-zA-Z0-9_-]+$'),
            'skype_url': ('skype:', r'^[a-zA-Z0-9._-]+$'),
            'doordash_url': ('https://www.doordash.com/store/', r'^[a-zA-Z0-9._-]+$'),
            'tripadvisor_url': ('https://www.tripadvisor.com/Profile/', r'^[a-zA-Z0-9._-]+$'),
            'yelp_url': ('https://www.yelp.com/biz/', r'^[a-zA-Z0-9._-]+$'),
            'twitter_url': ('https://www.twitter.com/', r'^[a-zA-Z0-9._-]+$'),
            'twitter_url_company': ('https://www.twitter.com/', r'^[a-zA-Z0-9._-]+$'),
            'google_reviews_url': ('https://g.page/', r'^[a-zA-Z0-9._-]+$'),
            'ubereats_url': ('https://www.ubereats.com/store/', r'^[a-zA-Z0-9._-]+$'),
            'line_url': ('https://line.me/R/ti/p/', r'^[a-zA-Z0-9._-]+$'),
            'vkontakte_url': ('https://vk.com/', r'^[a-zA-Z0-9._-]+$'),
            'reddit_url': ('https://www.reddit.com/user/', r'^[a-zA-Z0-9._-]+$'),
            'viber_url': ('viber://chat?number=', r'^[0-9]+$'),
            'pinterest_url': ('https://www.pinterest.com/', r'^[a-zA-Z0-9._-]+$'),
            'tiktok_url': ('https://www.tiktok.com/@', r'^[a-zA-Z0-9._-]+$'),
            'snapchat_url': ('https://www.snapchat.com/add/', r'^[a-zA-Z0-9._-]+$'),
            'signal_url': ('https://signal.me/#p/', r'^[0-9]+$')
        }

        for field_name, (prefix, slug_pattern) in url_patterns.items():
            field_value = getattr(self, field_name)
            if field_value:
                # Check if the user entered a full URL
                if field_value.startswith('http') or field_value.startswith('https'):
                    # If it's a full URL, do nothing
                    continue
                elif re.match(slug_pattern, field_value):
                    # If it's a valid slug, append the correct prefix
                    setattr(self, field_name, prefix + field_value)


    
    @api.depends('website_slug')
    def _compute_website_full_url(self):
        # Try to get base URL, but handle transaction errors gracefully
        # When web.base.url can't be read (aborted txn, config missing), fall
        # back to the current request URL if one exists, else leave base_url
        # empty so downstream URLs stay relative (or the compute returns ''
        # and the caller decides). Never emit hardcoded localhost:8069 — that
        # shows up in customer emails with broken links.
        import psycopg2
        base_url = ''
        try:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
        except psycopg2.errors.InFailedSqlTransaction:
            _logger.warning("Transaction aborted; falling back to request URL for web.base.url")
        except Exception as e:
            _logger.error("Error getting base_url in _compute_website_full_url: %s", e)
        if not base_url:
            try:
                from odoo.http import request as _req
                if hasattr(_req, 'httprequest') and _req.httprequest:
                    base_url = _req.httprequest.host_url.rstrip('/')
            except Exception:
                pass
        
        for record in self:
            if record.website_slug:
                record.website_full_url = base_url + "/" + record.website_slug
            else:
                record.website_full_url = base_url
                
   
        
    def _generate_vcf(self):
        """Generate vCard (.vcf) file for the partner."""
        vcard = (
            f"BEGIN:VCARD\n"
            f"VERSION:3.0\n"
            f"FN:{self.name}\n"
            f"ORG:{self.company_name or ''}\n"
            f"TITLE:{self.function or ''}\n"
            f"TEL;TYPE=CELL:{self.phone or ''}\n"
            f"TEL;TYPE=WORK,VOICE:{self.mobile or ''}\n"
            f"EMAIL:{self.email or ''}\n"
            f"ADR;TYPE=WORK,PREF:;;{self.street or ''};{self.city or ''};{self.state_id.name or ''};{self.zip or ''};{self.country_id.name or ''}\n"
            f"END:VCARD"
        )
        return vcard
