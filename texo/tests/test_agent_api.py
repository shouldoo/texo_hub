# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger


def _hub_user(env, login):
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': login, 'login': login,
        'group_ids': [Command.link(env.ref('texo.group_texo_member').id)],
    })


@tagged('post_install', '-at_install')
class TestAgentApi(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = _hub_user(cls.env, 'api_member')
        cls.partners = cls.env['res.partner'].create([
            {'name': f'Agent API Partner {i}', 'city': 'Torino', 'comment': '<p>Prefers <b>email</b></p>'}
            for i in range(30)
        ])

    @property
    def api(self):
        return self.env['texo.api'].with_user(self.user)

    def test_search_read_caps_and_flattens(self):
        result = self.api._agent_search_read('res.partner', [('name', 'like', 'Agent API Partner')],
                                       ['name', 'comment'], limit=500)
        self.assertEqual(result['count'], 30)
        self.assertFalse(result['has_more'])
        self.assertEqual(result['records'][0]['comment'], 'Prefers *email*')
        result = self.api._agent_search_read('res.partner', [('name', 'like', 'Agent API Partner')], limit=10)
        self.assertEqual(result['count'], 10)
        self.assertTrue(result['has_more'])
        self.assertEqual(set(result['records'][0]), {'id', 'display_name'})

    def test_read_group(self):
        result = self.api._agent_read_group('res.partner', [('name', 'like', 'Agent API Partner')], ['city'])
        self.assertEqual(result['groups'], [{'city': 'Torino', '__count': 30}])

    def test_blocked_models(self):
        for model in ('ir.config_parameter', 'res.users.apikeys', 'res.config.settings', 'base.language.install'):
            with self.assertRaises(AccessError):
                self.api._agent_search_read(model)
        with self.assertRaises(UserError):
            self.api._agent_search_read('no.such.model')

    def test_sensitive_and_binary_fields(self):
        readable = self.api._agent_fields('res.users')['fields']
        names = {field['name'] for field in readable}
        self.assertIn('login', names)
        self.assertFalse(names & {'password', 'new_password', 'api_key_ids', 'image_1920', 'signature'})
        with self.assertRaises(UserError):
            self.api._agent_search_read('res.users', fields=['password'])
        with self.assertRaises(AccessError):
            self.api._agent_search_read('res.users', [('api_key_ids.name', '=', 'x')])

    def test_record_rules_apply(self):
        # Multi-company rule on res.partner: a contact of another company stays invisible.
        other_company = self.env['res.company'].create({'name': 'Other Company'})
        hidden = self.env['res.partner'].create({'name': 'Agent API Hidden', 'company_id': other_company.id})
        self.assertEqual(self.api._agent_search_read('res.partner', [('id', '=', hidden.id)])['count'], 0)

    def test_models_search(self):
        found = {m['model'] for m in self.api._agent_models('partner')['models']}
        self.assertIn('res.partner', found)
        self.assertFalse({m for m in found if m.startswith('ir.')})


@tagged('post_install', '-at_install')
class TestAgentApiRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = _hub_user(cls.env, 'api_http_member')
        cls.no_role = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'No role', 'login': 'api_http_no_role',
            'group_ids': [Command.link(cls.env.ref('base.group_user').id)]})

    def _post(self, route, payload, key=None):
        key = key or self.env['res.users.apikeys'].with_user(self.user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    def test_search_read_route(self):
        response = self._post('search_read', {'model': 'res.users', 'domain': [['id', '=', self.user.id]],
                                              'fields': ['login']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['records'], [{'id': self.user.id, 'login': 'api_http_member'}])

    # The refusals are expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_refusals(self):
        self.assertEqual(self._post('search_read', {'model': 'ir.config_parameter'}).status_code, 403)
        self.assertEqual(self._post('search_read', {'model': 'res.users', 'fields': ['password']}).status_code, 422)
        rpc_key = self.env['res.users.apikeys'].with_user(self.user)._generate(
            'rpc', 'test', datetime.now() + timedelta(days=1))
        self.assertEqual(self._post('fields', {'model': 'res.partner'}, key=rpc_key).status_code, 401)

    @mute_logger('odoo.http')
    def test_user_without_role(self):
        key = self.env['res.users.apikeys'].with_user(self.user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        self.user.group_ids = [Command.unlink(self.env.ref('texo.group_texo_member').id)]
        self.assertEqual(self._post('fields', {'model': 'res.partner'}, key=key).status_code, 403)
