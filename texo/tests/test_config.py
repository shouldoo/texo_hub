# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

DOCS = {'id': 'docs', 'type': 'source', 'driver': 'git-mirror', 'data_class': 'public',
        'guide': 'The manual of the software.', 'repo': 'github.com/example/docs', 'ref': 'v2', 'paths': ['docs']}
DRIVE = {'id': 'drive', 'type': 'connector', 'driver': 'mcp-http', 'data_class': 'customer', 'writes': 'confirm',
         'url': 'https://drive.example/mcp', 'auth': 'env:DRIVE_TOKEN'}


def users(env):
    Users = env['res.users'].with_context(no_reset_password=True)
    return {role: Users.create({'name': role.title(), 'login': f'config_{role}',
                                'group_ids': [Command.link(env.ref(f'texo.group_texo_{role}').id)]})
            for role in ('member', 'lead', 'admin')}


@tagged('post_install', '-at_install')
class TestConfig(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users = users(cls.env)
        cls.env.company.texo_slug = False

    def config(self, user='admin'):
        return self.env['texo.config'].with_user(self.users[user])

    def test_only_an_administrator_writes_the_configuration(self):
        for role in ('member', 'lead'):
            with self.assertRaises(AccessError):
                self.config(role)._agent_set_config(packs=[], apply=True)

    def test_a_dry_run_writes_nothing_then_apply_and_every_role_reads(self):
        payload = {'packs': [{'name': 'odoo_partner', 'version': 'v1.0.0'}], 'threads': [DOCS, DRIVE],
                   'slug': 'acme'}
        dry = self.config()._agent_set_config(**payload)
        self.assertEqual((dry['applied'], dry['counts']), (False, {'updated': 1, 'created': 3}))
        self.assertFalse(self.env['texo.thread'].search([]))
        self.assertFalse(self.env.company.texo_slug)
        self.config()._agent_set_config(apply=True, **payload)
        config = self.config('member')._agent_config()
        self.assertEqual(config['organisation'], 'acme')
        self.assertEqual(config['packs'], [{'name': 'odoo_partner', 'version': 'v1.0.0'}])
        self.assertEqual({t['id']: t for t in config['threads']}['docs'],
                         dict(DOCS, writes='never'), "a thread reads back as its declaration")
        again = self.config()._agent_set_config(apply=True, **payload)
        self.assertEqual(again['counts'], {'unchanged': 3})

    def test_what_left_the_configuration_is_archived_never_deleted(self):
        self.config()._agent_set_config(threads=[DOCS, DRIVE], apply=True)
        result = self.config()._agent_set_config(threads=[dict(DOCS, ref='v3')], apply=True)
        self.assertEqual({i['key']: i['status'] for i in result['items']}, {'docs': 'updated', 'drive': 'archived'})
        self.assertEqual(result['items'][0]['changes'], ['settings'])
        drive = self.env['texo.thread'].with_context(active_test=False).search([('code', '=', 'drive')])
        self.assertFalse(drive.active)
        self.assertEqual([t['id'] for t in self.config('member')._agent_config()['threads']], ['docs'])
        self.config()._agent_set_config(threads=[DOCS, DRIVE], apply=True)
        self.assertTrue(drive.active, "a thread declared again comes back")

    def test_no_credential_is_ever_stored(self):
        with self.assertRaisesRegex(UserError, 'env:NAME'):
            self.config()._agent_set_config(threads=[dict(DRIVE, auth='abc123')])
        with self.assertRaisesRegex(UserError, 'env:NAME'):
            self.config()._agent_set_config(threads=[dict(DOCS, driver='mcp-stdio', env={'API_KEY': 'abc'})])
        self.assertFalse(self.env['texo.thread'].search([]), "a refused dry run leaves nothing either")

    def test_the_rules_of_a_declaration(self):
        for wrong in (dict(DOCS, writes='confirm'), dict(DRIVE, data_class='public'), dict(DOCS, id='memoria'),
                      dict(DOCS, id='Docs Folder')):
            with self.assertRaises(UserError, msg=wrong['id']):
                self.config()._agent_set_config(threads=[wrong], apply=True)
        with self.assertRaises(UserError):
            self.config()._agent_set_config(packs=[{'name': 'odoo_partner', 'version': 'latest'}], apply=True)
        with self.assertRaises(UserError):
            self.config()._agent_set_config(threads=[DOCS, DOCS])

    def test_the_slug_defaults_to_the_name_of_the_company(self):
        self.env.company.name = 'Acme & Sons S.r.l.'
        self.assertEqual(self.config('member')._agent_config()['organisation'], 'acme_sons_s_r_l')


@tagged('post_install', '-at_install')
class TestConfigRoutes(HttpCase):

    def _post(self, route, user, payload):
        key = self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    # The refusal below is expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_the_routes(self):
        people = users(self.env)
        self.assertEqual(self._post('admin/config', people['lead'], {'threads': [DOCS]}).status_code, 403)
        answer = self._post('admin/config', people['admin'], {'threads': [DOCS], 'apply': True})
        self.assertEqual(answer.json()['counts'], {'created': 1})
        config = self._post('config', people['member'], {}).json()
        self.assertEqual([t['id'] for t in config['threads']], ['docs'])
