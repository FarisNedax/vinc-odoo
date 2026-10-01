from odoo import http
from odoo.http import request
import json
import logging
import base64
import csv
import io
import threading
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class BulkOnboardingController(http.Controller):

    def _check_admin_access(self):
        """Check if user has admin/manager access"""
        user = request.env.user
        # Check if user is admin or has ERP manager group
        if user.id == 1:  # Superuser
            return True
        if user.has_group('qr_code_odoo.group_vinc_manager') or user.has_group('base.group_erp_manager'):
            return True
        return False

    @http.route('/bulk-onboard', type='http', auth='user', website=True, csrf=False)
    def bulk_onboard_index(self, **kwargs):
        """Main bulk onboarding page - shows list of batches or redirects to form"""
        if not self._check_admin_access():
            return request.redirect('/web/login')
        
        # Get all batches
        batches = request.env['bulk.onboarding.batch'].sudo().search([
        ], order='create_date desc', limit=50)
        
        return request.render('qr_code_odoo.bulk_onboarding_index', {
            'batches': batches,
        })
    
    @http.route('/bulk-onboard/new', type='http', auth='user', website=True, csrf=False)
    def bulk_onboard_page(self, **kwargs):
        """Display bulk onboarding form"""
        if not self._check_admin_access():
            return request.redirect('/web/login?redirect=/bulk-onboard')
        
        # Get countries and states for forms
        countries = request.env['res.country'].sudo().search([], order='name')
        states = request.env['res.country.state'].sudo().search([], order='name')
        
        return request.render('qr_code_odoo.bulk_onboarding_wizard', {
            'countries': countries,
            'states': states,
        })

    @http.route('/bulk-onboard/template', type='http', auth='user', website=True, csrf=False)
    def download_template(self, **kwargs):
        """Download CSV template for bulk onboarding"""
        if not self._check_admin_access():
            return request.render('qr_code_odoo.error_page', {'error': 'Access denied'})
        
        # Create CSV template content with expanded fields
        # Row 1: Explanations, Row 2: Headers, Rows 3-7: Examples
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Row 1: Explanations for all available fields
        writer.writerow([
            'Full name of the user (required)',
            'Email address (required)',
            'Phone number (optional)',
            'Mobile number (optional)',
            'Job title or function (optional)',
            'About text (optional, overrides default)',
            'Street address (optional)',
            'Address line 2 (optional)',
            'City (optional)',
            'ZIP/Postal code (optional)',
            'Country name (optional, e.g., United States)',
            'State/Province name (optional, e.g., California)',
            'LinkedIn URL (optional)',
            'Facebook URL (optional)',
            'Twitter/X URL (optional)',
            'Instagram URL (optional)',
            'WhatsApp URL (optional)',
            'YouTube URL (optional)',
            'Calendly URL (optional)',
            'Website slug (optional, custom URL)'
        ])
        # Row 2: Headers
        writer.writerow([
            'name',
            'email',
            'phone',
            'mobile',
            'function',
            'about',
            'street',
            'street2',
            'city',
            'zip',
            'country',
            'state',
            'linkedin_url',
            'facebook_url',
            'twitter_url',
            'instagram_url',
            'whatsapp_url',
            'youtube_url',
            'calendly_url',
            'website_slug'
        ])
        # Rows 3-7: Examples
        # Note: Prefix phone numbers with ' to force Excel to treat as text and preserve + sign
        writer.writerow([
            'John Doe',
            'john.doe@example.com',
            "'+15551234567",
            "'+15551234568",
            'Sales Manager',
            'Experienced sales professional with 10+ years in the industry',
            '123 Main Street',
            'Suite 100',
            'Los Angeles',
            '90210',
            'United States',
            'California',
            'https://www.linkedin.com/in/johndoe',
            'https://www.facebook.com/johndoe',
            'https://x.com/johndoe',
            'https://www.instagram.com/johndoe',
            '',
            '',
            'https://calendly.com/johndoe',
            'john-doe'
        ])
        writer.writerow([
            'Jane Smith',
            'jane.smith@example.com',
            "'+15559876543",
            '',
            'Account Executive',
            '',
            '456 Oak Avenue',
            '',
            'New York',
            '10001',
            'United States',
            'New York',
            'https://www.linkedin.com/in/janesmith',
            '',
            '',
            '',
            '',
            '',
            'jane-smith'
        ])
        writer.writerow([
            'Bob Johnson',
            'bob.johnson@example.com',
            '',
            '',
            'Regional Director',
            'Leading regional sales team',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            ''
        ])
        writer.writerow([
            'Alice Williams',
            'alice.williams@example.com',
            "'+15555555555",
            '',
            'VP of Sales',
            '',
            '789 Pine Road',
            'Floor 5',
            'Chicago',
            '60601',
            'United States',
            'Illinois',
            'https://www.linkedin.com/in/alicewilliams',
            '',
            '',
            '',
            '',
            '',
            'alice-williams'
        ])
        writer.writerow([
            'Charlie Brown',
            'charlie.brown@example.com',
            "'+15551111111",
            '',
            'Senior Account Manager',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            '',
            ''
        ])
        
        csv_content = output.getvalue()
        
        # Return CSV file
        response = request.make_response(
            csv_content.encode('utf-8-sig'),  # Use utf-8-sig to include BOM for Excel compatibility
            headers=[
                ('Content-Type', 'text/csv; charset=utf-8'),
                ('Content-Disposition', 'attachment; filename="bulk_onboarding_template.csv"'),
            ]
        )
        return response

    # Hard caps for bulk onboarding uploads. These limit both accidental misuse
    # and compromised-admin scenarios (a single run can spawn thousands of
    # res.users + attachments, which is expensive for licensed Odoo deployments).
    _BULK_UPLOAD_MAX_BYTES = 2 * 1024 * 1024  # 2 MB raw file
    _BULK_UPLOAD_MAX_ROWS = 500               # rows per batch

    @http.route('/bulk-onboard/upload', type='http', auth='user', website=True, csrf=False, methods=['POST'])
    def upload_file(self, **kwargs):
        """Handle file upload (CSV/Excel)"""
        if not self._check_admin_access():
            return json.dumps({'error': 'Access denied'})

        try:
            uploaded_file = request.httprequest.files.get('file')
            if not uploaded_file:
                return json.dumps({'error': 'No file uploaded'})

            # Enforce file-size cap before reading the whole thing into RAM.
            uploaded_file.seek(0, 2)
            file_size = uploaded_file.tell()
            uploaded_file.seek(0)
            if file_size > self._BULK_UPLOAD_MAX_BYTES:
                return json.dumps({
                    'error': f'File is too large. Maximum size is {self._BULK_UPLOAD_MAX_BYTES // (1024 * 1024)} MB.',
                })

            file_content = uploaded_file.read()
            file_name = uploaded_file.filename.lower()

            # Parse file based on extension
            if file_name.endswith('.csv'):
                rows = request.env['bulk.onboarding.batch'].parse_csv_file(file_content)
            elif file_name.endswith(('.xlsx', '.xls')):
                rows = request.env['bulk.onboarding.batch'].parse_excel_file(file_content)
            else:
                return json.dumps({'error': 'Unsupported file format. Please use CSV or Excel (.xlsx, .xls)'})

            # Cap the number of rows to prevent runaway user-creation.
            if len(rows) > self._BULK_UPLOAD_MAX_ROWS:
                return json.dumps({
                    'error': f'Too many rows ({len(rows)}). Maximum is {self._BULK_UPLOAD_MAX_ROWS} per batch; split the file and re-upload.',
                })

            # Validate required columns
            required_columns = ['name', 'email']
            if rows:
                first_row = rows[0]
                missing_columns = [col for col in required_columns if col not in first_row]
                if missing_columns:
                    return json.dumps({'error': f'Missing required columns: {", ".join(missing_columns)}'})

            # Per-row check: which emails belong to existing Odoo users?
            # Bulk onboarding now requires the rep to already be a user, so
            # admins need to see this BEFORE submit, not in the error log.
            row_emails = [
                str(r.get('email', '')).strip().lower()
                for r in rows
                if r.get('email')
            ]
            matched_logins = set()
            if row_emails:
                Users = request.env['res.users'].sudo()
                matched = Users.search([('login', 'in', row_emails)])
                matched_logins = {u.login.lower() for u in matched}
            unmatched = sorted({e for e in row_emails if e and e not in matched_logins})

            return json.dumps({
                'success': True,
                'rows': rows[:10],  # Return first 10 rows for preview
                'total_rows': len(rows),
                'matched_count': len(row_emails) - len(unmatched),
                'unmatched_count': len(unmatched),
                'unmatched_emails': unmatched[:20],  # cap to avoid bloating response
            })
            
        except Exception as e:
            _logger.error(f"Error uploading file: {str(e)}", exc_info=True)
            return json.dumps({'error': str(e)})

    @http.route('/bulk-onboard/submit', type='http', auth='user', website=True, csrf=True, methods=['POST'])
    def submit_bulk_onboard(self, **post):
        """Submit bulk onboarding form"""
        if not self._check_admin_access():
            return request.render('qr_code_odoo.error_page', {'error': 'Access denied'})
        
        try:
            # Parse common data
            common_data = {
                'company_name': post.get('company_name', ''),
                'brand_color': post.get('brand_color', '#4C75A3'),
                'website_template': post.get('website_template') or post.get('selected_template', 'modern'),
                'qr_pattern': 'square',  # Default pattern, no UI selection
                'default_about': post.get('default_about', ''),
                # Address defaults
                'default_street': post.get('default_street', ''),
                'default_street2': post.get('default_street2', ''),
                'default_city': post.get('default_city', ''),
                'default_zip': post.get('default_zip', ''),
                'country_id': post.get('country_id') or False,
                'state_id': post.get('state_id') or False,
                # Feature toggles from form (will be applied to all Cards)
                'show_reviews': post.get('show_reviews') == 'yes',
                'linkedin_url_company': post.get('linkedin_url_company', ''),
                'facebook_url_company': post.get('facebook_url_company', ''),
                'twitter_url_company': post.get('twitter_url_company', ''),
                'instagram_url_company': post.get('instagram_url_company', ''),
                'show_form': post.get('show_form') == 'yes' or post.get('show_form_yes') == 'yes',
                'mailing_list_name': post.get('mailing_list_name', 'Leads'),
                'lead_button_label': post.get('lead_button_label', 'Get In Touch'),
                'form_thank_you_message': post.get('form_thank_you_message', ''),
                'notify_on_new_lead': post.get('notify_on_new_lead') == 'yes' or post.get('notify_on_new_lead_yes') == 'yes',
                'intro_email_enabled': post.get('intro_email_enabled') == 'yes' or post.get('intro_email_enabled_yes') == 'yes',
                'enable_instant_leadback': post.get('enable_instant_leadback') == 'yes' or post.get('enable_instant_leadback_yes') == 'yes',
                'leadback_send_email': post.get('leadback_send_email') == 'yes' or post.get('leadback_send_email_yes') == 'yes',
                'leadback_enable_messaging': post.get('leadback_enable_messaging') == 'yes' or post.get('leadback_enable_messaging_yes') == 'yes',
                'leadback_channels': request.httprequest.form.getlist('leadback_channels[]') if hasattr(request.httprequest.form, 'getlist') else ([post.get('leadback_channels[]')] if post.get('leadback_channels[]') else []),
            }
            
            # Handle logo upload (store as base64)
            logo_file = request.httprequest.files.get('default_logo')
            if logo_file:
                common_data['default_logo'] = base64.b64encode(logo_file.read()).decode('utf-8')
            
            # Handle banner image (store as base64)
            banner_file = request.httprequest.files.get('banner_image')
            if banner_file:
                common_data['banner_image'] = base64.b64encode(banner_file.read()).decode('utf-8')
            
            # Handle QR logo (store as base64)
            qr_logo_file = request.httprequest.files.get('qr_logo')
            if qr_logo_file:
                common_data['qr_logo'] = base64.b64encode(qr_logo_file.read()).decode('utf-8')
            
            # Parse rep data
            rep_data_list = []
            
            # Check if data came from file upload or manual entry
            if post.get('rep_data_json'):
                # Data from file upload
                rep_data_list = json.loads(post.get('rep_data_json'))
            else:
                # Manual entry - parse form fields
                rep_names = request.httprequest.form.getlist('rep_name[]')
                rep_emails = request.httprequest.form.getlist('rep_email[]')
                rep_phones = request.httprequest.form.getlist('rep_phone[]')
                rep_functions = request.httprequest.form.getlist('rep_function[]')
                
                for i, email in enumerate(rep_emails):
                    if email.strip():
                        rep_data_list.append({
                            'name': rep_names[i] if i < len(rep_names) else '',
                            'email': email.strip(),
                            'phone': rep_phones[i] if i < len(rep_phones) else '',
                            'function': rep_functions[i] if i < len(rep_functions) else '',
                        })
            
            # Enforce the same row cap as /bulk-onboard/upload so a hostile
            # admin can't bypass via direct POST of rep_data_json.
            if len(rep_data_list) > self._BULK_UPLOAD_MAX_ROWS:
                countries = request.env['res.country'].sudo().search([], order='name')
                return request.render('qr_code_odoo.bulk_onboard_form', {
                    'countries': countries,
                    'error': f'Too many reps ({len(rep_data_list)}). Maximum is {self._BULK_UPLOAD_MAX_ROWS} per batch.',
                })

            # Validate that we have rep data
            if not rep_data_list:
                countries = request.env['res.country'].sudo().search([], order='name')
                states = request.env['res.country.state'].sudo().search([], order='name')
                return request.render('qr_code_odoo.bulk_onboarding_wizard', {
                    'error': 'No rep data provided. Please add at least one rep using file upload or manual entry.',
                    'countries': countries,
                    'states': states,
                })
            
            # Create batch
            batch = request.env['bulk.onboarding.batch'].sudo().create({
                'name': post.get('batch_name', f"Batch {datetime.now().strftime('%Y-%m-%d %H:%M')}"),
                'created_by': request.env.user.id,
                'status': 'draft',
            })
            
            batch.set_common_data(common_data)
            
            # Before creating rep records, clean emails, check for duplicates, and check existing users
            import re
            seen_emails = set()
            duplicate_emails = []
            missing_user_emails = []
            
            Batch = request.env['bulk.onboarding.batch']
            # First pass: clean emails and find duplicates within batch
            for rep_data in rep_data_list:
                email = rep_data.get('email', '').strip().lower()
                if not email:
                    continue

                # Clean email via the shared helper (strips stray spaces, e.g.
                # "robert@ noeticerp.com", and trailing Excel digits).
                cleaned_email = Batch._clean_email(email)
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', cleaned_email):
                    continue  # Skip invalid emails
                
                # Check for duplicates in this batch
                if cleaned_email in seen_emails:
                    duplicate_emails.append(cleaned_email)
                else:
                    seen_emails.add(cleaned_email)
                    rep_data['email'] = cleaned_email  # Update with cleaned email
            
            # Bulk onboarding attaches cards to Odoo users that ALREADY exist —
            # it does not create logins (see _create_rep_account). So the check
            # is the inverse: flag rows whose email has no user yet. Rejecting
            # emails *because* they exist made every upload impossible.
            if seen_emails:
                found_logins = {
                    u.login.lower()
                    for u in request.env['res.users'].sudo().search([
                        ('login', 'in', list(seen_emails))
                    ])
                }
                missing_user_emails = sorted(seen_emails - found_logins)

            # Report all errors at once
            errors = []
            if duplicate_emails:
                errors.append(f"Duplicate emails found in upload: {', '.join(set(duplicate_emails))}")
            if missing_user_emails:
                errors.append(
                    f"No Odoo user found for: {', '.join(missing_user_emails)}. "
                    f"Add them under Settings → Users & Companies → Users first"
                )
            
            if errors:
                countries = request.env['res.country'].sudo().search([], order='name')
                states = request.env['res.country.state'].sudo().search([], order='name')
                return request.render('qr_code_odoo.bulk_onboarding_wizard', {
                    'error': ' '.join(errors) + '. Please fix these issues and try again.',
                    'countries': countries,
                    'states': states,
                })
            
            # Create rep records (emails are now cleaned and validated)
            created_reps = 0
            for rep_data in rep_data_list:
                email = Batch._clean_email(rep_data.get('email', ''))
                if not email:  # Skip rows without valid emails
                    continue

                rep_record = request.env['bulk.onboarding.rep'].sudo().create({
                    'batch_id': batch.id,
                    'name': rep_data.get('name', '').strip(),
                    'email': email,
                    'phone': rep_data.get('phone', '').strip(),
                    'status': 'pending',
                })
                rep_record.set_rep_data(rep_data)
                created_reps += 1

            # Guard against the empty-draft zombie (the "RJ2" case): if nothing
            # survived cleaning, delete the just-created batch instead of
            # leaving a draft with zero reps and no available actions.
            if not created_reps:
                batch.sudo().unlink()
                countries = request.env['res.country'].sudo().search([], order='name')
                states = request.env['res.country.state'].sudo().search([], order='name')
                return request.render('qr_code_odoo.bulk_onboarding_wizard', {
                    'error': 'None of the rows had a usable email address, so no batch was created. Check the email column and try again.',
                    'countries': countries,
                    'states': states,
                })

            # Start processing (returns immediately, cron will process in background)
            batch.action_start_processing()
            
            # Process immediately in background thread (don't wait for cron)
            # This ensures processing starts right away without blocking the HTTP response
            def process_batch_async():
                try:
                    # Create a new environment for the background thread
                    with batch.env.registry.cursor() as cr:
                        env = batch.env(cr=cr)
                        batch_record = env['bulk.onboarding.batch'].browse(batch.id)
                        if batch_record.exists() and batch_record.status == 'processing':
                            _logger.info(f"Processing batch {batch.id} in background thread")
                            batch_record.with_user(batch_record.created_by)._process_batch()
                            cr.commit()
                            _logger.info(f"Completed processing batch {batch.id} in background thread")
                except Exception as e:
                    _logger.error(f"Error processing batch {batch.id} in background thread: {str(e)}", exc_info=True)
            
            # Start processing in background thread
            thread = threading.Thread(target=process_batch_async, daemon=True)
            thread.start()
            
            # Redirect to website UI batch view with success message
            return request.redirect(f'/bulk-onboard/batch/{batch.id}?started=1')
            
        except Exception as e:
            _logger.error(f"Error submitting bulk onboard: {str(e)}", exc_info=True)
            import traceback
            error_trace = traceback.format_exc()
            _logger.error(f"Full traceback: {error_trace}")
            
            # Get countries and states for re-rendering
            countries = request.env['res.country'].sudo().search([], order='name')
            states = request.env['res.country.state'].sudo().search([], order='name')
            
            return request.render('qr_code_odoo.bulk_onboarding_wizard', {
                'error': f'Error: {str(e)}',
                'countries': countries,
                'states': states,
            })
    
    @http.route('/bulk-onboard/batch/<int:batch_id>', type='http', auth='user', website=True)
    def view_batch(self, batch_id, **kwargs):
        """View batch details and progress"""
        if not self._check_admin_access():
            return request.redirect('/web/login')
        
        batch = request.env['bulk.onboarding.batch'].sudo().browse(batch_id)
        
        if not batch.exists():
            return request.not_found()
        
        # If batch is stuck in 'processing' status and hasn't made progress, try to process it
        if batch.status == 'processing' and batch.progress_current == 0 and batch.progress_total > 0:
            # Check if it's been stuck for more than 30 seconds
            if batch.processing_started_at:
                time_since_start = (datetime.now() - batch.processing_started_at).total_seconds()
                if time_since_start > 30:
                    _logger.info(f"Batch {batch_id} appears stuck, attempting to process in background thread")
                    def process_stuck_batch():
                        try:
                            with batch.env.registry.cursor() as cr:
                                env = batch.env(cr=cr)
                                batch_record = env['bulk.onboarding.batch'].browse(batch_id)
                                if batch_record.exists() and batch_record.status == 'processing':
                                    batch_record.with_user(batch_record.created_by)._process_batch()
                                    cr.commit()
                        except Exception as e:
                            _logger.error(f"Error processing stuck batch {batch_id}: {str(e)}", exc_info=True)
                    thread = threading.Thread(target=process_stuck_batch, daemon=True)
                    thread.start()
        
        # Ensure reps are loaded with proper status
        reps = batch.rep_ids.sudo().sorted('create_date')
        
        # Check if we just started processing (from redirect)
        show_started_message = request.httprequest.args.get('started') == '1'
        
        return request.render('qr_code_odoo.bulk_onboarding_batch_view', {
            'batch': batch,
            'reps': reps,
            'show_started_message': show_started_message,
        })
    
    @http.route('/bulk-onboard/resend-invite/<int:rep_id>', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def resend_invite(self, rep_id, **kwargs):
        """Resend invitation email for a specific rep"""
        try:
            if not self._check_admin_access():
                return {'success': False, 'error': 'Access denied'}
            
            rep = request.env['bulk.onboarding.rep'].sudo().browse(rep_id)
            
            if not rep.exists():
                return {'success': False, 'error': 'User not found'}
            
            rep.action_resend_invitation()
            return {'success': True, 'message': 'Invitation resent successfully'}
        except Exception as e:
            _logger.error(f"Error resending invitation for rep {rep_id}: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @http.route('/bulk-onboard/bulk-resend-invite', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def bulk_resend_invite(self, **kwargs):
        """Resend invitation emails for multiple reps"""
        if not self._check_admin_access():
            return {'success': False, 'error': 'Access denied'}
        
        rep_ids = kwargs.get('rep_ids', [])
        if not rep_ids:
            return {'success': False, 'error': 'No rep IDs provided'}
        
        # Convert to integers if they're strings
        try:
            rep_ids = [int(rid) for rid in rep_ids]
        except (ValueError, TypeError):
            return {'success': False, 'error': 'Invalid rep IDs'}
        
        reps = request.env['bulk.onboarding.rep'].sudo().browse(rep_ids)
        
        if not reps:
            return {'success': False, 'error': 'No valid reps found'}
        
        sent_count = 0
        failed_count = 0
        errors = []
        
        for rep in reps:
            try:
                rep.action_resend_invitation()
                sent_count += 1
            except Exception as e:
                failed_count += 1
                error_msg = f"Rep {rep.name} ({rep.email}): {str(e)}"
                errors.append(error_msg)
                _logger.error(f"Error resending invitation for rep {rep.id}: {str(e)}", exc_info=True)
        
        result = {
            'success': True,
            'sent_count': sent_count,
            'failed_count': failed_count,
            'total_count': len(reps)
        }
        
        if errors:
            result['errors'] = errors[:10]  # Limit to first 10 errors
        
        return result

    # ------------------------------------------------------------------
    # Batch / rep lifecycle management (web UI)
    # ------------------------------------------------------------------
    def _start_batch_async(self, batch):
        """Kick a batch's processing on a background thread (same pattern as
        submit) so a draft can be (re)processed without blocking the request."""
        batch_id = batch.id

        def _run():
            try:
                with batch.env.registry.cursor() as cr:
                    env = batch.env(cr=cr)
                    rec = env['bulk.onboarding.batch'].browse(batch_id)
                    if rec.exists() and rec.status == 'processing':
                        rec.with_user(rec.created_by)._process_batch()
                        cr.commit()
            except Exception as e:
                _logger.error(f"Error processing batch {batch_id} in background: {e}", exc_info=True)

        threading.Thread(target=_run, daemon=True).start()

    @http.route('/bulk-onboard/rep/<int:rep_id>/update', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def update_rep(self, rep_id, **kwargs):
        """Inline-edit a rep's name / email (e.g. fix a typo'd address), reset
        it to pending and clear the prior error so it can be retried."""
        if not self._check_admin_access():
            return {'success': False, 'error': 'Access denied'}
        rep = request.env['bulk.onboarding.rep'].sudo().browse(rep_id)
        if not rep.exists():
            return {'success': False, 'error': 'Rep not found'}
        if rep.status in ('completed', 'activated'):
            return {'success': False, 'error': 'This rep is already active and cannot be edited.'}

        Batch = request.env['bulk.onboarding.batch']
        vals = {}
        name = kwargs.get('name')
        email = kwargs.get('email')
        if name is not None:
            vals['name'] = name.strip()
        if email is not None:
            cleaned = Batch._clean_email(email)
            vals['email'] = cleaned
        # Reset the row so the edit can be retried cleanly.
        vals['status'] = 'pending'
        vals['error_message'] = False
        rep.write(vals)
        # Keep the JSON payload in sync with the edited fields.
        rep_data = rep.get_rep_data()
        if name is not None:
            rep_data['name'] = vals['name']
        if email is not None:
            rep_data['email'] = vals['email']
        rep.set_rep_data(rep_data)
        rep.batch_id._refresh_status()
        return {'success': True, 'name': rep.name, 'email': rep.email, 'status': rep.status}

    @http.route('/bulk-onboard/rep/<int:rep_id>/delete', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def delete_rep(self, rep_id, **kwargs):
        """Remove a rep row from a batch."""
        if not self._check_admin_access():
            return {'success': False, 'error': 'Access denied'}
        rep = request.env['bulk.onboarding.rep'].sudo().browse(rep_id)
        if not rep.exists():
            return {'success': False, 'error': 'Rep not found'}
        batch = rep.batch_id
        rep.unlink()
        batch._refresh_status()
        return {'success': True}

    @http.route('/bulk-onboard/rep/<int:rep_id>/reprocess', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def reprocess_rep(self, rep_id, **kwargs):
        """Actually (re)create the user-linked card for a failed/pending rep —
        not just resend. Degrades to a resend if already provisioned."""
        if not self._check_admin_access():
            return {'success': False, 'error': 'Access denied'}
        rep = request.env['bulk.onboarding.rep'].sudo().browse(rep_id)
        if not rep.exists():
            return {'success': False, 'error': 'Rep not found'}
        return rep.action_reprocess()

    @http.route('/bulk-onboard/batch/<int:batch_id>/add-rep', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def add_rep(self, batch_id, **kwargs):
        """Add a single rep to an existing batch (resurrects an empty draft)."""
        if not self._check_admin_access():
            return {'success': False, 'error': 'Access denied'}
        batch = request.env['bulk.onboarding.batch'].sudo().browse(batch_id)
        if not batch.exists():
            return {'success': False, 'error': 'Batch not found'}
        Batch = request.env['bulk.onboarding.batch']
        email = Batch._clean_email(kwargs.get('email', ''))
        if not email:
            return {'success': False, 'error': 'A valid email is required.'}
        name = (kwargs.get('name') or '').strip()
        rep_data = {
            'name': name,
            'email': email,
            'phone': (kwargs.get('phone') or '').strip(),
            'function': (kwargs.get('function') or '').strip(),
        }
        rep = request.env['bulk.onboarding.rep'].sudo().create({
            'batch_id': batch.id,
            'name': name,
            'email': email,
            'phone': rep_data['phone'],
            'status': 'pending',
        })
        rep.set_rep_data(rep_data)
        return {'success': True, 'rep_id': rep.id}

    @http.route('/bulk-onboard/batch/<int:batch_id>/process', type='json', auth='user', website=True, csrf=False, methods=['POST'])
    def process_batch(self, batch_id, **kwargs):
        """Process / resume a batch that still has pending reps (draft, or a
        partial/failed batch with rows that never ran)."""
        if not self._check_admin_access():
            return {'success': False, 'error': 'Access denied'}
        batch = request.env['bulk.onboarding.batch'].sudo().browse(batch_id)
        if not batch.exists():
            return {'success': False, 'error': 'Batch not found'}
        pending = batch.rep_ids.filtered(lambda r: r.status == 'pending')
        if not pending:
            return {'success': False, 'error': 'There are no pending reps to process in this batch.'}
        # Move to draft so action_start_processing accepts it, then kick it off.
        batch.write({'status': 'draft'})
        try:
            batch.action_start_processing()
        except Exception as e:
            return {'success': False, 'error': str(e)}
        self._start_batch_async(batch)
        return {'success': True, 'message': f'Processing {len(pending)} rep(s) in the background.'}

    @http.route('/bulk-onboard/batch/<int:batch_id>/delete', type='http', auth='user', website=True, csrf=True, methods=['POST'])
    def delete_batch(self, batch_id, **kwargs):
        """Delete an entire batch and its reps, then return to the index."""
        if not self._check_admin_access():
            return request.redirect('/web/login')
        batch = request.env['bulk.onboarding.batch'].sudo().browse(batch_id)
        if batch.exists():
            batch.unlink()
        return request.redirect('/bulk-onboard')

    @http.route('/bulk-onboard/activate', type='http', auth='public', website=True, csrf=False)
    def activate_account(self, token=None, **kwargs):
        """Handle magic link activation"""
        if not token:
            return request.render('qr_code_odoo.magic_link_error', {
                'error': 'No token provided'
            })
        
        # Validate token
        token_model = request.env['bulk.onboarding.token'].sudo()
        valid, result = token_model.validate_token(token)
        
        if not valid:
            return request.render('qr_code_odoo.magic_link_error', {
                'error': result  # Error message
            })
        
        token_record = result
        user = token_record.user_id
        
        if not user:
            # Find user by email (fallback - should not be needed if token is properly linked)
            user = request.env['res.users'].sudo().search([
                ('login', '=', token_record.email.lower().strip())
            ], limit=1)
        
        if not user:
            _logger.error(f"User account not found for token {token}. Email: {token_record.email}, User ID in token: {token_record.user_id.id if token_record.user_id else 'None'}")
            return request.render('qr_code_odoo.magic_link_error', {
                'error': 'User account not found. Please contact your administrator to request a new invitation.'
            })
        
        # Check if already activated
        if user.active:
            # Already activated, redirect to login
            return request.render('qr_code_odoo.magic_link_already_activated', {
                'login_url': '/web/login'
            })
        
        # Show password setup form
        return request.render('qr_code_odoo.magic_link_activation', {
            'token': token,
            'email': user.login,
            'user_name': user.name
        })

    @http.route('/bulk-onboard/activate/submit', type='http', auth='public', website=True, csrf=True, methods=['POST'])
    def activate_account_submit(self, **post):
        """Submit password setup and activate account"""
        token = post.get('token')
        password = post.get('password')
        password_confirm = post.get('password_confirm')
        
        if not token:
            return request.render('qr_code_odoo.magic_link_error', {
                'error': 'No token provided'
            })
        
        # Validate token
        token_model = request.env['bulk.onboarding.token'].sudo()
        valid, result = token_model.validate_token(token)
        
        if not valid:
            return request.render('qr_code_odoo.magic_link_error', {
                'error': result
            })
        
        token_record = result
        
        # Validate passwords
        if not password or len(password) < 8:
            return request.render('qr_code_odoo.magic_link_activation', {
                'error': 'Password must be at least 8 characters',
                'token': token,
                'email': token_record.email
            })
        
        if password != password_confirm:
            return request.render('qr_code_odoo.magic_link_activation', {
                'error': 'Passwords do not match',
                'token': token,
                'email': token_record.email
            })
        
        # Find user
        user = token_record.user_id
        if not user:
            user = request.env['res.users'].sudo().search([
                ('login', '=ilike', token_record.email)
            ], limit=1)
        
        if not user:
            return request.render('qr_code_odoo.magic_link_error', {
                'error': 'User account not found'
            })
        
        # Set password and activate
        try:
            # For inactive users without a password, set it directly
            # change_password() requires old password, which doesn't work for new users
            user.sudo().password = password
            user.sudo().write({'active': True})
            request.env.cr.commit()
            
            # Mark token as used
            token_record.write({
                'used': True,
                'used_at': datetime.now()
            })
            
            # Update rep status
            rep = request.env['bulk.onboarding.rep'].sudo().search([
                ('user_id', '=', user.id)
            ], limit=1)
            if rep:
                rep.status = 'activated'
            
            # Auto-login server-side and redirect to complete-vcard.
            # Never place credentials in a GET redirect: the URL ends up in
            # Werkzeug / reverse-proxy access logs and the browser's history.
            try:
                request.session.authenticate(request.session.db, user.login, password)
            except Exception as auth_err:
                _logger.warning(f"Auto-login after activation failed, redirecting to login form: {auth_err}")
                return request.redirect('/web/login?redirect=/bulk-onboard/complete-vcard')
            return request.redirect('/bulk-onboard/complete-vcard')
            
        except Exception as e:
            _logger.error(f"Error activating account: {str(e)}", exc_info=True)
            return request.render('qr_code_odoo.magic_link_activation', {
                'error': f'Error activating account: {str(e)}',
                'token': token,
                'email': token_record.email
            })

    @http.route('/bulk-onboard/complete-vcard', type='http', auth='user', website=True)
    def complete_vcard(self, **kwargs):
        """Legacy route — recipients are now funnelled through /get-started
        with a bulk-activate flag so admin-pre-filled values pre-populate the
        editorial form and the same validation / live-preview surface that
        admins use is available to recipients. The dedicated complete_vcard
        template has been removed.
        """
        return request.redirect('/get-started?flow=bulk-activate')

    # /bulk-onboard/complete-vcard/submit removed — the recipient flow now
    # posts through /vcard/submit (same editorial form used on /get-started)
    # with the `flow=bulk-activate` hidden field, and /vcard/submit handles
    # the "update existing card instead of creating" branch.

