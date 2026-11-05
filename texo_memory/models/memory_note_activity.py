# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

CODE = re.compile(r'^[a-z][a-z0-9_]*$')


class MemoryNoteActivity(models.Model):
    """A kind of work a rule applies to: analysing a request, writing to a customer.
    The session says what it is doing and its context pack carries the rules of that
    activity and the rules with none, which apply to every activity. The module ships
    only activities every organisation has; a sector adds its own through the seed of
    its industry (writing code, deploying), the organisation through the backend."""
    _name = 'memory.note.activity'
    _inherit = ['memory.seed.mixin']
    _description = "Rule Activity"
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="The word an agent passes for the activity of its session, e.g. analysis.")
    description = fields.Text(translate=True, help="What work the activity covers: the agent reads it to choose one.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', "The code of an activity must be unique.")

    @api.constrains('code')
    def _check_code(self):
        for activity in self:
            if not CODE.match(activity.code or ''):
                raise UserError(self.env._(
                    "The code of an activity is one lowercase word (letters, digits, underscore): %s.", activity.code))

    @api.model
    def _from_codes(self, codes):
        """The activities named by the codes of a session, a list or a comma-separated
        string; an unknown code is refused with the known ones."""
        if isinstance(codes, str):
            codes = codes.split(',')
        codes = [code.strip() for code in codes or () if code and code.strip()]
        activities = self.search([('code', 'in', codes)])
        unknown = sorted(set(codes) - set(activities.mapped('code')))
        if unknown:
            raise UserError(self.env._(
                "Unknown activity %(unknown)s. The activities are: %(known)s.",
                unknown=", ".join(unknown), known=", ".join(self.search([]).mapped('code'))))
        return activities

    def _agent_summary(self):
        return [{'code': activity.code, 'name': activity.name, 'description': activity.description or ''}
                for activity in self]
