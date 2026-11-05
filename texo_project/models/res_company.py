# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    """Every company of the instance has a home project: the place of what belongs to
    the organisation itself and to no customer (its documents, its notes, its
    internal work). Born with the company and at the installation of the module."""
    _inherit = 'res.company'

    def _texo_home_project(self, create=True):
        """The home project of the company: found whatever its state, created when
        missing (as the system: a home is a record of the module, not of the user).
        With create false a missing home raises, for the read-only routes."""
        self.ensure_one()
        Project = self.env['project.project'].with_context(active_test=False)
        home = Project.search([('texo_home', '=', True), ('company_id', '=', self.id)], limit=1)
        if home:
            return home
        if not create:
            raise UserError(self.env._("Company %s has no home project: upgrade texo_project.", self.name))
        # sudo: the home belongs to the module; a member who writes the first note of
        # the organisation may not create projects.
        return Project.sudo().create(self._texo_home_vals())

    def _texo_home_vals(self):
        self.ensure_one()
        return {
            'name': self.name, 'company_id': self.id, 'texo_home': True,
            # the organisation is not a customer: no partner, so nothing treats it as one
            'partner_id': False, 'privacy_visibility': 'employees', 'user_id': False,
        }

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        for company in companies:
            company._texo_home_project()
        return companies

    @api.model
    def _texo_ensure_homes(self):
        """A home for every company, existing ones included: the installation hook and
        the migration call it; idempotent."""
        homes = self.env['project.project']
        for company in self.sudo().with_context(active_test=False).search([]):
            homes |= company._texo_home_project()
        return homes
