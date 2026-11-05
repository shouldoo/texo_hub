# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models


class MemoryOptoutName(models.Model):
    """A name that no lesson may contain: the customers that opted out.

    The names are kept in clear because the leak filter matches substrings; the
    list is readable by administrators only and is never returned by any route.
    """
    _name = 'memory.optout.name'
    _description = "Memory Opt-out Name"
    _order = 'name'

    name = fields.Char(required=True, index=True)
    reason = fields.Char(help="The request that caused the opt-out, as a reference (no customer data).")

    _name_unique = models.Constraint('unique (name)', "This name is already in the opt-out list.")
