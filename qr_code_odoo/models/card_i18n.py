# -*- coding: utf-8 -*-
"""Translations for the generated public card pages.

Each card page is an ir.ui.view whose arch is generated in Python
(partner_website1.py), so its text is not in the module's .po file the way
a module template's is. The fixed labels of those pages are listed here as
code terms; after a page is generated, sync_card_view_translations() copies
their translation into the view's arch_db for every installed language.
Sentences that carry the card owner's name use a %(name)s placeholder and
are rendered with ``t-out="vinc_label % {...}"`` in the template.
"""
import html
import re

from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

CARD_TERMS = [
    # header / action buttons
    _lt("Back to Dashboard"),
    _lt("Call"),
    _lt("CALL"),
    _lt("Email"),
    _lt("EMAIL"),
    _lt("Get %(name)s's Info"),
    _lt("QR Code"),
    _lt("Drop Info"),
    _lt("Drop Your Info"),
    _lt("Get In Touch"),
    _lt("INQUIRE"),
    # sections
    _lt("About"),
    _lt("About Me"),
    _lt("Contact"),
    _lt("Services"),
    _lt("Request"),
    _lt("Specialities"),
    _lt("Specialties"),
    _lt("Specialties:"),
    _lt("Reviews"),
    _lt("Testimonials"),
    _lt("Add +"),
    _lt("Anonymous"),
    _lt("No reviews yet. Be the first to leave a review!"),
    _lt("Video"),
    _lt("Videos"),
    _lt("Video could not be loaded"),
    _lt("Watch on YouTube"),
    _lt("Websites"),
    _lt("Social Media"),
    _lt("Socials"),
    _lt("Social"),
    _lt("Calendar"),
    _lt("Previous"),
    _lt("Next"),
    # contact details
    _lt("Primary Phone"),
    _lt("Mobile"),
    _lt("Company"),
    _lt("Position"),
    _lt("Address"),
    _lt("Directions"),
    _lt("Company LinkedIn"),
    _lt("Company Facebook"),
    _lt("Company Instagram"),
    _lt("Company Twitter"),
    _lt("Google Reviews"),
    # lead form
    _lt("Fill in your details"),
    _lt("Full name"),
    _lt("Your name"),
    _lt("Phone"),
    _lt("Your phone number"),
    _lt("Notes"),
    _lt("Anything else you'd like to share (optional)"),
    _lt("Share My Contact"),
    _lt("* By clicking the 'Share My Contact' button, I agree to be contacted by %(name)s"),
    _lt("Thank you! I look forward to talking with you soon."),
    _lt("Close"),
    # QR modal
    _lt("Scan to connect"),
    _lt("Scan to save or share this card"),
    _lt("Scan this QR code to quickly save %(name)s's information to your device."),
    _lt("Download vCard"),
    # review form
    _lt("Leave a Review"),
    _lt("Your Name"),
    _lt("Rating"),
    _lt("Your Review"),
    _lt("Submit Review"),
    _lt("* Your review will be visible once approved by %(name)s"),
    _lt("Thank you for your review! We appreciate your feedback."),
    # service request form
    _lt("Request Service"),
    _lt("Service:"),
    _lt("Your Phone"),
    _lt("Additional Details"),
    _lt("Add any additional information or requirements..."),
    _lt("Send Request"),
    _lt("* By clicking 'Send Request', I agree to be contacted by %(name)s regarding this service"),
    _lt("Thank you! Your service request has been sent. We'll be in touch shortly."),
]

_TAG = re.compile(r'(<[^>]+>)')


def _translate_term(term, table):
    """Translate the text pieces of one arch term, leaving inline tags as they are."""
    parts = _TAG.split(term)
    for i in range(0, len(parts), 2):  # even indexes are text, odd are tags
        text = parts[i].strip()
        dst = table.get(html.unescape(text)) if text else None
        if dst:
            parts[i] = parts[i].replace(text, dst)
    return ''.join(parts)


def sync_card_view_translations(view):
    """Translate the card page ``view`` into every installed language.

    Terms someone already translated by hand (website translate mode) are kept.
    """
    view = view.sudo()
    langs = [code for code, _name in view.env['res.lang'].get_installed() if code != 'en_US']
    if not langs:
        return
    field = view._fields['arch_db']
    source = view.with_context(lang='en_US').arch_db
    current = {lang: view.with_context(lang=lang).arch_db for lang in langs}
    done = field.get_translation_dictionary(source, current)
    translations = {}
    for lang in langs:
        table = {t._source: t._translate(lang) for t in CARD_TERMS}
        mapping = {}
        for term, by_lang in done.items():
            if by_lang.get(lang, term) != term:
                continue  # already translated
            new = _translate_term(term, table)
            if new != term:
                mapping[term] = new
        if mapping:
            translations[lang] = mapping
    if translations:
        view.update_field_translations('arch_db', translations)
