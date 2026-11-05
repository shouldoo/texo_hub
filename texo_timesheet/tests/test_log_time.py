# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestLogTime(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        groups = [Command.link(cls.env.ref('texo.group_texo_member').id),
                  Command.link(cls.env.ref('project.group_project_user').id),
                  Command.link(cls.env.ref('hr_timesheet.group_hr_timesheet_user').id)]
        cls.dev = Users.create({'name': 'Dev', 'login': 'cht_dev', 'group_ids': groups})
        cls.env['hr.employee'].create({'name': 'Dev', 'user_id': cls.dev.id})
        cls.nobody = Users.create({'name': 'No employee', 'login': 'cht_nobody', 'group_ids': groups})
        cls.project = cls.env['project.project'].create({
            'name': 'Alfa', 'allowed_internal_user_ids': [Command.link(cls.dev.id), Command.link(cls.nobody.id)]})
        cls.task = cls.env['project.task'].create({
            'name': 'Returns flow', 'project_id': cls.project.id, 'allocated_hours': 8,
            'user_ids': [Command.link(cls.dev.id), Command.link(cls.nobody.id)]})

    def _post(self, user, payload):
        key = self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open('/texo/v1/project/log_time', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    def test_hours_land_on_the_task_as_the_user(self):
        response = self._post(self.dev, {'task_id': self.task.id, 'hours': 1.5, 'description': 'Route analysed with the customer'})
        self.assertEqual(response.status_code, 200)
        line = self.env['account.analytic.line'].browse(response.json()['timesheet_id'])
        self.assertEqual(line.user_id, self.dev)
        self.assertEqual(line.unit_amount, 1.5)
        self.assertEqual(response.json()['task_hours'], 1.5)
        context = self.task.with_user(self.dev)._texo_context()
        self.assertEqual(context['worklog'][0]['what'], 'Route analysed with the customer')
        self.assertEqual(context['hours'], {'spent': 1.5, 'allocated': 8.0})

    # The refusals are expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_refusals(self):
        self.assertEqual(self._post(self.dev, {'task_id': self.task.id, 'hours': 0, 'description': 'x'}).status_code, 422)
        self.assertEqual(self._post(self.dev, {'task_id': self.task.id, 'hours': 'two', 'description': 'x'}).status_code, 422)
        self.assertEqual(self._post(self.dev, {'task_id': self.task.id, 'hours': 1, 'description': ''}).status_code, 422)
        self.assertEqual(self._post(self.dev, {'task_id': 999999, 'hours': 1, 'description': 'x'}).status_code, 404)
        with self.assertRaises(UserError):
            self.task.with_user(self.nobody)._texo_log_time(1, 'no employee')
