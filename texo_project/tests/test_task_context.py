# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestTaskContext(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        groups = [Command.link(cls.env.ref('texo.group_texo_member').id),
                  Command.link(cls.env.ref('project.group_project_user').id)]
        cls.dev = Users.create({'name': 'Dev', 'login': 'chp_dev', 'group_ids': groups})
        cls.other = Users.create({'name': 'Other', 'login': 'chp_other', 'group_ids': groups})
        cls.customer = cls.env['res.partner'].create({'name': 'Alfa S.r.l.', 'is_company': True})
        cls.project = cls.env['project.project'].create({
            'name': 'Alfa', 'partner_id': cls.customer.id, 'privacy_visibility': 'followers',
        })
        cls.project.message_subscribe(partner_ids=cls.dev.partner_id.ids)
        Task = cls.env['project.task']
        cls.task = Task.create({
            'name': 'Returns flow', 'project_id': cls.project.id, 'user_ids': [Command.link(cls.dev.id)],
            'description': '<p>Handle <b>customer returns</b> with a dedicated route.</p>',
        })
        cls.done = Task.create({
            'name': 'Old work', 'project_id': cls.project.id, 'user_ids': [Command.link(cls.dev.id)],
            'state': '1_done',
        })
        cls.task.message_post(body="Customer confirmed the scope.", message_type='comment',
                              subtype_xmlid='mail.mt_comment')

    def test_my_work_lists_only_my_open_tasks(self):
        tasks = self.env['project.task'].with_user(self.dev)._texo_my_work()['tasks']
        self.assertEqual([t['id'] for t in tasks], [self.task.id])
        self.assertEqual(tasks[0]['customer'], 'Alfa S.r.l.')
        self.assertEqual(self.env['project.task'].with_user(self.other)._texo_my_work()['tasks'], [])

    def test_context_is_plain_text_with_latest_messages(self):
        context = self.task.with_user(self.dev)._texo_context(messages=5)
        self.assertEqual(context['description'], 'Handle *customer returns* with a dedicated route.')
        self.assertEqual(context['messages'][0]['body'], 'Customer confirmed the scope.')
        self.assertFalse(context['messages'][0]['internal_note'])
        self.assertEqual(context['project'], 'Alfa')

    def test_post_note_is_internal_and_escaped(self):
        task = self.task.with_user(self.dev)
        result = task._texo_post_note('<script>alert(1)</script> scope agreed')
        message = self.env['mail.message'].browse(result['message_id'])
        self.assertTrue(message.subtype_id.internal)
        self.assertEqual(message.author_id, self.dev.partner_id)
        self.assertNotIn('<script>', message.body)
        with self.assertRaises(UserError):
            task._texo_post_note('   ')

    def test_post_note_merges_the_search_keywords(self):
        task = self.task.with_user(self.dev)
        self.assertEqual(task._texo_post_note('Nothing to add')['keywords'], None)
        self.assertFalse(self.task.texo_keywords)
        result = task._texo_post_note('Returns fixed', keywords=['reso', 'RMA', ' ', 'return'])
        self.assertEqual(result['keywords'], 'reso, RMA, return')
        task._texo_post_note('Checked again', keywords='RMA, ubicazione resi')
        self.assertEqual(self.task.texo_keywords, 'reso, RMA, return, ubicazione resi',
                         "merged, in order, without duplicates")
        self.assertEqual(task._texo_context()['keywords'], 'reso, RMA, return, ubicazione resi')

    def test_private_project_hidden_from_non_members(self):
        self.assertFalse(self.task.with_user(self.other).has_access('read'))
