# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from ..models.texo_metrics import render


@tagged('post_install', '-at_install')
class TestMetrics(HttpCase):
    """The metrics route: an administrator reads them with a hub token, the exposition format, the
    gauges of the base module; a member is refused."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.admin = Users.create({'name': 'Metrics Admin', 'login': 'metrics_admin',
                                  'group_ids': [Command.link(cls.env.ref('texo.group_texo_admin').id)]})
        cls.member = Users.create({'name': 'Metrics Member', 'login': 'metrics_member',
                                   'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id)]})

    def _get(self, user):
        key = self.env['res.users.apikeys'].with_user(user)._generate('texo', 'test', datetime.now() + timedelta(days=1))
        return self.url_open('/texo/metrics', headers={'Authorization': f'Bearer {key}'})

    def test_an_administrator_reads_the_metrics(self):
        answer = self._get(self.admin)
        self.assertEqual(answer.status_code, 200)
        self.assertTrue(answer.headers['Content-Type'].startswith('text/plain'))
        lines = answer.text.splitlines()
        self.assertIn('# TYPE texo_users gauge', lines)
        self.assertTrue(any(line.startswith('texo_users{role="admin"} ') for line in lines))
        self.assertTrue(any(line.startswith('texo_info{version="') for line in lines))

    @mute_logger('odoo.http')
    def test_a_member_and_a_stranger_are_refused(self):
        self.assertEqual(self._get(self.member).status_code, 403)
        self.assertEqual(self.url_open('/texo/metrics').status_code, 401)

    def test_the_format(self):
        text = render([{'name': 'a', 'help': 'A thing', 'type': 'gauge', 'labels': {'k': 'v"q'}, 'value': 2},
                       {'name': 'a', 'help': 'A thing', 'type': 'gauge', 'labels': {}, 'value': True}])
        self.assertEqual(text, '# HELP a A thing\n# TYPE a gauge\na{k="v\\"q"} 2\na 1\n')
