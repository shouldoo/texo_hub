# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import re

from odoo import api, fields, models
from odoo.exceptions import UserError

CODE = re.compile(r'^[a-z][a-z0-9_]*$')


class MemorySection(models.Model):
    """A part of what the memory knows of a record, above all of the organisation: who it
    is, how it works, what it complies with, its sector, what it offers. The facts, the
    procedures and the rules stand in a section; the pack of the organisation is an index
    by section (a level of the OKF bundle: organisation/compliance/...). The organisation
    adds its own sections."""
    _name = 'memory.section'
    _description = "Memory Section"
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="The word an agent passes for the section, e.g. compliance.")
    description = fields.Text(translate=True, help="What the section holds: the agent reads it to choose one.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint('UNIQUE(code)', "The code of a section must be unique.")

    @api.constrains('code')
    def _check_code(self):
        for section in self:
            if not CODE.match(section.code or ''):
                raise UserError(self.env._(
                    "The code of a section is one lowercase word (letters, digits, underscore): %s.", section.code))

    @api.model
    def _from_code(self, code):
        """The section named by its code; an unknown code is refused with the known ones."""
        if not code:
            return self.browse()
        section = self.search([('code', '=', code.strip())], limit=1)
        if not section:
            raise UserError(self.env._("Unknown section %(code)s. The sections are: %(known)s.",
                                       code=code, known=", ".join(self.search([]).mapped('code'))))
        return section

    def _agent_summary(self):
        return [{'code': section.code, 'name': section.name, 'description': section.description or ''}
                for section in self]
