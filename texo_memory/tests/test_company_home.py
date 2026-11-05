# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase


@tagged('post_install', '-at_install')
class TestCompanyHome(MemoryCase):
    """What belongs to the organisation itself, and to no customer, lives on the company: a
    note or a document with no anchor goes there, the pack of the organisation is the pack
    of the company by section, and the organisation is never a customer. The home project
    stays, for the internal work."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.home = cls.company._texo_home_project()
        cls.other_company = cls.env['res.company'].create({'name': 'Seconda S.r.l.'})
        cls.member.company_ids = [Command.link(cls.other_company.id)]

    def test_a_note_with_no_anchor_goes_on_the_company(self):
        result = self.note_as(self.member, task_id=None, name='Our own rule', project_id=None)
        note = self.env['memory.note'].browse(result['id'])
        self.assertEqual((note.company_id, note.project_id), (self.company, self.env['project.project']))
        self.assertFalse(note.customer_id, "the organisation is not a customer")
        other = self.env['memory.note'].browse(self.note_as(
            self.member, project_id=None, name='Of the second company', company_id=self.other_company.id)['id'])
        self.assertEqual(other.company_id, self.other_company)
        with self.assertRaises(UserError):
            self.note_as(self.lead, project_id=None, company_id=self.other_company.id)
        # the UI way: a note created without an anchor lands on the company too
        direct = self.env['memory.note'].with_user(self.lead).create({'name': 'Direct', 'body': 'x'})
        self.assertEqual(direct.company_id, self.company)
        with self.assertRaises(UserError):
            self.note_as(self.member, project_id=self.project.id, partner_id=self.customer.id)
        self.assertFalse(self.env['memory.note'].with_user(self.outsider).search([('id', '=', other.id)]),
                         "a note of a company the user does not work in is not theirs")

    def test_a_document_with_no_anchor_goes_on_the_company_and_is_listed_there(self):
        Attachment = self.env['ir.attachment'].with_user(self.member)
        result = Attachment._texo_write(name='Procedure aziendali', url='https://drive.example.com/procedure.pdf',
                                                 summary='What a procedure is.',
                                                 text='# Procedure\n\nA procedure says who does what.')
        document = self.env['ir.attachment'].browse(result['id'])
        self.assertEqual((document.res_model, document.res_id), ('res.company', self.company.id),
                         "the document is on the company, for the people")
        self.assertEqual(document.texo_text_ids.res_model, 'res.company', "its text next to it")
        self.assertEqual([d['id'] for d in Attachment._texo_list()], [document.id])
        self.assertEqual(Attachment._texo_list(company_id=self.other_company.id), [])
        self.assertIn(document.id, [d['id'] for d in self.env['ir.attachment'].with_user(self.lead)._texo_list()],
                      "the documents of the organisation are visible to who works in it")

    def test_the_pack_of_the_organisation_is_the_pack_of_the_company_by_section(self):
        Note = self.env['memory.note']
        self.note_as(self.lead, project_id=None, name='Odoo version of the office', state='active')
        Note.with_user(self.member)._agent_note('Who signs', 'The director signs the offers.', kind='fact',
                                                 section='profile')
        Note.with_user(self.member)._agent_note('Close a month', '1. Reconcile the bank.\n2. Close the period.',
                                                 kind='procedure', section='operations')
        pack = Note.with_user(self.member)._agent_context()
        self.assertEqual([(l['model'], l['id']) for l in pack['levels']], [('res.company', self.company.id)])
        self.assertEqual([c['title'] for c in pack['levels'][0]['rules']], ['Odoo version of the office'])
        self.assertEqual([(f['title'], f['section']) for f in pack['levels'][0]['facts']], [('Who signs', 'profile')])
        self.assertEqual([p['title'] for p in pack['levels'][0]['procedures']], ['Close a month'])
        self.assertIn('compliance', [s['code'] for s in pack['sections']])
        self.assertNotIn('project', pack, "the organisation is not a project")
        index = Note.with_user(self.member)._okf_context(pack, self.company)['files'][0]['text']
        self.assertIn(f"# Organisation: {self.company.name} / Profile", index)
        self.assertIn("- Procedure: 1. Reconcile the bank.", index)
        other = Note.with_user(self.member)._agent_context(company_id=self.other_company.id)
        self.assertEqual(other['levels'][0]['id'], self.other_company.id)
        self.assertEqual(other['levels'][0]['rules'], [])
        # an internal task: its chain ends at the home project, which stays for the internal work
        task = self.env['project.task'].create({'name': 'Write the procedure', 'project_id': self.home.id})
        pack = Note.with_user(self.member)._agent_context(task_id=task.id)
        self.assertEqual([l['model'] for l in pack['levels']], ['project.task', 'project.project'])

    def test_a_project_of_our_own_company_as_customer_is_not_a_customer(self):
        internal = self.env['project.project'].create({'name': 'Office IT', 'partner_id': self.company.partner_id.id})
        note = self.env['memory.note'].browse(self.note_as(self.lead, task_id=None, project_id=internal.id, state='active')['id'])
        self.assertFalse(note.customer_id)
        pack = self.env['memory.note'].with_user(self.lead)._agent_context(project_id=internal.id)
        self.assertEqual([l['model'] for l in pack['levels']], ['project.project'])
        customer_note = self.env['memory.note'].browse(self.note_as(self.lead, state='active')['id'])
        self.assertEqual(customer_note.customer_id, self.customer, "a real customer stays one")

    def test_the_optout_refuses_our_own_company(self):
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Admin', 'login': 'chm_home_admin',
            'group_ids': [Command.link(self.env.ref('texo.group_texo_admin').id)]})
        wizard = self.env['memory.optout.wizard'].with_user(admin).create({
            'partner_id': self.company.partner_id.id, 'reason': 'x', 'confirm_name': self.company.partner_id.name})
        with self.assertRaises(UserError):
            wizard.action_optout()

    def test_a_lesson_belongs_to_a_company_or_to_all(self):
        Lesson = self.env['memory.lesson'].with_user(self.lead)
        mine = Lesson.create({'name': 'Of the first company', 'finding': CLEAN_FINDING,
                              'solution': CLEAN_SOLUTION, 'state': 'active'})
        self.assertEqual(mine.company_id, self.company)
        shared = Lesson.create({'name': 'Shared by all', 'finding': CLEAN_FINDING,
                                'solution': CLEAN_SOLUTION, 'state': 'active', 'company_id': False})
        with self.assertRaises(AccessError, msg="a lead writes only in the companies they work in"):
            Lesson.create({'name': 'Of the second company', 'finding': CLEAN_FINDING,
                           'solution': CLEAN_SOLUTION, 'state': 'active', 'company_id': self.other_company.id})
        self.lead.company_ids = [Command.link(self.other_company.id)]
        theirs = Lesson.with_context(allowed_company_ids=[self.company.id, self.other_company.id]).create({
            'name': 'Of the second company', 'finding': CLEAN_FINDING,
            'solution': CLEAN_SOLUTION, 'state': 'active', 'company_id': self.other_company.id})
        visible = self.env['memory.lesson'].with_user(self.outsider).search([('id', 'in', (mine | shared | theirs).ids)])
        self.assertEqual(visible, mine | shared, "an outsider of the second company does not see its lessons")
        both = self.env['memory.lesson'].with_user(self.member).with_context(
            allowed_company_ids=[self.company.id, self.other_company.id]).search([('id', 'in', (mine | shared | theirs).ids)])
        self.assertEqual(both, mine | shared | theirs)
        result = self.env['memory.lesson'].with_user(self.member)._agent_lesson(
            CLEAN_FINDING, CLEAN_SOLUTION)
        finding = self.env['memory.lesson'].browse(result['id'])
        self.assertEqual(finding.company_id, self.company, "a finding is born in the current company")
