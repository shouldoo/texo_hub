# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestCompanyHome(TransactionCase):

    def _home(self, company):
        return self.env['project.project'].with_context(active_test=False).search(
            [('texo_home', '=', True), ('company_id', '=', company.id)])

    def test_every_company_has_one_home_after_the_installation(self):
        for company in self.env['res.company'].with_context(active_test=False).search([]):
            home = self._home(company)
            self.assertEqual(len(home), 1, company.name)
            self.assertEqual(home.name, company.name)
            self.assertFalse(home.partner_id, "the organisation is not a customer")
            self.assertEqual(home.privacy_visibility, 'employees')
            self.assertEqual(company._texo_home_project(), home, "idempotent")

    def test_a_new_company_is_born_with_its_home(self):
        company = self.env['res.company'].create({'name': 'Seconda S.r.l.'})
        home = self._home(company)
        self.assertEqual(len(home), 1)
        self.assertEqual(home.company_id, company)
        self.assertEqual(self.env['res.company']._texo_ensure_homes() & home, home)
        self.assertEqual(len(self._home(company)), 1, "ensure_homes creates nothing twice")

    def test_an_archived_home_is_found_not_duplicated(self):
        company = self.env.company
        home = company._texo_home_project()
        home.active = False
        self.assertEqual(company._texo_home_project(), home)
        home.active = True

    def test_one_home_per_company_and_no_customer_on_it(self):
        company = self.env.company
        home = company._texo_home_project()
        with self.assertRaises(UserError):
            self.env['project.project'].create({'name': 'Second home', 'company_id': company.id, 'texo_home': True})
        with self.assertRaises(UserError):
            home.partner_id = self.env['res.partner'].create({'name': 'Cliente', 'is_company': True})
        with self.assertRaises(UserError):
            home.unlink()

    def test_the_organisation_is_never_a_customer(self):
        Project = self.env['project.project']
        self.assertTrue(Project._texo_is_own_partner(self.env.company.partner_id))
        contact = self.env['res.partner'].create({'name': 'Collega', 'parent_id': self.env.company.partner_id.id})
        self.assertTrue(Project._texo_is_own_partner(contact), "a contact of our company is ours")
        customer = self.env['res.partner'].create({'name': 'Cliente', 'is_company': True})
        self.assertFalse(Project._texo_is_own_partner(customer))
        self.assertFalse(Project._texo_is_own_partner(self.env['res.partner']))

    def test_a_missing_home_raises_on_read_only_paths(self):
        company = self.env['res.company'].create({'name': 'Terza S.r.l.'})
        home = self._home(company)
        self.env.cr.execute("UPDATE project_project SET texo_home = false WHERE id = %s", [home.id])
        home.invalidate_recordset()
        with self.assertRaises(UserError):
            company._texo_home_project(create=False)
        self.assertNotEqual(company._texo_home_project(), home, "recreated when writing")
