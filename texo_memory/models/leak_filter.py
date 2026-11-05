# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Deterministic leak filter for the shared text of a lesson.

One function, reused by the write path, the housekeeping cron and the tests, so
every path applies the same rules. It returns the reason of the first leak it
finds, or None when the text is clean. No customer, person, amount or record
reference may reach a lesson: a lesson belongs to nobody and survives the
opt-out of the customer it was learned on.
"""
import re

MIN_LEN = 20
MAX_LEN = 2000
MIN_NAME_LEN = 3

EMAIL = re.compile(r'[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}', re.IGNORECASE)
URL = re.compile(r'https?://[^\s)>\]"\']+', re.IGNORECASE)
ALLOWED_URL = re.compile(r'^https?://(github\.com/(oca|odoo)/|www\.odoo\.com/documentation/)', re.IGNORECASE)
AMOUNT = re.compile(r'(€|\$|£|\beur\b|\busd\b)\s*\d|\d\s*(€|\$|£|\beur\b|\busd\b)', re.IGNORECASE)
RECORD_REF = re.compile(r'\b[a-z_]+\.[a-z_.]+/\d+\b', re.IGNORECASE)
TICKET_NUMBER = re.compile(r'(^|[^\w.#])#\d{2,}')
PSEUDONYM = re.compile(r'\[(PERSONA|PERSON|NAME|TELEFONO|PHONE|EMAIL|CF|IBAN|PIVA|VAT)[:\]]', re.IGNORECASE)


def forbidden_names(env):
    """Names that a lesson may never contain: every customer company, archived ones
    included, and the names of the customers that opted out."""
    # sudo: a member may not read every partner, but the filter must know every
    # customer name; only the names leave this function, never the records.
    # On 20.0 is_company is computed from the VAT, so a customer is any top-level
    # partner that is neither one of our companies nor the partner of a user.
    own = env['res.company'].sudo().with_context(active_test=False).search([]).partner_id
    partners = env['res.partner'].sudo().with_context(active_test=False).search(
        [('parent_id', '=', False), ('id', 'not in', own.ids), ('user_ids', '=', False)])
    names = set()
    for partner in partners:
        names.update(filter(None, (partner.name, partner.ref)))
    names.update(env['memory.optout.name'].sudo().search([]).mapped('name'))
    return {name.strip().lower() for name in names if name and len(name.strip()) >= MIN_NAME_LEN}


def leak_reason(env, text, source_ref=None, names=None, check_length=True):
    """Return why ``text`` cannot be shared, or None when it is clean."""
    text = (text or '').strip()
    if check_length and len(text) < MIN_LEN:
        return env._("the shared text must be at least %s characters", MIN_LEN)
    if check_length and len(text) > MAX_LEN:
        return env._("the shared text must be at most %s characters", MAX_LEN)
    lowered = text.lower()
    for name in (names if names is not None else forbidden_names(env)):
        if name in lowered:
            return env._("it names a customer")
    if PSEUDONYM.search(text):
        return env._("it contains a pseudonym marker: describe the role, not the person")
    if EMAIL.search(text):
        return env._("it contains an e-mail address")
    for url in URL.findall(text):
        if not ALLOWED_URL.match(url):
            return env._("it contains a URL other than github.com/OCA, github.com/odoo or the Odoo documentation")
    if AMOUNT.search(text):
        return env._("it contains an amount of money")
    if RECORD_REF.search(text):
        return env._("it contains a reference to a record")
    if TICKET_NUMBER.search(text):
        return env._("it contains a task or ticket number")
    if source_ref and source_ref.strip() and source_ref.strip().lower() in lowered:
        return env._("it contains the source reference of the project note")
    return None
