# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestProjectContext(TransactionCase):
    """The project as an agent reads it: the description, the milestones as the
    roadmap, the last update as its present."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        groups = [Command.link(cls.env.ref('texo.group_texo_member').id),
                  Command.link(cls.env.ref('project.group_project_user').id)]
        cls.dev = Users.create({'name': 'Dev', 'login': 'chp_ctx_dev', 'group_ids': groups})
        cls.other = Users.create({'name': 'Other', 'login': 'chp_ctx_other', 'group_ids': groups})
        cls.customer = cls.env['res.partner'].create({'name': 'Alfa S.r.l.', 'is_company': True})
        cls.project = cls.env['project.project'].create({
            'name': 'Alfa migration', 'partner_id': cls.customer.id, 'privacy_visibility': 'followers',
            'allowed_internal_user_ids': [Command.link(cls.dev.id)], 'allow_milestones': True,
            'description': '<p>Migrate <b>Alfa</b> from 17.0 to 20.0.</p><p>Never on Fridays.</p>',
        })
        cls.today = fields.Date.context_today(cls.project)
        Milestone = cls.env['project.milestone']
        cls.done = Milestone.create({'name': 'Assessment', 'project_id': cls.project.id, 'is_reached': True,
                                     'deadline': cls.today - timedelta(days=40)})
        # reached long ago: the ORM dates it today
        cls.done.reached_date = cls.today - timedelta(days=40)
        cls.later = Milestone.create({'name': 'Go live', 'project_id': cls.project.id,
                                      'deadline': cls.today + timedelta(days=60)})
        cls.late = Milestone.create({'name': 'Test on stage', 'project_id': cls.project.id,
                                     'deadline': cls.today - timedelta(days=5)})
        cls.open_ms = Milestone.create({'name': 'Training', 'project_id': cls.project.id})
        Task = cls.env['project.task']
        cls.task = Task.create({'name': 'Port the modules', 'project_id': cls.project.id, 'milestone_id': cls.late.id})
        Task.create({'name': 'Inventory', 'project_id': cls.project.id, 'milestone_id': cls.late.id, 'state': '1_done'})

    def update(self, days_ago=0, **vals):
        update = self.env['project.update'].create(dict({
            'project_id': self.project.id, 'name': 'Week', 'status': 'on_track', 'progress': 40,
            'description': '<p>Modules ported.</p>'}, **vals))
        update.date = self.today - timedelta(days=days_ago)
        return update

    def test_description_and_roadmap(self):
        context = self.project.with_user(self.dev)._texo_context()
        self.assertEqual(context['description'], 'Migrate *Alfa* from 17.0 to 20.0.\nNever on Fridays.')
        self.assertEqual((context['customer'], context['home']), ('Alfa S.r.l.', False))
        self.assertEqual([m['name'] for m in context['milestones']], ['Test on stage', 'Go live', 'Training', 'Assessment'])
        late = context['milestones'][0]
        self.assertEqual((late['overdue'], late['open_tasks'], late['closed_tasks']), (True, 1, 1))
        self.assertEqual(context['milestones'][-1]['reached'], True)
        self.project.allow_milestones = False
        self.assertEqual(self.project.with_user(self.dev)._texo_context()['milestones'], [])

    def test_the_last_update_is_the_present(self):
        context = self.project.with_user(self.dev)._texo_context()
        self.assertIsNone(context['now'])
        self.assertEqual(context['warnings'], ['now_missing'])
        self.update(days_ago=10, name='Older')
        update = self.update(days_ago=1, name='Latest', status='at_risk', progress=55)
        context = self.project.with_user(self.dev)._texo_context()
        self.assertEqual(context['now']['id'], update.id)
        self.assertEqual((context['now']['status'], context['now']['progress']), ('at_risk', 55))
        self.assertEqual(context['now']['description'], 'Modules ported.')
        # the stage test fell due before the update: still the present
        self.assertEqual(context['warnings'], [])

    def test_an_old_update_or_a_milestone_after_it_is_stale(self):
        self.update(days_ago=45)
        self.assertEqual(self.project._texo_now_warnings(self.today), ['now_stale'])
        self.update(days_ago=20)
        self.assertEqual(self.project._texo_now_warnings(self.today), ['now_stale'],
                         "the stage test fell due after the update")
        self.late.deadline = self.today - timedelta(days=25)
        self.assertEqual(self.project._texo_now_warnings(self.today), [])
        self.open_ms.is_reached = True
        self.assertEqual(self.project._texo_now_warnings(self.today), ['now_stale'],
                         "a milestone reached after the update")

    def test_write_an_update_as_the_user(self):
        project = self.project.with_user(self.dev)
        result = project._texo_write_update('Week 44', 'at_risk', 'Stage late.\n<b>Risk</b>: data', 60)
        update = self.env['project.update'].browse(result['id'])
        self.assertEqual(self.project.last_update_id, update)
        self.assertEqual((update.user_id, update.status, update.progress), (self.dev, 'at_risk', 60))
        self.assertNotIn('<b>', update.description)
        self.assertEqual(project._texo_context()['now']['id'], update.id)
        # progress kept from the last update when not given
        self.assertEqual(project._texo_write_update('Week 45', 'on_track', 'Stage done.')['progress'], 60)
        for args in (('x', 'green', 'y'), ('', 'on_track', 'y'), ('x', 'on_track', ' '), ('x', 'on_track', 'y', 101),
                     ('x', 'on_track', 'y', True)):
            with self.assertRaises(UserError):
                project._texo_write_update(*args)
        with self.assertRaises(AccessError):
            self.project.with_user(self.other)._texo_write_update('x', 'on_track', 'y')

    def test_the_task_carries_its_milestone(self):
        context = self.task.with_user(self.dev)._texo_context()
        self.assertEqual(context['milestone'], {'id': self.late.id, 'name': 'Test on stage', 'reached': False,
                                                'deadline': fields.Date.to_string(self.late.deadline)})
