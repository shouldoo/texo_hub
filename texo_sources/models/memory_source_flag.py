# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models


class MemorySourceFlag(models.Model):
    """A doubt about a candidate, from a fixed list shared by Odoo and the agent: the event date
    is uncertain, a person named is not a public figure, a quote cannot be verified, the article
    cannot be read, it duplicates a card, the source is partisan, the channel is unknown, a video
    must be watched. The agent marks them when it prepares the triage; the person sees them in
    Odoo and in the session. The list is data of the module; its codes are what the agent uses."""
    _name = 'memory.source.flag'
    _description = "External Source Doubt"
    _order = 'sequence, id'

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True, translate=True)
    description = fields.Char(translate=True, help="What to check when the flag is raised.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _unique_code = models.Constraint('UNIQUE(code)', "A doubt with this code already exists.")
