# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestProjectRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        groups = [Command.link(cls.env.ref('texo.group_texo_member').id),
                  Command.link(cls.env.ref('project.group_project_user').id)]
        cls.dev = Users.create({'name': 'Dev', 'login': 'chp_http_dev', 'group_ids': groups})
        cls.other = Users.create({'name': 'Other', 'login': 'chp_http_other', 'group_ids': groups})
        project = cls.env['project.project'].create({'name': 'Alfa', 'privacy_visibility': 'followers'})
        project.message_subscribe(partner_ids=cls.dev.partner_id.ids)
        cls.task = cls.env['project.task'].create({
            'name': 'Returns flow', 'project_id': project.id, 'user_ids': [Command.link(cls.dev.id)],
        })

    def _post(self, route, user, payload):
        key = self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/project/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    def test_my_work(self):
        response = self._post('my_work', self.dev, {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([t['id'] for t in response.json()['tasks']], [self.task.id])

    # The refusals below are expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_task_context_and_hidden_task(self):
        self.assertEqual(self._post('task', self.dev, {'task_id': self.task.id}).json()['name'], 'Returns flow')
        # Not a member of the private project: same answer as a task that does not exist.
        self.assertEqual(self._post('task', self.other, {'task_id': self.task.id}).status_code, 404)
        self.assertEqual(self._post('task', self.dev, {'task_id': 999999}).status_code, 404)

    @mute_logger('odoo.http')
    def test_task_note(self):
        response = self._post('task_note', self.dev, {'task_id': self.task.id, 'body': 'Scope agreed'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Scope agreed', self.task.message_ids[0].body)
        self.assertEqual(self._post('task_note', self.dev, {'task_id': self.task.id, 'body': ''}).status_code, 422)
        response = self._post('task_note', self.dev, {'task_id': self.task.id, 'body': 'Returns fixed',
                                                       'keywords': ['reso', 'RMA']})
        self.assertEqual(response.json()['keywords'], 'reso, RMA')

    @mute_logger('odoo.http')
    def test_project_and_update(self):
        project = self.task.project_id
        project.allowed_internal_user_ids = [Command.link(self.dev.id)]
        context = self._post('project', self.dev, {'project_id': project.id}).json()
        self.assertEqual((context['name'], context['now']), ('Alfa', None))
        self.assertEqual(self._post('project', self.other, {'project_id': project.id}).status_code, 404)
        written = self._post('update', self.dev, {'project_id': project.id, 'name': 'Week 44', 'status': 'on_track',
                                                  'progress': 30, 'description': 'Returns flow designed.'})
        self.assertEqual(written.status_code, 200)
        self.assertEqual(self._post('project', self.dev, {'project_id': project.id}).json()['now']['id'], written.json()['id'])
        self.assertEqual(self._post('update', self.dev, {'project_id': project.id, 'name': 'x', 'status': 'green',
                                                         'description': 'y'}).status_code, 422)
        self.assertEqual(self._post('update', self.other, {'project_id': project.id, 'name': 'x', 'status': 'on_track',
                                                           'description': 'y'}).status_code, 404)
