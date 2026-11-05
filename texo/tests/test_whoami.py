# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

WHOAMI = '/texo/v1/whoami'


@tagged('post_install', '-at_install')
class TestWhoami(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Lead', 'login': 'hub_lead_http',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id)],
        })

    def _key(self, scope='texo'):
        return self.env['res.users.apikeys'].with_user(self.lead)._generate(
            scope, 'test', datetime.now() + timedelta(days=30))

    def _post(self, url, key):
        return self.url_open(url, data=json.dumps({}), headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
        })

    def test_valid_hub_token_returns_identity(self):
        response = self._post(WHOAMI, self._key())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'uid': self.lead.id, 'login': 'hub_lead_http', 'name': 'Hub Lead', 'role': 'lead',
        })
        self.assertTrue(self.lead.texo_last_seen)

    def test_rpc_key_refused(self):
        self.assertEqual(self._post(WHOAMI, self._key(scope='rpc')).status_code, 401)

    def test_hub_token_refused_by_json2(self):
        response = self._post('/json/2/res.users/context_get', self._key())
        self.assertEqual(response.status_code, 401)

    def test_unknown_token_refused(self):
        self.assertEqual(self._post(WHOAMI, 'not-a-real-key-0123456789abcdef').status_code, 401)

    # The refusal is expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_user_without_role_forbidden(self):
        key = self._key()
        self.lead.group_ids = [Command.unlink(self.env.ref('texo.group_texo_lead').id),
                               Command.unlink(self.env.ref('texo.group_texo_member').id)]
        self.assertEqual(self._post(WHOAMI, key).status_code, 403)

    def test_archived_user_refused(self):
        key = self._key()
        self.lead.active = False
        self.assertEqual(self._post(WHOAMI, key).status_code, 401)
