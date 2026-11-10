# -*- coding: utf-8 -*-
"""
Vinculum - Digital Business Cards Module
Copyright (C) 2024 Faris Delija. All Rights Reserved.
Licensed under OPL-1 (Odoo Proprietary License v1.0)

Unauthorized copying, modification, or distribution prohibited.
"""
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from markupsafe import escape as _html_escape
import json
import logging
import base64
import hashlib
import re
import time
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

# Module-level cache for default preview images (loaded from disk once per process).
# Keyed by the method name so invalidating one doesn't touch the other.
_DEFAULT_IMAGE_CACHE = {}


def _cached_default_image(vcard_env, kind):
    """Return a cached base64 default image ('profile' or 'banner'), loading on first miss."""
    if kind in _DEFAULT_IMAGE_CACHE:
        return _DEFAULT_IMAGE_CACHE[kind]
    getter = '_get_default_profile_image' if kind == 'profile' else '_get_default_banner_image'
    value = getattr(vcard_env, getter)()
    if value:
        _DEFAULT_IMAGE_CACHE[kind] = value
    return value


# Scalar form fields that affect the rendered preview template. Adding a new
# value to vals in generate_preview() that affects rendering REQUIRES adding
# the same key here, or previews will stale-cache until something else changes.
# Keep aligned with models/partner.py:PartnerVCard._TEMPLATE_AFFECTING_FIELDS
# (address + every social URL the preview templates can render).
HASHED_SCALARS = (
    'name', 'company_name', 'street', 'street2', 'city', 'zip',
    'country_id', 'state_id', 'function',
    'phone', 'mobile', 'email', 'website', 'calendly_url', 'about',
    'primary_color', 'secondary_color', 'website_template',
    'whatsapp_url',
    'linkedin_url', 'linkedin_url_company',
    'twitter_url', 'twitter_url_company',
    'instagram_url', 'instagram_url_company',
    'youtube_url',
    'facebook_url', 'facebook_url_company',
    'tiktok_url', 'pinterest_url', 'github_url', 'snapchat_url',
    'lead_button_label', 'form_thank_you_message',
    'show_form', 'mailing_list_name',
    'notify_on_new_lead', 'intro_email_enabled', 'enable_instant_leadback',
    'leadback_send_email', 'leadback_enable_messaging', 'show_reviews',
)


def _normalize_bool(v):
    """Match the truthy interpretation used in generate_preview's vals construction."""
    return v == 'yes' or v is True or v == True


def _compute_preview_hash(data, effective_show_form, mailing_list_name,
                          channel_codes, websites, videos,
                          image_token, banner_token):
    """Stable sha256 of every input that affects the rendered preview template.
    See HASHED_SCALARS for the contract on what's included."""
    scalars = {}
    for k in HASHED_SCALARS:
        v = data.get(k, '')
        # Normalize booleans so 'yes' / True / 'true' / False all hash consistently
        if k in ('notify_on_new_lead', 'intro_email_enabled',
                 'enable_instant_leadback', 'leadback_send_email',
                 'leadback_enable_messaging', 'show_reviews'):
            v = _normalize_bool(v)
        else:
            v = '' if v is None else v
        scalars[k] = v
    payload = {
        'scalars': scalars,
        'effective_show_form': bool(effective_show_form),
        'mailing_list_name': mailing_list_name if effective_show_form else '',
        'leadback_channel_codes': sorted(channel_codes),
        'websites': websites,
        'videos': videos,
        'image_token': image_token,
        'banner_token': banner_token,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'),
                           default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _build_browser_fingerprint(req):
    """Build browser fingerprint hash from request headers"""
    raw = json.dumps({
        'ua': req.httprequest.headers.get('User-Agent', ''),
        'accept': req.httprequest.headers.get('Accept', ''),
        'lang': req.httprequest.headers.get('Accept-Language', ''),
        'ip': req.httprequest.environ.get('REMOTE_ADDR', ''),
    }, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _get_ip_address(req):
    """Extract IP address from request, handling proxies"""
    # Check for forwarded IP headers (common in proxy/load balancer setups)
    forwarded_for = req.httprequest.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        ip = forwarded_for.split(',')[0].strip()
        if ip:
            return ip
    
    real_ip = req.httprequest.headers.get('X-Real-IP', '')
    if real_ip:
        return real_ip.strip()
    
    # Fallback to REMOTE_ADDR
    return req.httprequest.environ.get('REMOTE_ADDR', '')


LIMIT_PREFIX = 'qr_code_odoo.limit.'
FORM_LIMIT = 10  # posts per IP per 15-minute window
# Hidden field the card forms send; people never see it, form-filling bots do.
HONEYPOT_FIELD = 'company_fax'
TOO_MANY = {'status': 'error', 'message': 'Too many requests from here. Please try again later.'}


def _over_limit(req):
    """Fixed 15-minute bucket per address, shared by the public card forms.

    remote_addr, not X-Forwarded-For: with proxy_mode on, Odoo already
    resolves the real client address; a client-sent header could be spoofed.
    """
    ip = req.httprequest.remote_addr or 'unknown'
    bucket = int(time.time() // 900)
    key = f"{LIMIT_PREFIX}{hashlib.sha256(ip.encode()).hexdigest()}.{bucket}"
    # Lock so parallel posts from one address share the counter.
    req.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [key])
    params = req.env['ir.config_parameter'].sudo()
    # Counters from earlier windows are no longer needed ('not like' wraps in %).
    params.search([('key', '=like', f'{LIMIT_PREFIX}%'), ('key', 'not like', f'.{bucket}')]).unlink()
    count = int(params.get_param(key, '0'))
    if count >= FORM_LIMIT:
        return True
    params.set_param(key, str(count + 1))
    return False


def _card_visible(card):
    """A published card is public; an unpublished one only for users who may read it."""
    if (card.website_slug or '').startswith('preview-'):
        return not request.env.user._is_public() and card.website_slug == f'preview-{request.env.uid}'
    # Same pages the card route checks: the linked page and the page at /<slug>.
    pages = card.website_page_id | request.env['website.page'].sudo().search(
        [('url', '=', f'/{card.website_slug}')]) if card.website_slug else card.website_page_id
    if pages and all(pages.mapped('is_published')):
        return True
    if request.env.user._is_public():
        return False
    user_card = card.with_env(request.env)
    try:
        user_card.check_access_rights('read')
        user_card.check_access_rule('read')
    except AccessError:
        return False
    return True


def _count_once(card, kind):
    """True the first time this session hits `kind` for this card."""
    key = f'vinc_counted_{kind}'
    seen = request.session.get(key) or []
    if card.id in seen:
        return False
    request.session[key] = seen + [card.id]
    return True


def _get_geolocation_from_ip(ip_address):
    """
    Get geolocation data from IP address using free services (no API key required).
    Tries multiple free services as fallback.
    Returns dict with country, city, timezone, or None if lookup fails.
    """
    if not ip_address or ip_address in ('127.0.0.1', 'localhost', '::1'):
        return None
    
    import urllib.request
    import urllib.error
    
    # List of free IP geolocation services to try (in order of preference)
    services = [
        {
            'name': 'geojs.io',
            'url': f'https://get.geojs.io/v1/ip/geo/{ip_address}.json',
            'parser': lambda d: {
                'country': d.get('country', ''),
                'city': d.get('city', ''),
                'timezone': d.get('timezone', ''),
                'country_code': d.get('country_code', ''),
                'region': d.get('region', ''),
            }
        },
        {
            'name': 'ip-api.com',
            'url': f'http://ip-api.com/json/{ip_address}?fields=status,country,countryCode,city,timezone,regionName',
            'parser': lambda d: {
                'country': d.get('country', ''),
                'city': d.get('city', ''),
                'timezone': d.get('timezone', ''),
                'country_code': d.get('countryCode', ''),
                'region': d.get('regionName', ''),
            } if d.get('status') == 'success' else None
        },
    ]
    
    # Try each service until one succeeds
    for service in services:
        try:
            req = urllib.request.Request(
                service['url'],
                headers={'User-Agent': 'Odoo-LeadTracker/1.0'}
            )
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode())
                result = service['parser'](data)
                if result:
                    _logger.debug(f"IP geolocation lookup succeeded using {service['name']} for {ip_address}")
                    return result
        except Exception as e:
            _logger.debug(f"IP geolocation lookup failed using {service['name']} for {ip_address}: {e}")
            continue
    
    # If all services fail, return None (graceful fallback)
    _logger.debug(f"All IP geolocation services failed for {ip_address}, continuing without geolocation data")
    return None


def _parse_user_agent(user_agent):
    """Parse user agent string to extract device type, browser, and OS"""
    if not user_agent:
        return {'device_type': '', 'browser': '', 'os': ''}
    
    ua_lower = user_agent.lower()
    
    # Device type detection
    device_type = 'desktop'
    if any(mobile in ua_lower for mobile in ['mobile', 'android', 'iphone', 'ipod']):
        device_type = 'mobile'
    elif 'tablet' in ua_lower or 'ipad' in ua_lower:
        device_type = 'tablet'
    
    # Browser detection
    browser = 'Unknown'
    if 'chrome' in ua_lower and 'edg' not in ua_lower:
        browser = 'Chrome'
    elif 'firefox' in ua_lower:
        browser = 'Firefox'
    elif 'safari' in ua_lower and 'chrome' not in ua_lower:
        browser = 'Safari'
    elif 'edg' in ua_lower or 'edge' in ua_lower:
        browser = 'Edge'
    elif 'opera' in ua_lower or 'opr' in ua_lower:
        browser = 'Opera'
    
    # OS detection
    os_name = 'Unknown'
    if 'windows' in ua_lower:
        os_name = 'Windows'
    elif 'mac' in ua_lower or 'darwin' in ua_lower:
        os_name = 'macOS'
    elif 'linux' in ua_lower:
        os_name = 'Linux'
    elif 'android' in ua_lower:
        os_name = 'Android'
    elif 'iphone' in ua_lower or 'ipad' in ua_lower:
        os_name = 'iOS'
    
    return {
        'device_type': device_type,
        'browser': browser,
        'os': os_name
    }


def _extract_tracking_data_from_request(req, data=None):
    """
    Extract all tracking data from the HTTP request and form data.
    Similar to referral tracking but for lead form submissions.
    
    Returns dict with all tracking fields.
    """
    # Get IP address (handling proxies)
    ip_address = _get_ip_address(req)

    # Get user agent
    user_agent = req.httprequest.headers.get('User-Agent', '')

    # Build browser fingerprint
    fingerprint_hash = _build_browser_fingerprint(req)

    # Geolocation moved off the sync path. Previously this blocked the submit
    # for up to 4s waiting on two upstream geo providers — a very user-visible
    # latency hit. The IP is stored with the lead / download-tracking row and
    # the `Vinc: Enrich lead geolocation` cron backfills country / city /
    # timezone asynchronously (see data/cron_actions.xml).
    geolocation = None

    # Parse user agent
    ua_info = _parse_user_agent(user_agent)
    
    # Get language
    language = req.httprequest.headers.get('Accept-Language', '')
    # Extract primary language (e.g., "en-US,en;q=0.9" -> "en-US")
    if language:
        language = language.split(',')[0].split(';')[0].strip()
    
    # Get referrer/source URL
    source_url = req.httprequest.referrer or req.httprequest.url
    
    # Extract UTM parameters and referral code from URL or form data
    utm_source = None
    utm_medium = None
    utm_campaign = None
    referral_code = None
    
    # Check URL parameters first
    url_params = req.httprequest.args
    utm_source = url_params.get('utm_source') or None
    utm_medium = url_params.get('utm_medium') or None
    utm_campaign = url_params.get('utm_campaign') or None
    referral_code = url_params.get('ref') or None
    
    # Check form data if provided
    if data:
        utm_source = utm_source or data.get('utm_source') or None
        utm_medium = utm_medium or data.get('utm_medium') or None
        utm_campaign = utm_campaign or data.get('utm_campaign') or None
        referral_code = referral_code or data.get('ref') or data.get('referral_code') or None
    
    # Check session (for UTM params stored from previous page visit)
    if hasattr(req, 'session'):
        utm_source = utm_source or req.session.get('utm_source') or None
        utm_medium = utm_medium or req.session.get('utm_medium') or None
        utm_campaign = utm_campaign or req.session.get('utm_campaign') or None
        referral_code = referral_code or req.session.get('referral_code') or None
    
    # Build tracking data dict
    tracking_data = {
        'submission_ip': ip_address,
        'submission_user_agent': user_agent,
        'submission_fingerprint_hash': fingerprint_hash,
        'submission_language': language,
        'submission_source_url': source_url,
        'submission_utm_source': utm_source,
        'submission_utm_medium': utm_medium,
        'submission_utm_campaign': utm_campaign,
        'submission_referral_code': referral_code,
        'submission_device_type': ua_info.get('device_type', ''),
        'submission_browser': ua_info.get('browser', ''),
        'submission_os': ua_info.get('os', ''),
    }
    
    # Add geolocation data if available
    if geolocation:
        tracking_data['submission_country'] = geolocation.get('country', '')
        tracking_data['submission_city'] = geolocation.get('city', '')
        tracking_data['submission_timezone'] = geolocation.get('timezone', '')
    
    return tracking_data

class QRCodeController(http.Controller):

    @http.route('/qr/<int:partner_id>', type='http', auth='public')
    def redirect_to_dynamic_url(self, partner_id):
        partner = request.env['partner.vcard'].sudo().browse(partner_id)
    
        if partner.exists():
            if _count_once(partner, 'scan'):
                partner.sudo().write({'qr_code_scan_count': partner.qr_code_scan_count + 1})

            if partner.website_full_url:
                return request.redirect(partner.website_full_url)
            else:
                return request.not_found()
        else:
            return request.not_found()

    @http.route('/track_page_view/<string:slug>', type='json', auth='public', methods=['POST'], csrf=False)
    def track_page_view(self, slug, **kwargs):
        """Track page views for vCard pages via AJAX call from the page"""
        try:
            vcard = request.env['partner.vcard'].sudo().search([
                ('website_slug', '=', slug)
            ], limit=1)
            
            if vcard:
                if _card_visible(vcard) and _count_once(vcard, 'view'):
                    vcard.sudo().write({'page_view_count': vcard.page_view_count + 1})
                return {'success': True, 'views': vcard.page_view_count}
            else:
                _logger.warning(f"Page view tracking: vCard with slug '{slug}' not found")
                return {'success': False, 'error': 'vCard not found'}
        except Exception as e:
            _logger.error(f"Error tracking page view for slug '{slug}': {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}

    @http.route('/vcard/qr_code/download/<int:partner_id>', type='http', auth='public')
    def download_qr_code(self, partner_id):
        """Serve the QR code image for download"""
        partner = request.env['partner.vcard'].sudo().browse(partner_id)
        
        if not partner.exists() or not partner.qr_code or not _card_visible(partner):
            return request.not_found()

        # Prepare the QR code image for download
        qr_code_data = base64.b64decode(partner.qr_code)

        # Sanitize + quote the filename. Owner-controlled name could otherwise
        # contain `"` or `;` sequences that break Content-Disposition parsing
        # or forge the extension shown to downloaders.
        safe_name = re.sub(r'[^\w.-]', '_', partner.name or 'vcard') or 'vcard'
        return request.make_response(
            qr_code_data,
            headers=[
                ('Content-Type', 'image/png'),
                ('Content-Disposition', f'attachment; filename="{safe_name}_qr_code.png"'),
            ]
        )

class PartnerController(http.Controller):

    @http.route('/get_partner_name', type='json', auth="public", methods=['GET'], csrf=False)
    def get_partner_name(self, partner_id=None):
        if not partner_id:
            return {'error': 'No partner ID provided'}

        partner = request.env['partner.vcard'].sudo().search([('id', '=', int(partner_id))], limit=1)
        if partner:
            return {'partner_name': partner.name}
        else:
            return {'error': 'Partner not found'}



class VCardController(http.Controller):
    
    @http.route('/<string:slug>', type='http', auth='public', website=True, methods=['GET'], priority=10)
    def track_vcard_page_view(self, slug, **kwargs):
        """Track page views for vCard pages - intercepts requests to vCard slugs"""
        # Check if this is a preview slug (allow it through)
        is_preview = slug.startswith('preview-')
        
        # Check if this is a vCard slug (not a system route)
        excluded_prefixes = ('web', 'website', 'start', 'tap', 'saas', 'nfc', 'get-started', 'vcard', 
                           'track_page_view', 'qr', 'create_lead', 'create_review', 'vinculum', 
                           'odoo', 'mail', 'subscription')
        excluded_extensions = ('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', 
                             '.woff', '.woff2', '.ttf', '.eot', '.map')
        
        # Skip if it's a system route or static file
        if not is_preview and (slug.startswith(excluded_prefixes) or slug.endswith(excluded_extensions)):
            # Let Odoo handle it normally by returning 404, which will let other routes try
            return request.not_found()
        
        # Try to find a vCard with this slug
        vcard = request.env['partner.vcard'].sudo().search([
            ('website_slug', '=', slug)
        ], limit=1)
        
        if vcard:
            # Persist any UTM / referral params from the landing URL into the
            # session. The vCard download endpoint (/website/vcard/download/<id>)
            # carries no query string, so without this the download-tracking
            # row never captures UTM. _extract_tracking_data_from_request reads
            # these session values back when the download happens.
            for _utm_key in ('utm_source', 'utm_medium', 'utm_campaign'):
                _utm_val = kwargs.get(_utm_key)
                if _utm_val:
                    request.session[_utm_key] = _utm_val
            if kwargs.get('ref'):
                request.session['referral_code'] = kwargs.get('ref')

            if is_preview and not _card_visible(vcard):
                return request.not_found()
            if not is_preview:
                # Check if website page is published
                website_page = request.env['website.page'].sudo().search([
                    ('url', '=', f'/{slug}')
                ], limit=1)

                if website_page and not website_page.is_published:
                    _logger.warning(f"Blocked access to vCard slug '{slug}' (ID: {vcard.id}) - website page is unpublished")
                    return request.not_found()

                # Also check via website_page_id if set
                if vcard.website_page_id and not vcard.website_page_id.is_published:
                    _logger.warning(f"Blocked access to vCard slug '{slug}' (ID: {vcard.id}) - website page via website_page_id is unpublished")
                    return request.not_found()

            if not is_preview and _count_once(vcard, 'view'):
                vcard.sudo().write({'page_view_count': vcard.page_view_count + 1})

            # Referral URL is always /get-started
            final_referral_url = '/get-started'

            # Render the page using the view key (same as how website pages are rendered)
            # Pass the computed referral URL in context to ensure it's available
            view_key = f'website.{slug}'
            return request.render(view_key, {
                'referral_url': final_referral_url,
            })

        # Not a vCard slug. If a published website.page owns this URL, render
        # it directly so this priority=10 catch-all does not shadow ordinary
        # website pages. Returning request.not_found() here is unreliable for
        # authenticated users: Odoo's _serve_fallback recovery does not always
        # run after the catch-all matched, producing a 404 on real pages
        # (e.g. /help-desk, /about-us) for logged-in users while logged-out
        # users see the page correctly.
        website_page = request.env['website.page'].sudo().search([
            ('url', '=', f'/{slug}'),
            ('is_published', '=', True),
        ], limit=1)
        if website_page:
            return request.render(website_page.view_id.id, {
                'main_object': website_page,
            })

        return request.not_found()

    @http.route('/website/vcard/download/<int:partner_id>', type='http', auth="public")
    def download_vcard(self, partner_id):
        """Endpoint to download vCard for the given partner."""
        partner = request.env['partner.vcard'].sudo().browse(partner_id)
        if not partner.exists() or not _card_visible(partner):
            return request.not_found()
        if not _count_once(partner, 'download'):
            return self._vcf_response(partner)

        # Extract tracking data from request (IP, user agent, geolocation, UTM params, etc.)
        tracking_data = _extract_tracking_data_from_request(request)
        _logger.info(f"=== VCARD DOWNLOAD TRACKING ===")
        _logger.info(f"Partner ID: {partner_id}, IP: {tracking_data.get('submission_ip')}")
        _logger.info(f"Country: {tracking_data.get('submission_country')}, City: {tracking_data.get('submission_city')}")
        _logger.info(f"Device: {tracking_data.get('submission_device_type')}, Browser: {tracking_data.get('submission_browser')}")

        # Create download tracking record
        download_tracking_vals = {
            'partner_vcard_id': partner.id,
            'download_ip': tracking_data.get('submission_ip', ''),
            'download_user_agent': tracking_data.get('submission_user_agent', ''),
            'download_fingerprint_hash': tracking_data.get('submission_fingerprint_hash', ''),
            'download_country': tracking_data.get('submission_country', ''),
            'download_city': tracking_data.get('submission_city', ''),
            'download_timezone': tracking_data.get('submission_timezone', ''),
            'download_language': tracking_data.get('submission_language', ''),
            'download_source_url': tracking_data.get('submission_source_url', ''),
            'download_utm_source': tracking_data.get('submission_utm_source'),
            'download_utm_medium': tracking_data.get('submission_utm_medium'),
            'download_utm_campaign': tracking_data.get('submission_utm_campaign'),
            'download_referral_code': tracking_data.get('submission_referral_code'),
            'download_device_type': tracking_data.get('submission_device_type', ''),
            'download_browser': tracking_data.get('submission_browser', ''),
            'download_os': tracking_data.get('submission_os', ''),
        }
        
        try:
            request.env['vcard.download.tracking'].sudo().create(download_tracking_vals)
            _logger.info(f"Download tracking record created for partner {partner_id}")
        except Exception as e:
            _logger.error(f"Error creating download tracking record: {e}", exc_info=True)
            # Continue even if tracking fails

        partner.sudo().write({'vcard_download_count': partner.vcard_download_count + 1})
        return self._vcf_response(partner)

    def _vcf_response(self, partner):
        vcard_content = partner._generate_vcf()
        # Sanitize + quote. Unsanitised owner-controlled names could forge the
        # extension shown to downloaders or break the header.
        safe_name = re.sub(r'[^\w.-]', '_', partner.name or 'vcard') or 'vcard'
        vcard_filename = f"{safe_name}.vcf"

        # Return the vCard as a downloadable file
        return request.make_response(
            vcard_content,
            headers=[
                ('Content-Type', 'text/vcard'),
                ('Content-Disposition', f'attachment; filename="{vcard_filename}"'),
            ]
        )

class NFCOnboardingController(http.Controller):

    @http.route('/nfc/setup/<int:partner_id>', type='http', auth='public', website=True)
    def nfc_onboarding(self, partner_id):
        """NFC Card Programming Onboarding Guide"""
        partner = request.env['partner.vcard'].sudo().browse(partner_id)
        
        if not partner.exists():
            return request.not_found()
        
        return request.render('qr_code_odoo.nfc_onboarding_page', {
            'vcard_url': partner.website_full_url,
            'partner': partner
        })

    # Hub + 8 sub-pages. Order in GUIDE_NAV drives both the sidebar and
    # the prev/next pagination at the bottom of each sub-page.
    GUIDE_NAV = [
        {'track': 'users', 'label': 'For Users', 'topics': [
            ('setup-card',   'Setting Up Your Card'),
            ('share-card',   'Sharing Your Card'),
            ('lead-capture', 'Lead Capture & Email Marketing'),
            ('reviews',      'Collecting Reviews'),
        ]},
        {'track': 'admins', 'label': 'For Administrators', 'topics': [
            ('bulk-onboard', 'Bulk Onboarding'),
            ('crm',          'CRM & Lead Routing'),
            ('nfc',          'NFC Card Programming'),
            ('automations',  'Email Automations & Digests'),
            ('branding',     'Branding & White-Label'),
        ]},
    ]
    GUIDE_TOPICS = {
        slug: {'template': f'qr_code_odoo.vinculum_guide_{slug.replace("-", "_")}',
               'track': group['track'], 'title': title}
        for group in GUIDE_NAV
        for (slug, title) in group['topics']
    }

    def _guide_context(self, current_topic):
        """Common render context for every guide page (hub + sub-pages)."""
        ctx = {
            'guide_nav': self.GUIDE_NAV,
            'guide_topics': self.GUIDE_TOPICS,
            'current_topic': current_topic,
            'current_track': self.GUIDE_TOPICS[current_topic]['track'] if current_topic else None,
        }
        # Compute prev/next within the same track.
        if current_topic:
            track = ctx['current_track']
            flat = [t for g in self.GUIDE_NAV if g['track'] == track for t in g['topics']]
            slugs = [s for (s, _) in flat]
            i = slugs.index(current_topic)
            ctx['prev_topic'] = flat[i - 1] if i > 0 else None
            ctx['next_topic'] = flat[i + 1] if i + 1 < len(flat) else None
        else:
            ctx['prev_topic'] = ctx['next_topic'] = None
        # Hero CTA on the hub depends on whether the signed-in user already has
        # a vCard. Mirror user_dashboard._compute_vcards (create_uid + email).
        has_vcard = False
        if request.session.uid:
            VC = request.env['partner.vcard'].sudo()
            user = request.env['res.users'].sudo().browse(request.session.uid)
            domain = ['|', ('create_uid', '=', user.id),
                      ('email', '=', user.partner_id.email)] if user.partner_id and user.partner_id.email \
                     else [('create_uid', '=', user.id)]
            has_vcard = bool(VC.search_count(domain))
        ctx['guide_user_has_vcard'] = has_vcard
        ctx['guide_user_signed_in'] = bool(request.session.uid)
        Brand = request.env['qr_code_odoo.brand'].sudo()
        ctx['brand_name'] = Brand.get_brand_name()
        ctx['brand_short_name'] = Brand.get_brand_short_name()
        ctx['brand_icon_url'] = Brand.get_brand_icon_url()
        ctx['brand_wordmark_url'] = Brand.get_brand_wordmark_url()
        return ctx

    @http.route('/vinculum/guide', type='http', auth='public', website=True)
    def vinculum_guide_hub(self):
        """Vinc Guide hub — landing page + audience picker."""
        return request.render('qr_code_odoo.vinculum_guide_hub',
                              self._guide_context(None))

    @http.route('/vinculum/guide/<string:topic>', type='http', auth='public', website=True)
    def vinculum_guide_topic(self, topic):
        """Vinc Guide sub-page (one of GUIDE_TOPICS). 404 on unknown topic."""
        import werkzeug
        if topic not in self.GUIDE_TOPICS:
            raise werkzeug.exceptions.NotFound()
        return request.render(self.GUIDE_TOPICS[topic]['template'],
                              self._guide_context(topic))


class ReviewController(http.Controller):

    @http.route('/create_review', type='json', auth='public', methods=['POST'], csrf=False)
    def create_review(self, **kwargs):
        _logger.info("create_review route called")

        try:
            # Load and log incoming data
            data = json.loads(request.httprequest.data)
            if data.get(HONEYPOT_FIELD):
                # Honeypot filled in: answer like a success so bots learn nothing.
                return {'status': 'success', 'message': 'Thank you!'}
            if _over_limit(request):
                return TOO_MANY
            _logger.info(f"Received review data: {data}")

            # Extract data from the request
            reviewer_name = data.get('reviewer_name')
            rating = data.get('rating')
            review_text = data.get('review_text')
            partner_vcard_id = data.get('partner_id')

            # Ensure partner_vcard_id is an integer
            try:
                partner_vcard_id = int(partner_vcard_id)
                _logger.info(f"Converted partner_id to int: {partner_vcard_id}")
            except (ValueError, TypeError):
                _logger.error(f"Invalid partner_id: {partner_vcard_id}")
                return {'status': 'error', 'message': 'Invalid partner ID'}

            # Validate required fields
            if not reviewer_name or not rating or not review_text:
                _logger.error("Missing required fields: reviewer_name, rating, or review_text")
                return {'status': 'error', 'message': 'Missing required fields'}

            # Validate rating
            if rating not in ['1', '2', '3', '4', '5']:
                _logger.error(f"Invalid rating: {rating}")
                return {'status': 'error', 'message': 'Invalid rating value'}

            # Search for the partner by ID
            partner = request.env['partner.vcard'].sudo().search([('id', '=', partner_vcard_id)], limit=1)
            _logger.info(f"Searching for partner with ID {partner_vcard_id}")

            # Check if the partner exists
            if not partner:
                _logger.error(f"Partner with ID {partner_vcard_id} not found")
                return {'status': 'error', 'message': 'Partner not found'}

            # Create the review (unpublished by default)
            review = request.env['partner.vcard.reviews'].sudo().create({
                'reviewer_name': reviewer_name,
                'rating': rating,
                'review_text': review_text,
                'partner_id': partner.id,
                'is_published': False,  # Unpublished by default
            })

            _logger.info(f"Review created successfully with ID: {review.id}")

            # Retrieve the custom thank you message from the partner
            custom_message = partner.review_thank_you_message or 'Thank you for your review! We appreciate your feedback.'

            # Return success response in the format expected by JavaScript
            return {'status': 'success', 'message': custom_message, 'review_id': review.id}

        except Exception as e:
            _logger.exception("Error in create_review")
            return {'status': 'error', 'message': f'Error processing request: {str(e)}'}

class LeadController(http.Controller):

    @http.route('/create_lead', type='json', auth='public', methods=['POST'], csrf=False)
    def create_lead(self, **kwargs):
        _logger.info("create_lead route called")

        try:
            # Load and log incoming data
            data = json.loads(request.httprequest.data)
            if data.get(HONEYPOT_FIELD):
                # Honeypot filled in: answer like a success so bots learn nothing.
                return {'status': 'success', 'message': 'Thank you!'}
            if _over_limit(request):
                return TOO_MANY
            _logger.info(f"Received data: {data}")

            # Extract tracking data from request (IP, user agent, geolocation, UTM params, etc.)
            tracking_data = _extract_tracking_data_from_request(request, data)
            _logger.info(f"=== LEAD TRACKING DATA ===")
            _logger.info(f"IP Address: {tracking_data.get('submission_ip')}")
            _logger.info(f"User Agent: {tracking_data.get('submission_user_agent')}")
            _logger.info(f"Country: {tracking_data.get('submission_country')}")
            _logger.info(f"City: {tracking_data.get('submission_city')}")
            _logger.info(f"Timezone: {tracking_data.get('submission_timezone')}")
            _logger.info(f"UTM Source: {tracking_data.get('submission_utm_source')}")
            _logger.info(f"UTM Medium: {tracking_data.get('submission_utm_medium')}")
            _logger.info(f"UTM Campaign: {tracking_data.get('submission_utm_campaign')}")
            _logger.info(f"Referral Code: {tracking_data.get('submission_referral_code')}")
            _logger.info(f"Device: {tracking_data.get('submission_device_type')} | Browser: {tracking_data.get('submission_browser')} | OS: {tracking_data.get('submission_os')}")

            # Extract data from the request
            contact_name = data.get('contact_name')
            email_from = data.get('email_from')
            phone = data.get('phone')
            partner_vcard_id = data.get('partner_id')
            description = data.get('description')
            lead_tag_ids = data.get('lead_tag_ids', [])

            _logger.info(f"=== LEAD FORM SUBMISSION ===")
            _logger.info(f"Received partner_id: {partner_vcard_id}")

            # Ensure partner_vcard_id is an integer
            try:
                partner_vcard_id = int(partner_vcard_id)
                _logger.info(f"Converted partner_id to int: {partner_vcard_id}")
            except (ValueError, TypeError):
                _logger.error(f"Invalid partner_id: {partner_vcard_id}")
                return {'status': 'error', 'message': 'Invalid partner ID'}

            # Validate required fields
            if not contact_name or not email_from:
                _logger.error("Missing required fields: contact_name or email_from")
                return {'status': 'error', 'message': 'Missing required fields'}

            # Search for the partner by ID
            partner = request.env['partner.vcard'].sudo().search([('id', '=', partner_vcard_id)], limit=1)
            _logger.info(f"Searching for partner with ID {partner_vcard_id}")
            _logger.info(f"Partner found: {partner.exists()}")

            # Check if the partner exists
            if not partner:
                _logger.error(f"Partner with ID {partner_vcard_id} not found")
                return {'status': 'error', 'message': 'Partner not found'}

            # Validate and filter lead_tag_ids to ensure they belong to the partner
            valid_tag_ids = []
            if lead_tag_ids and hasattr(partner, 'lead_tag_ids') and partner.lead_tag_ids:
                try:
                    # Convert to integers and filter out any invalid IDs
                    lead_tag_ids = [int(tag_id) for tag_id in lead_tag_ids if tag_id]
                    valid_tag_ids = partner.lead_tag_ids.filtered(lambda tag: tag.id in lead_tag_ids).ids
                    if not valid_tag_ids:
                        _logger.warning("No valid lead_tag_ids found for the partner")
                except Exception as e:
                    _logger.warning(f"Error processing lead tags: {e}")
                    valid_tag_ids = []
            else:
                _logger.info("Lead tags not available or not configured")

            _logger.info(f"Valid tag IDs to be assigned: {valid_tag_ids}")
            
            # Resolve the card owner so the new opportunity is auto-assigned.
            # 1) Try login match on the card's email (common when cardholder
            #    logged in with their real email).
            # 2) Fall back to the user who created the card record
            #    (create_uid), but skip Odoo's built-in system/public users
            #    (ids 1=OdooBot, 3=Default User Template, 4=Public) so a card
            #    created via the public /get-started route doesn't end up
            #    assigning leads to an anonymous user. Admin (id=2) IS used.
            _SKIP_AUTOASSIGN_UIDS = (1, 3, 4)
            owner_user_id = False
            if partner.email:
                owner_user = request.env['res.users'].sudo().search(
                    [('login', '=', partner.email)], limit=1)
                if owner_user:
                    owner_user_id = owner_user.id
            if (not owner_user_id and partner.create_uid
                    and partner.create_uid.id not in _SKIP_AUTOASSIGN_UIDS):
                owner_user_id = partner.create_uid.id

            # Create the opportunity and associate it with the partner and tags
            # Include all tracking data
            opportunity_vals = {
                'contact_name': contact_name,
                'email_from': email_from,
                'phone': phone,
                'partner_vcard_id': partner.id,
                'type': 'opportunity',  # This makes it an opportunity instead of a lead
                'description': description,
                'name': f'New vCard form submission for {partner.name}',
                'tag_ids': [(6, 0, valid_tag_ids)] if valid_tag_ids else False,
            }
            if owner_user_id:
                opportunity_vals['user_id'] = owner_user_id
                _logger.info(f"Lead auto-assigned to user_id={owner_user_id} (card owner)")

            # Add all tracking data to opportunity
            opportunity_vals.update(tracking_data)

            partner.sudo()._stamp_event_on_lead(
                opportunity_vals, contact_name, email_from, phone,
            )
            opportunity = request.env['crm.lead'].sudo().create(opportunity_vals)

            _logger.info(f"Opportunity created with tracking data: IP={tracking_data.get('submission_ip')}, Country={tracking_data.get('submission_country')}, UTM={tracking_data.get('submission_utm_source')}")
            _logger.info(f"Opportunity created with ID: {opportunity.id}")

            # Get the CRM tags that were applied to the lead
            applied_tags = partner.lead_tag_ids if partner.lead_tag_ids else None
            _logger.info(f"Partner lead_tag_ids: {partner.lead_tag_ids}")
            _logger.info(f"Applied tags to pass: {applied_tags}")

            # Add contact to email marketing with tags
            self._add_to_mailing_list(contact_name, email_from, partner, applied_tags)

            # Send notification email to vCard owner if enabled (queued, not
            # sent synchronously — mail cron delivers within the minute).
            if partner.notify_on_new_lead and partner.email:
                try:
                    self._send_lead_notification_email(partner, opportunity, contact_name, email_from, phone, description)
                except Exception as e:
                    _logger.error(f"Error sending lead notification email: {str(e)}", exc_info=True)

            # Send introduction email to lead if enabled (queued)
            if partner.intro_email_enabled and email_from:
                try:
                    self._send_intro_email(partner, contact_name, email_from, opportunity)
                except Exception as e:
                    _logger.error(f"Error sending intro email: {str(e)}", exc_info=True)

            # Send instant lead-back message if enabled.
            # Email is queued; messaging links (WhatsApp/Viber/Telegram) are
            # generated inline and posted to the opportunity's chatter.
            if partner.enable_instant_leadback and (email_from or phone):
                try:
                    partner.sudo()._send_instant_leadback_message(
                        contact_name=contact_name,
                        contact_phone=phone or '',
                        contact_email=email_from,
                        opportunity=opportunity
                    )
                    _logger.info(f"Instant lead-back sent for opportunity {opportunity.id} (email: {bool(email_from)}, phone: {bool(phone)})")
                except Exception as e:
                    _logger.exception(f"Error sending instant lead-back message: {e}")
                    # Don't fail the lead creation if messaging fails
                    # Error is already logged to the lead timeline

            # Schedule follow-up reminder activities if enabled
            if partner.followup_reminders_enabled:
                try:
                    activities_created, reminders_queued = partner.sudo()._schedule_followup_reminders(opportunity, contact_name)
                    total = activities_created + reminders_queued
                    if total > 0:
                        _logger.info(
                            f"Follow-up reminders scheduled for opportunity {opportunity.id}: "
                            f"{activities_created} activity/ies created immediately, "
                            f"{reminders_queued} reminder(s) queued for cron processing"
                        )
                except Exception as e:
                    _logger.exception(f"Error scheduling follow-up reminders: {e}")
                    # Don't fail the lead creation if reminder scheduling fails

            # Retrieve the custom thank you message from the partner
            custom_message = partner.form_thank_you_message or 'Thank you! I look forward to talking to you soon!'

            # Return success response in the format expected by JavaScript
            return {'status': 'success', 'message': custom_message, 'opportunity_id': opportunity.id}

        except Exception as e:
            _logger.exception("Error in create_lead")
            return {'status': 'error', 'message': f'Error processing request: {str(e)}'}
    
    def _add_to_mailing_list(self, name, email, partner, lead_tags=None):
        """Add contact to email marketing mailing list with tags"""
        try:
            # Check if contact already exists
            existing_contact = request.env['mailing.contact'].sudo().search([
                ('email', '=', email)
            ], limit=1)
            
            if existing_contact:
                _logger.info(f"Contact {email} already exists in mailing list")
                # Update tags if provided
                if lead_tags:
                    tag_ids = self._sync_tags_to_mailing_tags(lead_tags)
                    if tag_ids:
                        existing_contact.tag_ids = [(4, tag_id) for tag_id in tag_ids]
                        _logger.info(f"Updated existing contact with {len(tag_ids)} tags")
                return existing_contact
            
            # Use the vCard's specified mailing list
            mailing_list = partner.mailing_list_id
            
            if not mailing_list:
                _logger.warning(f"No mailing list configured for vCard {partner.id}")
                # Fallback: Find or create "All Contacts" mailing list
                mailing_list = request.env['mailing.list'].sudo().search([
                    ('name', '=', 'All Contacts')
                ], limit=1)
                
                if not mailing_list:
                    mailing_list = request.env['mailing.list'].sudo().create({
                        'name': 'All Contacts'
                    })
                    _logger.info(f"Created 'All Contacts' mailing list")
            
            _logger.info(f"Using mailing list: {mailing_list.name} (ID: {mailing_list.id})")
            
            # Sync CRM tags to mailing contact tags
            tag_ids = []
            if lead_tags:
                _logger.info(f"Syncing {len(lead_tags)} tags to mailing tags")
                tag_ids = self._sync_tags_to_mailing_tags(lead_tags)
                _logger.info(f"Tag IDs created: {tag_ids}")
            
            # Create mailing contact with tags
            contact_vals = {
                'name': name,
                'email': email,
                'list_ids': [(6, 0, [mailing_list.id])]
            }
            
            if tag_ids:
                contact_vals['tag_ids'] = [(6, 0, tag_ids)]
            
            mailing_contact = request.env['mailing.contact'].sudo().create(contact_vals)
            
            _logger.info(f"Added {email} to mailing list {mailing_list.name} with {len(tag_ids)} tags")
            _logger.info(f"Mailing contact tag_ids: {mailing_contact.tag_ids}")
            return mailing_contact
            
        except Exception as e:
            _logger.error(f"Error adding contact to mailing list: {str(e)}")
            # Don't fail the lead creation if mailing list addition fails
            return False
    
    def _sync_tags_to_mailing_tags(self, crm_tags):
        """Convert CRM tags to partner categories (used by mailing.contact.tag_ids)"""
        tag_ids = []
        try:
            for tag in crm_tags:
                _logger.info(f"Processing CRM tag: {tag.name}")
                # Find or create matching res.partner.category
                partner_category = request.env['res.partner.category'].sudo().search([
                    ('name', '=', tag.name)
                ], limit=1)
                
                if not partner_category:
                    partner_category = request.env['res.partner.category'].sudo().create({
                        'name': tag.name
                    })
                    _logger.info(f"Created partner category: {tag.name} (ID: {partner_category.id})")
                else:
                    _logger.info(f"Found existing partner category: {tag.name} (ID: {partner_category.id})")
                
                tag_ids.append(partner_category.id)
            
            _logger.info(f"Total tag IDs to assign: {tag_ids}")
            return tag_ids
        except Exception as e:
            _logger.exception(f"Error syncing tags to partner categories: {str(e)}")
            return []
    
    def _send_lead_notification_email(self, partner, opportunity, contact_name, email_from, phone, description):
        """Send notification email to vCard owner when a new lead is submitted"""
        try:
            # Build email HTML body.
            # Attacker-controlled values (everything from the public /create_lead
            # POST) are HTML-escaped before interpolation so a hostile visitor
            # can't inject phishing HTML into the owner's notification email.
            name_safe = _html_escape(contact_name or '')
            email_safe = _html_escape(email_from or '')
            phone_safe = _html_escape(phone or 'Not provided')
            description_safe = _html_escape(description or 'No message provided')
            vcard_url = partner.website_full_url or '#'
            lead_url = f"{request.httprequest.host_url}web#id={opportunity.id}&model=crm.lead&view_type=form"

            email_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
                <div style="background-color: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h2 style="color: #333; margin-top: 0; border-bottom: 2px solid #457eb8; padding-bottom: 10px;">
                        🎉 New Lead Received!
                    </h2>

                    <p style="color: #666; font-size: 16px; line-height: 1.6;">
                        You've received a new lead submission on your Vinc Card:
                    </p>

                    <div style="background-color: #f8f9fa; border-left: 4px solid #457eb8; padding: 20px; margin: 20px 0; border-radius: 4px;">
                        <p style="margin: 8px 0;"><strong style="color: #333;">Name:</strong> <span style="color: #666;">{name_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Email:</strong> <span style="color: #666;">{email_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Phone:</strong> <span style="color: #666;">{phone_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Message:</strong></p>
                        <p style="margin: 8px 0; color: #666; white-space: pre-wrap;">{description_safe}</p>
                    </div>

                    <div style="margin: 30px 0; text-align: center;">
                        <a href="{lead_url}"
                           style="display: inline-block; background-color: #457eb8; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                            View Lead in CRM
                        </a>
                    </div>

                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 14px; color: #999;">
                        <p style="margin: 5px 0;">This lead was submitted through your Vinc Card: <a href="{vcard_url}" style="color: #457eb8;">{vcard_url}</a></p>
                        <p style="margin: 5px 0;">You can manage lead notifications in your Vinc Card settings.</p>
                    </div>
                </div>
            </div>
            """

            # Create mail message. Subject uses the escaped name to avoid
            # tricks like `"Name" <phish@evil>` in the header (escape neutralises
            # quotes into entities).
            mail_values = {
                'subject': f'New Lead: {name_safe} submitted a form on your Vinc Card',
                'body_html': email_body,
                'email_from': request.env['partner.vcard']._get_notification_email(user=request.env.user),
                'email_to': partner.email,
                'auto_delete': True,
            }
            
            # Queue the email (state='outgoing' by default). Odoo's built-in
            # "Mail: Send Email Queue" cron delivers it within a minute without
            # blocking this request on SMTP.
            mail = request.env['mail.mail'].sudo().create(mail_values)
            _logger.info(f"Lead notification email queued (id={mail.id}) for {partner.email}, new lead from {contact_name} ({email_from})")
            
        except Exception as e:
            _logger.error(f"Error sending lead notification email: {str(e)}", exc_info=True)
    
    def _send_intro_email(self, partner, contact_name, contact_email, opportunity):
        """Send introduction email to new lead with card owner CC'd and as Reply-To"""
        try:
            if not partner.intro_email_enabled or not contact_email:
                return
            
            # Prepare template variables (same pattern as leadback)
            base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
            vcard_url = partner.website_full_url or f"{base_url}/{partner.website_slug}" if partner.website_slug else base_url
            booking_url = partner.calendly_url or vcard_url
            
            # Extract first name from contact name
            first_name = contact_name.split()[0] if contact_name and ' ' in contact_name else (contact_name or 'there')
            
            template_vars = {
                'contact_name': contact_name or 'there',
                'first_name': first_name,
                'vcard_url': vcard_url,
                'booking_url': booking_url,
                'owner_name': partner.name or 'me',
                'owner_phone': partner.phone or partner.mobile or '',
                'owner_email': partner.email or '',
                'company_name': partner.company_name or '',
                'owner_title': partner.function or '',
            }
            
            # Get email template and process it
            email_template = partner.intro_email_template or "<p>Hi {contact_name},</p><p>Great meeting you today. I'm {owner_name} (cc'd), here's my info and how to reach me:</p><p><strong>Email:</strong> {owner_email}<br/><strong>Phone:</strong> {owner_phone}<br/><strong>My vCard:</strong> <a href='{vcard_url}'>{vcard_url}</a></p><p>Looking forward to connecting!<br/>{owner_name}</p>"
            
            # Process template with fallbacks and conditionals
            email_body_html = partner._process_template(email_template, template_vars, escape_html=True)
            
            # Import Markup to ensure HTML is properly rendered
            from markupsafe import Markup
            
            # Get the email template
            template = request.env.ref('qr_code_odoo.email_template_intro_email', raise_if_not_found=False)
            if not template:
                _logger.warning("Intro email template not found, skipping email")
                return
            
            # Get universal notification email
            notification_email = request.env['partner.vcard']._get_notification_email(user=request.env.user)
            
            # Prepare email subject
            email_subject = f'Great meeting you today - {partner.name}'
            
            # Send email using template (same pattern as referral email)
            # Pass Markup object to ensure HTML is not escaped
            # Override subject in email_values to ensure it renders correctly
            # force_send=False queues the mail for the cron; we still get the
            # mail_id so the CC/Reply-To headers can be patched below before
            # the cron picks it up. Response time stays sub-100ms.
            mail_id = template.sudo().with_context(
                contact_email=contact_email,
                owner_email=partner.email or '',
                email_body_html=Markup(email_body_html),
            ).send_mail(opportunity.id, force_send=False, email_values={
                'email_to': contact_email,
                'email_from': notification_email,
                'subject': email_subject,
            })
            
            # Update mail record to add CC and Reply-To headers
            if mail_id and partner.email:
                mail = request.env['mail.mail'].sudo().browse(mail_id)
                if mail.exists():
                    update_vals = {}
                    # Set email_cc if the field exists
                    if 'email_cc' in mail._fields:
                        update_vals['email_cc'] = partner.email
                    # Set reply_to if the field exists  
                    if 'reply_to' in mail._fields:
                        update_vals['reply_to'] = partner.email
                    # Update the mail record if we have fields to update
                    if update_vals:
                        mail.write(update_vals)
            
            # Log to opportunity if exists
            if opportunity:
                from markupsafe import Markup
                opportunity.message_post(
                    body=Markup(f"<p><strong>✓ Introduction Email Sent</strong><br/>To: {contact_email}<br/>CC: {partner.email or 'N/A'}</p>"),
                    subject="Introduction Email Sent"
                )
            
            _logger.info(f"Intro email sent to {contact_email} (CC: {partner.email}) for lead from {contact_name}. Mail ID: {mail_id}")
            
        except Exception as e:
            _logger.error(f"Error sending intro email: {str(e)}", exc_info=True)
    
    @http.route('/create_service_request', type='json', auth='public', methods=['POST'], csrf=False)
    def create_service_request(self, **kwargs):
        """Handle service request submissions"""
        _logger.info("create_service_request route called")

        try:
            # Load and log incoming data
            data = json.loads(request.httprequest.data)
            if data.get(HONEYPOT_FIELD):
                # Honeypot filled in: answer like a success so bots learn nothing.
                return {'status': 'success', 'message': 'Thank you!'}
            if _over_limit(request):
                return TOO_MANY
            _logger.info(f"Received service request data: {data}")

            # Extract tracking data from request (IP, user agent, geolocation, UTM params, etc.)
            tracking_data = _extract_tracking_data_from_request(request, data)
            _logger.info(f"=== SERVICE REQUEST TRACKING DATA ===")
            _logger.info(f"IP Address: {tracking_data.get('submission_ip')}")
            _logger.info(f"User Agent: {tracking_data.get('submission_user_agent')}")
            _logger.info(f"Country: {tracking_data.get('submission_country')}")
            _logger.info(f"City: {tracking_data.get('submission_city')}")
            _logger.info(f"UTM Source: {tracking_data.get('submission_utm_source')}")
            _logger.info(f"Referral Code: {tracking_data.get('submission_referral_code')}")

            # Extract data from the request
            contact_name = data.get('contact_name')
            email_from = data.get('email_from')
            phone = data.get('phone', '')
            partner_vcard_id = data.get('partner_id')
            service_id = data.get('service_id')
            service_name = data.get('service_name', '')
            service_description = data.get('service_description', '')
            notes = data.get('notes', '')
            custom_answers = data.get('custom_answers') or []

            _logger.info(f"=== SERVICE REQUEST SUBMISSION ===")
            _logger.info(f"Received partner_id: {partner_vcard_id}")

            # Validate required fields
            if not contact_name or not email_from or not partner_vcard_id or not service_id:
                _logger.error("Missing required fields in service request")
                return {'status': 'error', 'message': 'Missing required fields'}

            # Search for the partner by ID
            partner = request.env['partner.vcard'].sudo().search([('id', '=', partner_vcard_id)], limit=1)
            
            if not partner:
                _logger.error(f"Partner with ID {partner_vcard_id} not found")
                return {'status': 'error', 'message': 'Partner not found'}
            
            _logger.info(f"Partner found: {partner.exists()}")

            # Get the service
            service = request.env['partner.vcard.service'].sudo().search([
                ('id', '=', service_id),
                ('partner_id', '=', partner_vcard_id)
            ], limit=1)
            
            if not service:
                _logger.error(f"Service with ID {service_id} not found for partner {partner_vcard_id}")
                return {'status': 'error', 'message': 'Service not found'}

            # Build description for CRM lead
            lead_description = f"New lead for service: {service_name}\n\n"
            if notes:
                lead_description += f"Additional Details:\n{notes}\n"

            # Append custom question/answer summary if provided
            answers_summary_lines = []
            if isinstance(custom_answers, list):
                for qa in custom_answers:
                    label = qa.get('label') or qa.get('name') or ''
                    value = qa.get('value')
                    if isinstance(value, bool):
                        value = 'Yes' if value else 'No'
                    if label and (value or value == 0):
                        answers_summary_lines.append(f"{label}: {value}")

            answers_summary_text = ""
            if answers_summary_lines:
                answers_summary_text = "Custom Questions:\n" + "\n".join(f"- {line}" for line in answers_summary_lines)
                lead_description += "\n" + answers_summary_text + "\n"
            
            # Create CRM opportunity
            opportunity_vals = {
                'contact_name': contact_name,
                'email_from': email_from,
                'phone': phone,
                'partner_vcard_id': partner.id,
                'name': f"Service Request: {service_name}",
                'description': lead_description,
                'type': 'opportunity',
            }

            # Store structured summary of custom answers on the lead if available
            if answers_summary_text:
                opportunity_vals['service_request_answers'] = answers_summary_text
            
            # Add all tracking data to opportunity
            opportunity_vals.update(tracking_data)

            partner.sudo()._stamp_event_on_lead(
                opportunity_vals, contact_name, email_from, phone,
            )
            opportunity = request.env['crm.lead'].sudo().create(opportunity_vals)

            _logger.info(f"Service request opportunity created with tracking data: IP={tracking_data.get('submission_ip')}, Country={tracking_data.get('submission_country')}, UTM={tracking_data.get('submission_utm_source')}")

            _logger.info(f"Service request opportunity created with ID: {opportunity.id}")

            # Schedule follow-up reminder activities if enabled
            if partner.followup_reminders_enabled:
                try:
                    activities_created, reminders_queued = partner.sudo()._schedule_followup_reminders(opportunity, contact_name)
                    total = activities_created + reminders_queued
                    if total > 0:
                        _logger.info(
                            f"Follow-up reminders scheduled for service request opportunity {opportunity.id}: "
                            f"{activities_created} activity/ies created immediately, "
                            f"{reminders_queued} reminder(s) queued for cron processing"
                        )
                except Exception as e:
                    _logger.exception(f"Error scheduling follow-up reminders: {e}")
                    # Don't fail the service request creation if reminder scheduling fails
            
            # Final result
            _logger.info(f"=== FINAL SERVICE REQUEST RESULT ===")
            _logger.info(f"Opportunity ID: {opportunity.id}")

            # Add contact to email marketing if mailing list is configured
            if partner.mailing_list_id:
                try:
                    self._add_to_mailing_list(contact_name, email_from, partner, partner.lead_tag_ids)
                except Exception as e:
                    _logger.error(f"Error adding to mailing list: {str(e)}", exc_info=True)

            # Send notification email to vCard owner if enabled
            if partner.notify_on_new_lead and partner.email:
                try:
                    self._send_service_request_notification_email(
                        partner, opportunity, service, contact_name, email_from, phone, notes
                    )
                except Exception as e:
                    _logger.error(f"Error sending service request notification email: {str(e)}", exc_info=True)

            # Retrieve the custom thank you message from the service
            custom_message = service.thank_you_message or 'Thank you! Your service request has been sent. We\'ll be in touch shortly.'

            # Return success response
            return {
                'status': 'success',
                'message': custom_message,
                'opportunity_id': opportunity.id
            }

        except Exception as e:
            _logger.exception("Error in create_service_request")
            return {'status': 'error', 'message': f'Error processing request: {str(e)}'}

    @http.route('/service/questions', type='json', auth='public', methods=['POST'], csrf=False)
    def get_service_questions(self, **kwargs):
        """Return custom questions for a given service."""
        try:
            data = json.loads(request.httprequest.data or '{}')
            service_id = data.get('service_id')
            if not service_id:
                return {'status': 'error', 'message': 'Missing service_id'}

            service = request.env['partner.vcard.service'].sudo().browse(int(service_id))
            if not service or not service.exists():
                return {'status': 'error', 'message': 'Service not found'}

            questions = []
            for q in service.question_ids:
                questions.append({
                    'id': q.id,
                    'name': q.name,
                    'field_type': q.field_type,
                    'is_required': bool(q.is_required),
                    'options': q.options or '',
                })

            return {'status': 'ok', 'questions': questions}
        except Exception as e:
            _logger.exception("Error fetching service questions")
            return {'status': 'error', 'message': f'Error fetching questions: {str(e)}'}
    
    def _send_service_request_notification_email(self, partner, opportunity, service, contact_name, email_from, phone, notes):
        """Send notification email to vCard owner when a service request is submitted"""
        try:
            # Build email HTML body.
            # Attacker-controlled values (from /create_service_request POST) are
            # HTML-escaped to block phishing HTML injection into the owner's mail.
            service_name_safe = _html_escape(service.name or '')
            service_description_safe = _html_escape(service.description or '')
            name_safe = _html_escape(contact_name or '')
            email_safe = _html_escape(email_from or '')
            phone_safe = _html_escape(phone or 'Not provided')
            notes_safe = _html_escape(notes or 'No additional details provided')
            vcard_url = partner.website_full_url or '#'
            lead_url = f"{request.httprequest.host_url}web#id={opportunity.id}&model=crm.lead&view_type=form"

            email_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f5f5f5;">
                <div style="background-color: white; border-radius: 8px; padding: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h2 style="color: #333; margin-top: 0; border-bottom: 2px solid #457eb8; padding-bottom: 10px;">
                        🎯 New Service Request!
                    </h2>

                    <p style="color: #666; font-size: 16px; line-height: 1.6;">
                        You've received a new service request on your Vinc Card:
                    </p>

                    <div style="background-color: #f8f9fa; border-left: 4px solid #457eb8; padding: 20px; margin: 20px 0; border-radius: 4px;">
                        <p style="margin: 8px 0;"><strong style="color: #333;">Service:</strong> <span style="color: #666;">{service_name_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Service Description:</strong></p>
                        <p style="margin: 8px 0; color: #666; white-space: pre-wrap;">{service_description_safe}</p>
                        <p style="margin: 20px 0 8px 0; border-top: 1px solid #ddd; padding-top: 12px;"><strong style="color: #333;">Contact Information:</strong></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Name:</strong> <span style="color: #666;">{name_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Email:</strong> <span style="color: #666;">{email_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Phone:</strong> <span style="color: #666;">{phone_safe}</span></p>
                        <p style="margin: 8px 0;"><strong style="color: #333;">Additional Details:</strong></p>
                        <p style="margin: 8px 0; color: #666; white-space: pre-wrap;">{notes_safe}</p>
                    </div>

                    <div style="margin: 30px 0; text-align: center;">
                        <a href="{lead_url}"
                           style="display: inline-block; background-color: #457eb8; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                            View Lead in CRM
                        </a>
                    </div>

                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 14px; color: #999;">
                        <p style="margin: 5px 0;">This service request was submitted through your Vinc Card: <a href="{vcard_url}" style="color: #457eb8;">{vcard_url}</a></p>
                        <p style="margin: 5px 0;">You can manage service request notifications in your Vinc Card settings.</p>
                    </div>
                </div>
            </div>
            """

            # Subject uses the escaped service name + contact name.
            mail_values = {
                'subject': f'New Service Request: {service_name_safe} - {name_safe}',
                'body_html': email_body,
                'email_from': request.env['partner.vcard']._get_notification_email(user=request.env.user),
                'email_to': partner.email,
                'auto_delete': True,
            }
            
            # Send the email
            mail = request.env['mail.mail'].sudo().create(mail_values)
            mail.send()
            _logger.info(f"Service request notification email sent to {partner.email} for service '{service.name}' from {contact_name} ({email_from})")
            
        except Exception as e:
            _logger.error(f"Error sending service request notification email: {str(e)}", exc_info=True)

class VCardFormController(http.Controller):

    @http.route(['/get-started/translate-view'], type='http', auth='public', website=True)
    def get_started_translate_view(self, **kwargs):
        """Special route for translating the form - shows all steps for easy translation"""
        # Check if user is logged in
        if request.env.user._is_public():
            return request.redirect('/web/login?redirect=/get-started/translate-view')
        
        # Render the actual form template with all steps visible
        countries = request.env['res.country'].sudo().search([], order='name')
        states = request.env['res.country.state'].sudo().search([], order='name')
        
        return request.render('qr_code_odoo.vcard_form_page', {
            'countries': countries,
            'states': states,
            'default_name': 'John Doe',
            'default_email': 'john@example.com',
            'default_company': 'Example Company',
            'show_all_steps': True,
        })

    @http.route(['/get-started'], type='http', auth='public', website=True)
    def get_started_form_page(self, flow=None, **kwargs):
        # Check if user is authenticated by checking session UID
        if not request.session.uid or request.session.uid == 1:  # 1 is public user
            return request.redirect('/web/login')

        # Get the actual user from the session
        user = request.env['res.users'].sudo().browse(request.session.uid)
        if not user.exists():
            return request.redirect('/web/login')

        # Allow users to create multiple vCards - no restriction
        countries = request.env['res.country'].sudo().search([], order='name')
        states = request.env['res.country.state'].sudo().search([], order='name')

        # Detect "completing a bulk-onboarded card" flow. Recipients arrive
        # here via /bulk-onboard/complete-vcard → redirect with flow=bulk-activate.
        # When in this mode we prefill EVERY input from the admin-created card
        # and the submit handler UPDATEs instead of CREATEs (see handle_form_submission).
        bulk_rep = None
        bulk_vcard = None
        if flow == 'bulk-activate':
            bulk_rep = request.env['bulk.onboarding.rep'].sudo().search([
                ('user_id', '=', user.id),
            ], limit=1)
            if bulk_rep and bulk_rep.vcard_id:
                bulk_vcard = bulk_rep.vcard_id

        # Prefill defaults
        default_name = ''
        default_email = ''
        default_company = ''
        default_phone = ''
        default_mobile = ''
        default_function = ''
        default_about = ''
        default_slug = ''
        default_street = ''
        default_street2 = ''
        default_city = ''
        default_zip = ''
        default_country_id = ''
        default_state_id = ''
        default_secondary_color = '#2D5BFF'
        default_website_template = 'modern'
        default_linkedin = ''
        default_linkedin_company = ''
        default_twitter = ''
        default_twitter_company = ''
        default_facebook = ''
        default_facebook_company = ''
        default_instagram = ''
        default_instagram_company = ''
        default_whatsapp = ''
        default_youtube = ''
        default_calendly = ''

        try:
            if bulk_vcard:
                # Bulk-onboarded recipients: every field prefills from the
                # admin-created card. They edit the ones they want to change
                # and /vcard/submit updates the existing record in place.
                default_name = bulk_vcard.name or user.name or ''
                default_email = bulk_vcard.email or user.login or ''
                default_company = bulk_vcard.company_name or ''
                default_phone = bulk_vcard.phone or ''
                default_mobile = bulk_vcard.mobile or ''
                default_function = bulk_vcard.function or ''
                # Strip HTML from the About field for the textarea display.
                if bulk_vcard.about:
                    import re as _re
                    from html import unescape as _unescape
                    default_about = _unescape(_re.sub(r'<[^>]+>', '', bulk_vcard.about))
                default_slug = bulk_vcard.website_slug or ''
                default_street = bulk_vcard.street or ''
                default_street2 = bulk_vcard.street2 or ''
                default_city = bulk_vcard.city or ''
                default_zip = bulk_vcard.zip or ''
                default_country_id = bulk_vcard.country_id.id if bulk_vcard.country_id else ''
                default_state_id = bulk_vcard.state_id.id if bulk_vcard.state_id else ''
                default_secondary_color = bulk_vcard.secondary_color or '#2D5BFF'
                default_website_template = bulk_vcard.website_template or 'modern'
                default_linkedin = bulk_vcard.linkedin_url or ''
                default_linkedin_company = bulk_vcard.linkedin_url_company or ''
                default_twitter = bulk_vcard.twitter_url or ''
                default_twitter_company = bulk_vcard.twitter_url_company or ''
                default_facebook = bulk_vcard.facebook_url or ''
                default_facebook_company = bulk_vcard.facebook_url_company or ''
                default_instagram = bulk_vcard.instagram_url or ''
                default_instagram_company = bulk_vcard.instagram_url_company or ''
                default_whatsapp = bulk_vcard.whatsapp_url or ''
                default_youtube = bulk_vcard.youtube_url or ''
                default_calendly = bulk_vcard.calendly_url or ''
            else:
                # Normal /get-started: prefill name / email from the user and
                # phone / mobile / function from their linked partner record.
                default_name = user.name or ''
                default_email = getattr(user, 'email', None) or getattr(user, 'login', '') or ''
                if hasattr(user, 'company_id') and user.company_id:
                    company = request.env['res.company'].sudo().browse(user.company_id.id)
                    if company.exists() and company.name:
                        default_company = company.name
                partner = getattr(user, 'partner_id', None)
                if partner and partner.exists():
                    default_phone = partner.phone or ''
                    default_mobile = partner.mobile or ''
                    default_function = partner.function or ''
        except Exception as e:
            _logger.warning(f"Error accessing prefill fields: {e}")

        # Get base URL for vCard URL prefix
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        base_url_display = base_url.replace('http://', '').replace('https://', '').rstrip('/')

        return request.render('qr_code_odoo.vcard_form_page', {
            'countries': countries,
            'states': states,
            'default_name': default_name,
            'default_email': default_email,
            'default_company': default_company,
            'default_phone': default_phone,
            'default_mobile': default_mobile,
            'default_function': default_function,
            'default_about': default_about,
            'default_slug': default_slug,
            'default_street': default_street,
            'default_street2': default_street2,
            'default_city': default_city,
            'default_zip': default_zip,
            'default_country_id': default_country_id,
            'default_state_id': default_state_id,
            'default_secondary_color': default_secondary_color,
            'default_website_template': default_website_template,
            'default_linkedin': default_linkedin,
            'default_linkedin_company': default_linkedin_company,
            'default_twitter': default_twitter,
            'default_twitter_company': default_twitter_company,
            'default_facebook': default_facebook,
            'default_facebook_company': default_facebook_company,
            'default_instagram': default_instagram,
            'default_instagram_company': default_instagram_company,
            'default_whatsapp': default_whatsapp,
            'default_youtube': default_youtube,
            'default_calendly': default_calendly,
            'base_url_display': base_url_display,
            'max_websites': 999999,  # Unlimited
            'max_videos': 999999,    # Unlimited
            'flow': flow or '',
            'bulk_mode': bool(bulk_vcard),
        })

    @http.route(['/vcard/check_slug_availability'], type='json', auth='user', methods=['POST'], csrf=False)
    def check_slug_availability(self, **kwargs):
        """Check if a website slug is available"""
        try:
            # For type='json' routes, Odoo automatically parses JSON into request.jsonrequest
            # Also check kwargs as fallback
            data = request.jsonrequest if hasattr(request, 'jsonrequest') and request.jsonrequest else kwargs
            
            # Debug logging
            _logger.info(f"Slug check request - jsonrequest: {request.jsonrequest if hasattr(request, 'jsonrequest') else 'N/A'}, kwargs: {kwargs}")
            
            # Try multiple ways to get the slug
            slug = ''
            if isinstance(data, dict):
                slug = data.get('slug', '').strip()
            elif isinstance(request.jsonrequest, dict):
                slug = request.jsonrequest.get('slug', '').strip()
            elif kwargs:
                slug = kwargs.get('slug', '').strip()
            
            # If still no slug, try to parse from raw request body
            if not slug and hasattr(request, 'httprequest') and request.httprequest.data:
                try:
                    import json
                    raw_data = json.loads(request.httprequest.data.decode('utf-8'))
                    if isinstance(raw_data, dict):
                        slug = raw_data.get('slug', '').strip()
                except (ValueError, UnicodeDecodeError, AttributeError):
                    pass
            
            _logger.info(f"Extracted slug: '{slug}'")
            
            if not slug:
                _logger.warning("No slug provided in request")
                return {'available': False, 'error': 'No slug provided'}
            
            # Use ORM to check vcards, but EXCLUDE preview vCards (they're temporary)
            # This is safer than raw SQL and avoids tuple unpacking issues
            existing_vcard = request.env['partner.vcard'].sudo().search([
                ('website_slug', '=', slug),
                ('website_slug', 'not like', 'preview-%')
            ], limit=1)
            
            _logger.info(f"Slug availability check for '{slug}' (ORM, excluding previews): exists={bool(existing_vcard)}")
            
            if existing_vcard:
                _logger.info(f"  Found existing vCard: ID={existing_vcard.id}, Name={existing_vcard.name}, Slug={existing_vcard.website_slug}")
                
                # Slug is taken, suggest an alternative using ORM (also exclude previews)
                counter = 2
                suggestion = f"{slug}-{counter}"
                
                # Check suggestions using ORM too (excluding previews)
                while counter < 100:  # Safety limit
                    suggestion_exists = request.env['partner.vcard'].sudo().search([
                        ('website_slug', '=', suggestion),
                        ('website_slug', 'not like', 'preview-%')
                    ], limit=1)
                    if not suggestion_exists:
                        break
                    counter += 1
                    suggestion = f"{slug}-{counter}"
                
                _logger.info(f"  Suggesting alternative: {suggestion} (all existing slugs checked via ORM, excluding previews)")
                
                return {
                    'available': False,
                    'suggestion': suggestion
                }
            else:
                # Slug is available
                _logger.info(f"  Slug '{slug}' is available")
                return {
                    'available': True,
                    'slug': slug
                }
        
        except Exception as e:
            _logger.error("Error checking slug availability: %s", e)
            return {
                'available': False,
                'error': str(e)
            }

    @http.route(['/vcard/preview'], type='json', auth='user', methods=['POST'], csrf=False)
    def generate_preview(self, **kwargs):
        """Generate a live preview of the vCard website based on form data"""
        try:
            # Get form data from request
            # For type='json' routes, Odoo automatically parses JSON into request.jsonrequest
            if hasattr(request, 'jsonrequest') and request.jsonrequest:
                data = request.jsonrequest
            elif hasattr(request, 'httprequest') and request.httprequest.data:
                try:
                    raw_data = request.httprequest.data
                    if isinstance(raw_data, bytes):
                        data = json.loads(raw_data.decode('utf-8'))
                    else:
                        data = json.loads(raw_data)
                except (json.JSONDecodeError, AttributeError, UnicodeDecodeError):
                    data = kwargs
            else:
                data = kwargs
            
            # Get or create a preview vCard for this user
            user = request.env.user
            
            # Look for existing preview vCard (marked with a special slug)
            preview_slug = f'preview-{user.id}'
            preview_vcard = request.env['partner.vcard'].sudo().search([
                ('website_slug', '=', preview_slug)
            ], limit=1)

            # ---- Fast-path: short-circuit when inputs hash matches existing preview ----
            # All hash inputs derive from `data` alone (no DB reads), so this branch
            # can decide entirely from the request payload + the stored hash.
            try:
                _ml_name_raw = (data.get('mailing_list_name') or '').strip()
                _effective_show_form = bool(data.get('show_form')) and bool(_ml_name_raw)
                _channel_codes_in = data.get('leadback_channels') or []
                if not isinstance(_channel_codes_in, list):
                    _channel_codes_in = [_channel_codes_in]
                _websites_in = list(zip(
                    data.get('website_url') if isinstance(data.get('website_url'), list) else ([data.get('website_url')] if data.get('website_url') else []),
                    data.get('website_name') if isinstance(data.get('website_name'), list) else ([data.get('website_name')] if data.get('website_name') else []),
                    data.get('website_color') if isinstance(data.get('website_color'), list) else ([data.get('website_color')] if data.get('website_color') else []),
                ))
                _videos_in = list(zip(
                    data.get('video_url') if isinstance(data.get('video_url'), list) else ([data.get('video_url')] if data.get('video_url') else []),
                    data.get('video_name') if isinstance(data.get('video_name'), list) else ([data.get('video_name')] if data.get('video_name') else []),
                ))
                _img_b64 = data.get('image_base64')
                _bnr_b64 = data.get('banner_image_base64')
                _image_token = hashlib.sha256(_img_b64.encode('utf-8') if isinstance(_img_b64, str) else _img_b64).hexdigest()[:16] if _img_b64 else 'DEFAULT'
                _banner_token = hashlib.sha256(_bnr_b64.encode('utf-8') if isinstance(_bnr_b64, str) else _bnr_b64).hexdigest()[:16] if _bnr_b64 else 'DEFAULT'
                incoming_hash = _compute_preview_hash(
                    data, _effective_show_form, _ml_name_raw, _channel_codes_in,
                    _websites_in, _videos_in, _image_token, _banner_token,
                )
            except Exception as _e:
                _logger.warning(f"Preview hash compute failed, falling through to slow path: {_e}", exc_info=True)
                incoming_hash = None

            if incoming_hash and preview_vcard and preview_vcard.preview_template_hash == incoming_hash:
                website_page = request.env['website.page'].sudo().search([
                    ('url', '=', f'/{preview_slug}')
                ], limit=1)
                if website_page:
                    base_url = request.httprequest.host_url.rstrip('/')
                    preview_url = f'{base_url}/{preview_slug}?preview=1'
                    _logger.info(f"Preview fast-path hit for vCard {preview_vcard.id} (slug: {preview_slug})")
                    return {
                        'success': True,
                        'preview_url': preview_url,
                        'vcard_id': preview_vcard.id,
                        'website_page_id': website_page.id,
                    }
                _logger.info(f"Preview hash matched but website.page missing for slug '{preview_slug}', falling through to slow path")
            # ---- end fast-path ----

            # Slow-path timing instrumentation. Sections logged at end as a single
            # comma-separated key=ms list so it greps cleanly.
            import time
            _t = {}
            _t['t_start'] = time.monotonic()

            # Prepare values from form data
            vals = {
                'name': data.get('name') or 'Your Name',
                'company_name': data.get('company_name') or 'Your Company',
                'street': data.get('street', ''),
                'street2': data.get('street2', ''),
                'city': data.get('city', ''),
                'zip': data.get('zip', ''),
                'function': data.get('function', ''),
                'phone': data.get('phone', ''),
                'mobile': data.get('mobile', ''),
                'email': data.get('email') or 'email@example.com',
                'website': data.get('website', ''),
                'calendly_url': data.get('calendly_url', ''),
                'website_slug': preview_slug,
                'about': data.get('about') or 'Tell people about yourself...',
                'primary_color': data.get('primary_color') or '#ffffff',  # Default to white for backgrounds
                'secondary_color': data.get('secondary_color') or '#4C75A3',  # Default to Vinc blue
                'website_template': data.get('website_template', 'modern'),
                'whatsapp_url': data.get('whatsapp_url', ''),
                'linkedin_url': data.get('linkedin_url', ''),
                'linkedin_url_company': data.get('linkedin_url_company', ''),
                'youtube_url': data.get('youtube_url', ''),
                'facebook_url': data.get('facebook_url', ''),
                'facebook_url_company': data.get('facebook_url_company', ''),
                'lead_button_label': data.get('lead_button_label', ''),
                'form_thank_you_message': data.get('form_thank_you_message', ''),
                'show_form': data.get('show_form', False),
                'preview_template_hash': incoming_hash or False,
            }
            
            _t['vals_built'] = time.monotonic()

            # Handle mailing list if show_form is enabled
            if vals.get('show_form'):
                mailing_list_name = (data.get('mailing_list_name') or '').strip()
                if mailing_list_name:
                    # Find or create mailing list
                    MailingList = request.env['mailing.list'].sudo()
                    mailing_list = MailingList.search([
                        ('name', '=ilike', mailing_list_name)
                    ], limit=1)
                    
                    if not mailing_list:
                        mailing_list = MailingList.create({
                            'name': mailing_list_name,
                            'is_public': True
                        })
                        _logger.info(f"Created preview mailing list '{mailing_list_name}' (ID: {mailing_list.id})")
                    else:
                        _logger.info(f"Using existing mailing list '{mailing_list.name}' (ID: {mailing_list.id})")
                    
                    # Assign to vals to satisfy model constraint
                    vals['mailing_list_id'] = mailing_list.id
                else:
                    # If show_form is enabled but no mailing list name, disable show_form for preview
                    # Don't fail - just disable the form for preview purposes
                    vals['show_form'] = False
                    _logger.info(f"show_form enabled but no mailing_list_name provided, disabling show_form for preview (non-blocking)")
            
            _t['ml_resolved'] = time.monotonic()

            # Handle image if provided (base64 encoded)
            if data.get('image_base64'):
                vals['image_url'] = data.get('image_base64')
            else:
                default_profile = _cached_default_image(request.env['partner.vcard'], 'profile')
                if default_profile:
                    vals['image_url'] = default_profile

            # Handle banner image if provided (base64 encoded)
            if data.get('banner_image_base64'):
                vals['banner_image'] = data.get('banner_image_base64')
            else:
                default_banner = _cached_default_image(request.env['partner.vcard'], 'banner')
                if default_banner:
                    vals['banner_image'] = default_banner
            
            # Handle extra features (checkboxes return boolean or 'yes' string)
            vals['notify_on_new_lead'] = data.get('notify_on_new_lead') == 'yes' or data.get('notify_on_new_lead') == True or data.get('notify_on_new_lead') is True
            vals['intro_email_enabled'] = data.get('intro_email_enabled') == 'yes' or data.get('intro_email_enabled') == True or data.get('intro_email_enabled') is True
            vals['enable_instant_leadback'] = data.get('enable_instant_leadback') == 'yes' or data.get('enable_instant_leadback') == True or data.get('enable_instant_leadback') is True
            vals['leadback_send_email'] = data.get('leadback_send_email') == 'yes' or data.get('leadback_send_email') == True or data.get('leadback_send_email') is True
            vals['leadback_enable_messaging'] = data.get('leadback_enable_messaging') == 'yes' or data.get('leadback_enable_messaging') == True or data.get('leadback_enable_messaging') is True
            vals['show_reviews'] = data.get('show_reviews') == 'yes' or data.get('show_reviews') == True or data.get('show_reviews') is True
            
            # Handle leadback channels
            if data.get('leadback_channels'):
                channel_ids = []
                channel_codes = data.get('leadback_channels') if isinstance(data.get('leadback_channels'), list) else [data.get('leadback_channels')]
                for code in channel_codes:
                    channel = request.env['leadback.messaging.channel'].sudo().search([('code', '=', code)], limit=1)
                    if channel:
                        channel_ids.append(channel.id)
                if channel_ids:
                    vals['leadback_channels'] = [(6, 0, channel_ids)]
            
            # Handle websites and videos for preview
            website_urls = data.get('website_url', []) if isinstance(data.get('website_url'), list) else (data.get('website_url') and [data.get('website_url')] or [])
            website_names = data.get('website_name', []) if isinstance(data.get('website_name'), list) else (data.get('website_name') and [data.get('website_name')] or [])
            website_colors = data.get('website_color', []) if isinstance(data.get('website_color'), list) else (data.get('website_color') and [data.get('website_color')] or [])
            
            video_urls = data.get('video_url', []) if isinstance(data.get('video_url'), list) else (data.get('video_url') and [data.get('video_url')] or [])
            video_names = data.get('video_name', []) if isinstance(data.get('video_name'), list) else (data.get('video_name') and [data.get('video_name')] or [])
            
            _t['channels_resolved'] = time.monotonic()

            # Create or update preview vCard with retry logic for concurrent updates
            import psycopg2
            max_retries = 3
            retry_count = 0
            vcard = None
            
            while retry_count < max_retries:
                try:
                    # Use savepoint for each attempt to isolate failures
                    with request.env.cr.savepoint():
                        if preview_vcard:
                            preview_vcard.sudo().write(vals)
                            vcard = preview_vcard
                        else:
                            vcard = request.env['partner.vcard'].sudo().with_context(skip_vcard_limit_check=True).create(vals)
                    break  # Success, exit retry loop
                except psycopg2.errors.SerializationFailure as e:
                    retry_count += 1
                    request.env.cr.rollback()  # Rollback the failed transaction
                    
                    if retry_count >= max_retries:
                        _logger.warning(f"Failed to update preview vCard after {max_retries} retries due to concurrent updates")
                        # Last attempt: ensure clean transaction state
                        request.env.cr.rollback()
                        # Refresh the preview vCard to get latest state
                        preview_vcard = request.env['partner.vcard'].sudo().search([
                            ('website_slug', '=', preview_slug)
                        ], limit=1)
                        try:
                            if preview_vcard:
                                preview_vcard.sudo().write(vals)
                                vcard = preview_vcard
                            else:
                                vcard = request.env['partner.vcard'].sudo().with_context(skip_vcard_limit_check=True).create(vals)
                            break
                        except Exception as final_e:
                            _logger.error(f"Final retry attempt failed: {final_e}", exc_info=True)
                            return {'success': False, 'error': 'Failed to create/update preview due to concurrent access. Please try again.'}
                    else:
                        _logger.info(f"Retrying preview vCard update (attempt {retry_count + 1}/{max_retries}) due to concurrent update")
                        # Exponential backoff with jitter
                        time.sleep(0.1 * (2 ** retry_count) + (time.time() % 0.1))
                        # Refresh the preview vCard to get latest state
                        preview_vcard = request.env['partner.vcard'].sudo().search([
                            ('website_slug', '=', preview_slug)
                        ], limit=1)
                except Exception as e:
                    # For other errors, don't retry
                    _logger.error(f"Error updating preview vCard: {e}", exc_info=True)
                    request.env.cr.rollback()
                    return {'success': False, 'error': str(e)}
            
            if not vcard:
                _logger.error(f"Failed to create/update preview vCard for slug '{preview_slug}' after {max_retries} retries.")
                return {'success': False, 'error': 'Failed to create/update preview due to concurrent access. Please try again.'}
            
            _t['vcard_written'] = time.monotonic()

            # Ensure banner attachment is created/updated if banner_image was set (including default)
            if vals.get('banner_image'):
                vcard.sudo()._update_banner_attachment_if_image_changed()
            
            # Handle websites data for preview
            if website_urls and website_urls[0]:
                # Delete existing websites for this preview vCard
                request.env['partner.vcard.website'].sudo().search([
                    ('partner_id', '=', vcard.id)
                ]).unlink()
                
                # Get secondary color as default
                secondary_color = vcard.secondary_color or '#000000'
                
                # Create new websites
                website_data = []
                for i, url in enumerate(website_urls):
                    if url and url.strip():
                        # Use provided color, or default to secondary color
                        button_color = website_colors[i] if i < len(website_colors) and website_colors[i] and website_colors[i].strip() else secondary_color
                        website_data.append({
                            'partner_id': vcard.id,
                            'website_url': url.strip(),
                            'name': website_names[i] if i < len(website_names) and website_names[i] else 'Website',
                            'button_color': button_color
                        })
                
                if website_data:
                    request.env['partner.vcard.website'].sudo().create(website_data)
            
            # Handle videos data for preview
            if video_urls and video_urls[0]:
                # Delete existing videos for this preview vCard
                request.env['partner.vcard.videos'].sudo().search([
                    ('partner_id', '=', vcard.id)
                ]).unlink()
                
                # Create new videos
                video_data = []
                for i, url in enumerate(video_urls):
                    if url and url.strip():
                        video_data.append({
                            'partner_id': vcard.id,
                            'video_url': url.strip(),
                            'name': video_names[i] if i < len(video_names) and video_names[i] else 'Video'
                        })
                
                if video_data:
                    request.env['partner.vcard.videos'].sudo().create(video_data)
            
            _t['children_written'] = time.monotonic()

            # Generate the website page (optimized for preview - single commit at end)
            if hasattr(vcard, 'action_generate_website_page'):
                try:
                    vcard.action_generate_website_page()
                    _logger.info(f"Preview website generated successfully for vCard {vcard.id} (slug: {preview_slug})")
                except Exception as e:
                    _logger.error(f"Error generating preview website: {str(e)}", exc_info=True)
                    # Don't return error - just log it and continue (suppress errors in preview)
                    pass
            
            _t['page_generated'] = time.monotonic()

            # Single commit at the end of the slow path. action_generate_website_page
            # creates/updates the website.page with is_published=True, so the prior
            # post-commit recovery branches were dead in practice.
            website_page = request.env['website.page'].sudo().search([
                ('url', '=', f'/{preview_slug}')
            ], limit=1)
            request.env.cr.commit()

            _t['committed'] = time.monotonic()

            base_url = request.httprequest.host_url.rstrip('/')
            preview_url = f'{base_url}/{preview_slug}?preview=1'

            # Emit timing breakdown as a single greppable line.
            def _ms(a, b): return f"{(_t[b] - _t[a]) * 1000:.0f}"
            _logger.info(
                "Preview slow-path timing ms: "
                f"vals={_ms('t_start', 'vals_built')}, "
                f"ml={_ms('vals_built', 'ml_resolved')}, "
                f"channels={_ms('ml_resolved', 'channels_resolved')}, "
                f"vcard_write={_ms('channels_resolved', 'vcard_written')}, "
                f"children={_ms('vcard_written', 'children_written')}, "
                f"page_gen={_ms('children_written', 'page_generated')}, "
                f"commit={_ms('page_generated', 'committed')}, "
                f"total={_ms('t_start', 'committed')}"
            )

            if not website_page:
                _logger.warning(f"Website page not found for preview slug: {preview_slug}, returning URL anyway")
                return {'success': True, 'preview_url': preview_url}

            _logger.info(f"Preview slow-path generated for vCard {vcard.id} (slug: {preview_slug})")
            return {
                'success': True,
                'preview_url': preview_url,
                'vcard_id': vcard.id,
                'website_page_id': website_page.id,
            }
            
        except Exception as e:
            _logger.error(f"Error generating preview: {str(e)}", exc_info=True)
            return {'success': False, 'error': str(e)}
    
    @http.route(['/vcard/submit'], type='http', auth='public', website=True, csrf=True)
    def handle_form_submission(self, **post):
        # Check if user is authenticated
        if not request.env.user or request.env.user._is_public():
            return request.redirect('/web/login')

        # Detect the "completing a bulk-onboarded invited card" flow.
        # The /get-started template carries `flow=bulk-activate` as a hidden
        # input when the admin-pre-filled card is being completed by the
        # recipient. We UPDATE that card instead of CREATE-ing a new one, and
        # skip the slug uniqueness check (the slug already belongs to them).
        flow = (post.get('flow') or '').strip()
        bulk_vcard = None
        bulk_rep = None
        if flow == 'bulk-activate':
            bulk_rep = request.env['bulk.onboarding.rep'].sudo().search([
                ('user_id', '=', request.env.user.id),
            ], limit=1)
            if bulk_rep and bulk_rep.vcard_id:
                bulk_vcard = bulk_rep.vcard_id

        # Validate required fields
        required_fields = {
            'name': 'Full Name',
            'email': 'Email Address', 
            'website_slug': 'Vinc URL',
            'about': 'About You',
            'secondary_color': 'Brand Color'
        }
        
        # Validate image file if provided (optional - default will be used if not provided)
        image_file = request.httprequest.files.get('image_url')
        if image_file and image_file.filename:
            # Validate image file type
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
            import os
            file_extension = os.path.splitext(image_file.filename.lower())[1]
            if file_extension not in allowed_extensions:
                error_message = f"Please upload a valid image file (JPG, PNG, GIF, BMP, or WebP). Uploaded file: {image_file.filename}"
                _logger.warning(f"Profile photo validation failed: Invalid file type - {file_extension}")
                return request.render('qr_code_odoo.vcard_form_page', {
                    'error': error_message,
                    'countries': request.env['res.country'].sudo().search([]),
                    'states': request.env['res.country.state'].sudo().search([]),
                })
            
            # Validate file size (max 5MB)
            image_file.seek(0, 2)  # Seek to end
            file_size = image_file.tell()
            image_file.seek(0)  # Reset to beginning
            max_size = 5 * 1024 * 1024  # 5MB in bytes
            if file_size > max_size:
                error_message = f"Image file is too large. Maximum size is 5MB. Your file is {file_size / (1024*1024):.1f}MB"
                _logger.warning(f"Profile photo validation failed: File too large - {file_size} bytes")
                return request.render('qr_code_odoo.vcard_form_page', {
                    'error': error_message,
                    'countries': request.env['res.country'].sudo().search([]),
                    'states': request.env['res.country.state'].sudo().search([]),
                })
        
        missing_fields = []
        for field, label in required_fields.items():
            if not post.get(field) or not post.get(field).strip():
                missing_fields.append(label)
        
        if missing_fields:
            error_message = f"Please fill in the following required fields: {', '.join(missing_fields)}"
            _logger.warning(f"Form validation failed: {error_message}")
            return request.render('qr_code_odoo.vcard_form_page', {
                'error': error_message,
                'countries': request.env['res.country'].sudo().search([]),
                'states': request.env['res.country.state'].sudo().search([]),
            })
        
        # Additional validation for email format
        import re
        email = post.get('email', '').strip()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            error_message = "Please enter a valid email address"
            _logger.warning(f"Email validation failed: {email}")
            return request.render('qr_code_odoo.vcard_form_page', {
                'error': error_message,
                'countries': request.env['res.country'].sudo().search([]),
                'states': request.env['res.country.state'].sudo().search([]),
            })
        
        # Additional validation for website_slug format (alphanumeric and hyphens only)
        website_slug = post.get('website_slug', '').strip()
        if not re.match(r'^[a-zA-Z0-9-]+$', website_slug):
            error_message = "vCard URL can only contain letters, numbers, and hyphens"
            _logger.warning(f"Website slug validation failed: {website_slug}")
            return request.render('qr_code_odoo.vcard_form_page', {
                'error': error_message,
                'countries': request.env['res.country'].sudo().search([]),
                'states': request.env['res.country.state'].sudo().search([]),
            })
        
        # Check if website_slug is already taken. In bulk-activate mode, the
        # slug can legitimately already belong to the recipient's own card —
        # only flag a collision if it belongs to a *different* card.
        existing_partner = request.env['partner.vcard'].sudo().search([
            ('website_slug', '=', website_slug)
        ], limit=1)
        if existing_partner and (not bulk_vcard or existing_partner.id != bulk_vcard.id):
            error_message = f"The vCard URL '{website_slug}' is already taken. Please choose a different one."
            _logger.warning(f"Website slug already exists: {website_slug}")
            return request.render('qr_code_odoo.vcard_form_page', {
                'error': error_message,
                'countries': request.env['res.country'].sudo().search([]),
                'states': request.env['res.country.state'].sudo().search([]),
            })
        
        vals = {
            'name': post.get('name'),
            'company_name': post.get('company_name', ''),  # Optional now
            'street': post.get('street'),
            'street2': post.get('street2'),
            'city': post.get('city'),
            'zip': post.get('zip'),
            'function': post.get('function'),
            'phone': post.get('phone'),
            'mobile': post.get('mobile'),
            'email': post.get('email'),
            'website': post.get('website'),
            'calendly_url': post.get('calendly_url'),
            'website_slug': post.get('website_slug'),
            'about': post.get('about'),
            'primary_color': post.get('primary_color', '#ffffff'),  # Default to white for backgrounds
            'secondary_color': post.get('secondary_color', '#4C75A3'),  # Default to Vinc blue
            'website_template': post.get('website_template', 'classic'),  # Default to classic if not provided
            'whatsapp_url': post.get('whatsapp_url'),
            'linkedin_url': post.get('linkedin_url'),
            'linkedin_url_company': post.get('linkedin_url_company'),
            'youtube_url': post.get('youtube_url'),
            'facebook_url': post.get('facebook_url'),
            'facebook_url_company': post.get('facebook_url_company'),
            'lead_button_label': post.get('lead_button_label'),
            'form_thank_you_message': post.get('form_thank_you_message'),
            'show_form': post.get('show_form') == 'yes',
            'notify_on_new_lead': post.get('notify_on_new_lead') == 'yes',
            'intro_email_enabled': post.get('intro_email_enabled') == 'yes',
            'enable_instant_leadback': post.get('enable_instant_leadback') == 'yes',
            'leadback_send_email': post.get('leadback_send_email') == 'yes',
            'leadback_enable_messaging': post.get('leadback_enable_messaging') == 'yes',
            'show_reviews': post.get('show_reviews') == 'yes',
        }
        
        # Handle leadback channels
        # In Odoo, form data comes as a dict, not a request object
        leadback_channels = post.get('leadback_channels[]')
        if isinstance(leadback_channels, list):
            pass  # Already a list
        elif leadback_channels:
            leadback_channels = [leadback_channels]  # Convert single value to list
        else:
            leadback_channels = []
        
        if leadback_channels:
            channel_ids = []
            for code in leadback_channels:
                channel = request.env['leadback.messaging.channel'].sudo().search([('code', '=', code)], limit=1)
                if channel:
                    channel_ids.append(channel.id)
            if channel_ids:
                vals['leadback_channels'] = [(6, 0, channel_ids)]
        
        # When lead form is enabled, ensure a mailing list exists and assign it
        try:
            if vals.get('show_form'):
                mailing_list_name = (post.get('mailing_list_name') or '').strip()
                if not mailing_list_name:
                    error_message = "Please provide a Mailing List Name when lead collection is enabled."
                    _logger.warning("Lead form enabled but no mailing_list_name provided")
                    return request.render('qr_code_odoo.vcard_form_page', {
                        'error': error_message,
                        'countries': request.env['res.country'].sudo().search([]),
                        'states': request.env['res.country.state'].sudo().search([]),
                    })

                # Find or create mailing list
                MailingList = request.env['mailing.list'].sudo()
                mailing_list = MailingList.search([
                    ('name', '=ilike', mailing_list_name)
                ], limit=1)

                if not mailing_list:
                    mailing_list = MailingList.create({
                        'name': mailing_list_name,
                        'is_public': True
                    })
                    _logger.info(f"Created mailing list '{mailing_list_name}' (ID: {mailing_list.id})")
                else:
                    _logger.info(f"Using existing mailing list '{mailing_list.name}' (ID: {mailing_list.id})")

                # Assign to vals to satisfy model constraint
                vals['mailing_list_id'] = mailing_list.id
        except Exception as e:
            _logger.error(f"Error preparing mailing list: {e}")
            # Fail gracefully with message on the form rather than 500
            return request.render('qr_code_odoo.vcard_form_page', {
                'error': f'Error preparing mailing list: {str(e)}',
                'countries': request.env['res.country'].sudo().search([]),
                'states': request.env['res.country.state'].sudo().search([]),
            })


        # Handle image upload
        file = request.httprequest.files.get('image_url')
        if file and file.filename:
            vals['image_url'] = base64.b64encode(file.read()).decode('utf-8')
        else:
            # Use default profile image if no image is uploaded
            default_profile = request.env['partner.vcard']._get_default_profile_image()
            if default_profile:
                vals['image_url'] = default_profile
        
        # Handle banner image upload
        banner_file = request.httprequest.files.get('banner_image')
        if banner_file and banner_file.filename:
            vals['banner_image'] = base64.b64encode(banner_file.read()).decode('utf-8')
        else:
            # Use default banner if no banner is uploaded
            default_banner = request.env['partner.vcard']._get_default_banner_image()
            if default_banner:
                vals['banner_image'] = default_banner

        # Handle QR Code Logo upload
        qr_file = request.httprequest.files.get('qr_logo')
        if qr_file:
            vals['qr_logo'] = base64.b64encode(qr_file.read())

        # Delete any preview vCard for this user before creating the real one
        # This prevents the preview from counting against the vCard limit
        user = request.env.user
        preview_slug = f'preview-{user.id}'
        preview_vcard = request.env['partner.vcard'].sudo().search([
            ('website_slug', '=', preview_slug)
        ], limit=1)
        if preview_vcard:
            # Delete the preview vCard and its related records
            preview_vcard.sudo().unlink()
            _logger.info(f"Deleted preview vCard {preview_vcard.id} before creating real vCard")

        # Bulk-activate mode updates the existing admin-created card in place
        # so the recipient's activation doesn't spawn a duplicate. Otherwise,
        # create a new card for this submission.
        if bulk_vcard:
            bulk_vcard.sudo().with_context(skip_vcard_limit_check=True).write(vals)
            partner = bulk_vcard
            # Flag rep as completed so the admin batch view reflects it.
            if bulk_rep:
                try:
                    bulk_rep.sudo().write({'status': 'completed'})
                except Exception as _e:
                    _logger.warning("Could not mark bulk rep as completed: %s", _e)
        else:
            partner = request.env['partner.vcard'].sudo().with_context(skip_vcard_limit_check=True).create(vals)
        
        # Ensure banner attachment is created if banner_image was set (including default)
        if vals.get('banner_image'):
            partner.sudo()._update_banner_attachment_if_image_changed()
            request.env.cr.flush()
        
        # In bulk-activate mode the admin may have seeded websites / videos on
        # the card before the recipient arrived. The form is now the source of
        # truth, so clear existing ones before re-creating from the submission.
        if bulk_vcard:
            if partner.website_ids:
                partner.website_ids.sudo().unlink()
            if partner.video_ids:
                partner.video_ids.sudo().unlink()

        # Handle websites data
        website_urls = request.httprequest.form.getlist('website_url[]')
        website_names = request.httprequest.form.getlist('website_name[]')
        website_colors = request.httprequest.form.getlist('website_color[]')

        if website_urls and website_urls[0]:  # Check if at least one website URL is provided
            website_data = []
            # Get secondary color as default
            secondary_color = partner.secondary_color or '#4C75A3'  # Default to Vinc blue
            for i, url in enumerate(website_urls):
                if url.strip():  # Only add non-empty URLs
                    # Use provided color, or default to secondary color
                    button_color = website_colors[i] if i < len(website_colors) and website_colors[i] and website_colors[i].strip() else secondary_color
                    website_data.append({
                        'partner_id': partner.id,
                        'website_url': url.strip(),
                        'name': website_names[i] if i < len(website_names) and website_names[i].strip() else 'Website',
                        'button_color': button_color
                    })
            
            if website_data:
                request.env['partner.vcard.website'].sudo().create(website_data)
        
        # Handle videos data
        video_urls = request.httprequest.form.getlist('video_url[]')
        video_names = request.httprequest.form.getlist('video_name[]')
        
        if video_urls and video_urls[0]:  # Check if at least one video URL is provided
            video_data = []
            for i, url in enumerate(video_urls):
                if url.strip():  # Only add non-empty URLs
                    video_data.append({
                        'partner_id': partner.id,
                        'video_url': url.strip(),
                        'name': video_names[i] if i < len(video_names) and video_names[i].strip() else 'Video'
                    })
            
            if video_data:
                request.env['partner.vcard.videos'].sudo().create(video_data)
        
        # Generate website page and commit changes
        if hasattr(partner, 'action_generate_website_page'):
            partner.action_generate_website_page()
        
        # Redirect authenticated users to their vCard list
        # Public users will be redirected to login anyway
        return request.redirect('/web#action=qr_code_odoo.action_partner_vcard')
