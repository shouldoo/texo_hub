# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models

KINDS = [('person', "Public Person"), ('body', "Body"), ('place', "Place"), ('theme', "Theme")]


class MemorySourceTag(models.Model):
    """A label of the cards: a public person, a body, a place or a theme.

    A person named in an article is a label, not a contact of the organisation: the memory
    keeps who was talked about to find the cards again, it does not file people. The themes
    are the organisation's own vocabulary (the topics of a programme, the areas of work)."""
    _name = 'memory.source.tag'
    _description = "External Source Label"
    _order = 'kind, name'

    name = fields.Char(required=True)
    kind = fields.Selection(KINDS, required=True, default='theme', index=True)
    color = fields.Integer()
    note = fields.Char(help="Who or what it is, in a few words (e.g. the role of a public person).")
    company_id = fields.Many2one('res.company', string="Organisation", required=True, index=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True)

    _unique_name = models.Constraint('UNIQUE(company_id, kind, name)', "A label with this name and kind already exists.")
