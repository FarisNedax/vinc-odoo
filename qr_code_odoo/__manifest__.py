{
    'name': 'Vinc',
    'version': '19.0.1.0.1',
    'category': 'Tools',
    'summary': 'Digital business cards, lead capture & analytics inside Odoo',
    'description': """
Vinc brings digital business cards and lead capture directly into your Odoo database.

Each user gets a smart vCard page with QR / NFC links that you can print on cards, badges, email signatures, or marketing materials. When someone scans the code, they land on a branded contact page that lives in your Odoo environment.

Key features:
- Create and manage per-user digital business cards (vCards) in Odoo
- Generate QR / URL links for cards (ideal for NFC cards, bands, badges, email signatures)
- Capture leads directly from the vCard page into Odoo CRM
- Track card views, scans, and form submissions with built-in analytics
- Configure services, reviews, and custom sections on each card
- Use Odoo's pipeline and activities for follow-up on captured leads
- All data stored in your Odoo database (no external data storage)

This module is designed for companies that want Vinc-style digital cards and lead capture, but prefer to keep everything self-hosted in their own Odoo instance.
""",
    'author': 'Faris Delija',
    'license': 'OPL-1',
    'price': 399,
    'currency': 'USD',
    'support': 'support@getvinc.com',
    'images': ['static/description/Banner.png'],
    'depends': ['base', 'web', 'crm', 'website', 'utm', 'mass_mailing', 'event_crm'],
    'data': [
        # Security: groups first so ir.model.access.csv can reference them
        'security/vinc_groups.xml',
        'security/ir.model.access.csv',
        'security/vinc_record_rules.xml',
        'security/bulk_onboarding_rules.xml',
        'data/leadback_preview_model.xml',
        'data/followup_scheduled_reminder_model.xml',
        'data/vcard_download_tracking_model.xml',
        'data/cron_actions.xml',
        'data/license_cron.xml',
        'data/leadback_channels.xml',
        'data/digest_email_template.xml',
        'data/lead_notification_email_template.xml',
        'data/intro_email_template.xml',
        'data/bulk_onboarding_models.xml',
        'data/bulk_onboarding_email_templates.xml',
        'views/user_dashboard.xml',
        'views/partner_view.xml',
        'views/vcard_dashboard.xml',
        'views/leadback_preview.xml',
        'views/vcard_layout.xml',
        'views/vcard_form_template.xml',
        'views/vcard_templates.xml',
        'views/success_page.xml',
        'views/crm_lead_view.xml',
        'views/partner_reviews_view.xml',
        'views/nfc_onboarding_template.xml',
        'views/vinculum_guide_template.xml',
        'views/vinculum_guide_users.xml',
        'views/vinculum_guide_admins.xml',
        'views/bulk_onboarding_templates.xml',
        'views/magic_link_templates.xml',
        'views/res_config_settings_views.xml',
        'views/vinc_license_views.xml',
        'views/license_required_template.xml',
        'views/license_banner_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            '/qr_code_odoo/static/src/js/widget.js',
            '/qr_code_odoo/static/src/js/vg_fonts.js',
            '/qr_code_odoo/static/src/css/get_started.css',
            '/qr_code_odoo/static/src/js/get_started.js',
            '/qr_code_odoo/static/src/css/bulk_onboard.css',
            '/qr_code_odoo/static/src/js/bulk_onboard.js',
        ],
        'web.assets_backend': [
            '/qr_code_odoo/static/src/css/reviews_backend.css',
            '/qr_code_odoo/static/src/css/mobile_tables.css',
            '/qr_code_odoo/static/src/css/dashboard.css',
            '/qr_code_odoo/static/src/js/vg_fonts.js',
            '/qr_code_odoo/static/src/js/signature_generator.js',
            '/qr_code_odoo/static/src/js/virtual_bg_generator.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
