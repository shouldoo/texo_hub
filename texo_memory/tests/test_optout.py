# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..models.leak_filter import leak_reason
from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase


@tagged('post_install', '-at_install')
class TestOptout(MemoryCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Admin', 'login': 'chm_admin',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_admin').id),
                          Command.link(cls.env.ref('project.group_project_manager').id)]})

    def test_optout_deletes_the_rules_and_keeps_the_findings(self):
        self.note_as(self.lead, state='active')
        self.note_as(self.lead, name='Weekend', body='Releases only on Saturday.', state='active')
        self.note_as(self.lead, name='Contract', body='Community only, by contract.', state='active',
                     partner_id=self.customer.id)
        self.env['memory.lesson'].with_user(self.lead)._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION, state='active')
        request = self.env['project.task'].create({'name': 'Opt-out request', 'project_id': self.project.id})
        wizard = self.env['memory.optout.wizard'].with_user(self.admin).create({
            'partner_id': self.customer.id, 'task_id': request.id, 'reason': 'request of the customer',
            'confirm_name': 'wrong'})
        self.assertEqual(wizard.note_count, 3)
        with self.assertRaises(UserError):
            wizard.action_optout()
        wizard.confirm_name = 'rossi meccanica'
        certificate = wizard.action_optout()
        self.assertEqual(certificate['deleted']['notes'], 3)
        self.assertEqual(len(certificate['sha256']), 64)
        self.assertFalse(self.env['memory.note'].with_context(active_test=False).search([('customer_id', '=', self.customer.id)]))
        self.assertEqual(self.env['memory.lesson'].search_count([('kind', '=', 'finding')]), 1)
        self.assertFalse(self.customer.active)
        self.assertEqual(self.env['memory.optout.name'].search([]).mapped('name'), ['Rossi Meccanica'])
        self.assertIn('sha256', request.message_ids[0].body)
        # Archived or not, the former customer may never be named again.
        self.assertEqual(leak_reason(self.env, "A lesson that mentions Rossi Meccanica by name is refused."),
                         "it names a customer")

    def test_only_an_administrator_runs_it(self):
        wizard = self.env['memory.optout.wizard'].with_user(self.admin).create({
            'partner_id': self.customer.id, 'reason': 'x', 'confirm_name': 'Rossi Meccanica'})
        with self.assertRaises(AccessError):
            wizard.with_user(self.lead).action_optout()
