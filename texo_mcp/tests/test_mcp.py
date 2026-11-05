# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.texo_memory.tests.common import clear_home

URL = '/texo/mcp'


@tagged('post_install', '-at_install')
class TestMcp(HttpCase):
    """The memory as a remote MCP server: the token of the person, the rules as instructions,
    the tools of the routes, the confirmation before a write."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        clear_home(cls.env)
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        project_user = Command.link(cls.env.ref('project.group_project_user').id)
        cls.lead = Users.create({
            'name': 'Lead', 'login': 'chmcp_lead', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id), project_user]})
        cls.norole = Users.create({'name': 'No role', 'login': 'chmcp_norole', 'lang': 'en_US', 'group_ids': [project_user]})
        cls.project = cls.env['project.project'].create({
            'name': 'Service flows', 'user_id': cls.lead.id, 'allowed_internal_user_ids': [Command.link(cls.lead.id)]})
        cls.env['res.partner'].create({'name': 'Neri Impianti', 'is_company': True})
        cls.env['memory.note'].with_user(cls.lead)._agent_note(
            'Language', 'Answer the customers in Italian.', state='active', severity='must')

    def key(self, user):
        return self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))

    def rpc(self, method, params=None, user=None, rid=1, key=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if rid is not None:
            message['id'] = rid
        if params is not None:
            message['params'] = params
        return self.url_open(URL, data=json.dumps(message), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key or self.key(user or self.lead)}'})

    def call(self, name, arguments=None, user=None):
        return self.rpc('tools/call', {'name': name, 'arguments': arguments or {}}, user=user).json()['result']

    def test_the_tools_of_the_external_sources_follow_their_module(self):
        names = {t['name'] for t in self.rpc('tools/list').json()['result']['tools']}
        installed = 'memory.source.item' in self.env
        self.assertEqual({'sources_find', 'sources_search', 'sources_card'} <= names, installed)
        if not installed:
            return
        self.env['memory.source.channel'].create({'name': 'Local news', 'website': 'https://news.example.com'})
        found = self.call('sources_find', {'query': 'nothing like this'})
        self.assertFalse(found['isError'])
        self.assertEqual(json.loads(found['content'][0]['text']), [])
        self.assertIn('Needs confirmation', self.call('sources_link', {'url': 'https://news.example.com/a'})['content'][0]['text'])
        linked = self.call('sources_link', {'url': 'https://news.example.com/a', 'title': 'A', 'confirm': True})
        self.assertEqual(json.loads(linked['content'][0]['text'])['state'], 'candidate')

    def test_initialize_gives_the_rules_of_the_session(self):
        result = self.rpc('initialize', {'protocolVersion': '2025-06-18'}).json()['result']
        self.assertEqual(result['protocolVersion'], '2025-06-18')
        self.assertEqual(result['serverInfo']['name'], 'texo')
        self.assertIn("Working memory (Texo)", result['instructions'])
        self.assertIn("- [must] Language: Answer the customers in Italian.", result['instructions'])
        self.assertIn("My role in the hub: lead.", result['instructions'])
        self.assertIn("Activities of the organisation", result['instructions'])
        self.assertEqual(self.rpc('initialize', {'protocolVersion': '1999-01-01'}).json()['result']['protocolVersion'],
                         '2025-06-18', "an unknown version gets the latest")
        self.assertEqual(self.rpc('ping').json()['result'], {})
        self.assertEqual(self.rpc('notifications/initialized', rid=None).status_code, 202)

    def test_tools_run_as_the_person_and_a_write_waits_for_the_yes(self):
        tools = {t['name']: t for t in self.rpc('tools/list').json()['result']['tools']}
        self.assertTrue({'context', 'search', 'note', 'lesson', 'document_write', 'query'} <= set(tools))
        self.assertEqual(tools['search']['inputSchema']['properties']['mode']['enum'], ['lexical', 'semantic', 'hybrid'])
        self.assertEqual(json.loads(self.call('whoami')['content'][0]['text'])['login'], 'chmcp_lead')
        arguments = {'name': 'Weekend', 'body': 'Releases only on Saturday.', 'project_id': self.project.id,
                     'state': 'active', 'severity': 'never'}
        refused = self.call('note', arguments)
        self.assertFalse(refused['isError'])
        self.assertIn("Needs confirmation", refused['content'][0]['text'])
        self.assertFalse(self.env['memory.note'].search([('name', '=', 'Weekend')]))
        written = json.loads(self.call('note', dict(arguments, confirm=True))['content'][0]['text'])
        self.assertEqual((written['state'], written['severity']), ('active', 'never'))
        pack = json.loads(self.call('context', {'project_id': self.project.id})['content'][0]['text'])
        self.assertEqual([r['title'] for r in pack['levels'][0]['rules']], ['Weekend'])
        found = json.loads(self.call('search', {'query': 'saturday releases', 'scope': 'notes'})['content'][0]['text'])
        self.assertEqual([r['id'] for r in found['results']], [written['id']])
        fact = json.loads(self.call('fact', {'name': 'Opening hours', 'body': 'Open 8 to 17.', 'project_id': self.project.id,
                                             'confirm': True})['content'][0]['text'])
        stale = self.call('fact_update', {'fact_id': fact['id'], 'body': 'x', 'expected_version': 'old', 'confirm': True})
        self.assertTrue(stale['isError'])
        # in the language of the request: the id of the fact is in every one
        self.assertIn(str(fact['id']), stale['content'][0]['text'])
        self.assertFalse(self.env['memory.note'].browse(fact['id']).body == 'x')
        pack = json.loads(self.call('context', {'project_id': self.project.id})['content'][0]['text'])
        self.assertEqual([f['title'] for f in pack['levels'][0]['facts']], ['Opening hours'])

    def test_a_refusal_is_an_error_result_and_writes_nothing(self):
        missing = self.call('read', {'note_id': 999999})
        self.assertTrue(missing['isError'])
        # the message is in the language of the request, as with auth='bearer': the id is in every one
        self.assertIn("999999", missing['content'][0]['text'])
        leak = self.call('lesson', {'finding': "Done for Service flows customer Neri Impianti, a fact of no use here.",
                                    'solution': "Nothing to reuse: this text names a customer and must be refused.",
                                    'confirm': True})
        self.assertTrue(leak['isError'])
        self.assertTrue(self.call('task', {})['isError'], "a required argument is missing")
        self.assertTrue(self.call('nope')['isError'])
        before = self.env['memory.note'].search_count([])
        self.assertTrue(self.call('note', {'name': 'x', 'body': 'y', 'state': 'bogus', 'confirm': True})['isError'])
        self.assertEqual(self.env['memory.note'].search_count([]), before)

    # The 401 of a wrong token is expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_the_token_and_the_role_are_checked(self):
        self.assertEqual(self.rpc('tools/list', key='not-a-key').status_code, 401)
        # a token made while the person had a role, the role taken away afterwards
        member = self.env.ref('texo.group_texo_member')
        self.norole.group_ids = [Command.link(member.id)]
        key = self.key(self.norole)
        self.norole.group_ids = [Command.unlink(member.id)]
        answer = self.rpc('tools/list', key=key).json()
        self.assertEqual(answer['error']['code'], -32001)
        bad = self.url_open(URL, data='{not json', headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {self.key(self.lead)}'}).json()
        self.assertEqual(bad['error']['code'], -32700)
        self.assertEqual(self.rpc('resources/list').json()['error']['code'], -32601)

    def test_the_memory_comes_back_as_open_knowledge_format(self):
        names = [t['name'] for t in self.rpc('tools/list').json()['result']['tools']]
        self.assertIn('log', names)
        self.assertIn('Open Knowledge Format', self.rpc('initialize', {}).json()['result']['instructions'])
        written = json.loads(self.call('note', {'name': 'Tests', 'body': 'Run the tests before a push.', 'state': 'active',
                                                'project_id': self.project.id, 'generated_by': 'claude-code/2.1',
                                                'confirm': True})['content'][0]['text'])
        # an OKF answer is markdown as it is, each file after its path
        text = self.call('read', {'concept': written['concept'], 'format': 'okf'})['content'][0]['text']
        self.assertTrue(text.startswith(f"<!-- okf: rules/{written['id']}.md -->\n---\ntype: \"Rule\"\n"))
        self.assertIn('generated: {"by": "claude-code/2.1"', text)
        self.call('update', {'project_id': self.project.id, 'name': 'Week 44', 'status': 'on_track',
                             'description': 'Started.', 'confirm': True})
        pack = self.call('context', {'project_id': self.project.id, 'format': 'okf'})['content'][0]['text']
        self.assertIn('<!-- okf: index.md -->', pack)
        self.assertIn('<!-- okf: log.md -->', pack)
        log = self.call('log', {'project_id': self.project.id})['content'][0]['text']
        self.assertIn(f"<!-- okf: projects/{self.project.id}/log.md -->", log)
