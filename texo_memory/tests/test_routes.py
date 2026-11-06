# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .common import CLEAN_FINDING, CLEAN_SOLUTION, clear_home, sector_activities


@tagged('post_install', '-at_install')
class TestMemoryRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        clear_home(cls.env)
        sector_activities(cls.env)
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        project_user = Command.link(cls.env.ref('project.group_project_user').id)
        # English users: the assertions read the messages of the routes.
        cls.member = Users.create({
            'name': 'Member', 'login': 'chm_http_member', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id), project_user]})
        cls.lead = Users.create({
            'name': 'Lead', 'login': 'chm_http_lead', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id), project_user]})
        cls.customer = cls.env['res.partner'].create({'name': 'Neri Impianti'})
        cls.project = cls.env['project.project'].create({
            'name': 'Service flows', 'partner_id': cls.customer.id, 'privacy_visibility': 'followers',
            'user_id': cls.lead.id, 'allowed_internal_user_ids': [Command.link(cls.member.id), Command.link(cls.lead.id)],
        })
        cls.task = cls.env['project.task'].create({
            'name': 'Service route', 'project_id': cls.project.id, 'user_ids': [Command.link(cls.member.id)]})

    def _post(self, route, user, payload):
        key = self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/memory/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    def test_rules_carry_the_role_and_the_rules_of_the_organisation(self):
        self.assertEqual(self._post('rules', self.member, {}).json()['role'], 'member')
        self.assertIn('Working memory', self._post('rules', self.lead, {}).json()['rules'])
        self._post('note', self.lead, {'name': 'Language', 'body': 'Answer in Italian.', 'state': 'active'})
        rules = self._post('rules', self.member, {}).json()
        self.assertTrue(rules['rules'].endswith("- [must] Language: Answer in Italian."))
        self._post('note', self.lead, {'name': 'Deploy', 'body': 'Never on Friday.', 'state': 'active',
                                       'severity': 'never', 'activities': ['deploy']})
        coding = self._post('rules', self.member, {'activity': 'code'}).json()
        self.assertEqual([r['title'] for r in coding['company_rules']], ['Language'])
        deploying = self._post('rules', self.member, {'activity': 'deploy'}).json()
        self.assertEqual([(r['title'], r['severity']) for r in deploying['company_rules']],
                         [('Language', 'must'), ('Deploy', 'never')])
        self.assertEqual([r['title'] for r in rules['company_rules']], ['Language'])

    # The refusals below are expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_note_lesson_state_context_search_read(self):
        active = self._post('note', self.lead, {'name': 'Version', 'body': 'Never upgrade on Friday.',
                                                'project_id': self.project.id, 'state': 'active'})
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()['state'], 'active')
        # A member may not ask for an active note: 403, nothing stored.
        refused = self._post('note', self.member, {'name': 'x', 'body': 'A member tries active.',
                                                   'project_id': self.project.id, 'state': 'active'})
        self.assertEqual(refused.status_code, 403)
        # The kinds of the previous versions are refused with the way to go.
        old_kind = self._post('note', self.member, {'kind': 'decision', 'name': 'x', 'body': 'An old client.',
                                                    'task_id': self.task.id})
        self.assertEqual(old_kind.status_code, 422)
        self.assertIn('task', old_kind.json()['message'])
        draft = self._post('note', self.member, {'name': 'Weekend', 'body': 'Releases only on Saturday.',
                                                 'project_id': self.project.id})
        self.assertEqual(draft.json()['state'], 'draft')
        finding = self._post('lesson', self.member, {'tags': ['migration'], 'finding': CLEAN_FINDING,
                                                     'solution': CLEAN_SOLUTION, 'applies_to': 'Odoo 20.0'})
        self.assertEqual(finding.status_code, 200)
        self.assertEqual((finding.json()['kind'], finding.json()['state']), ('finding', 'draft'))
        leak = self._post('lesson', self.member, {'tags': ['migration'], 'finding': CLEAN_FINDING,
                                                  'solution': CLEAN_SOLUTION + " Done for Neri Impianti."})
        self.assertEqual(leak.status_code, 422)
        # The reason reaches the client, in the language of the request.
        self.assertIn('finding', leak.json()['message'])
        self.assertEqual(self._post('lesson', self.member, {'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION,
                                                            'state': 'active'}).status_code, 403)
        self.assertEqual(self._post('state', self.member, {'note_id': draft.json()['id'], 'state': 'active'}).status_code, 403)
        activated = self._post('state', self.lead, {'note_id': draft.json()['id'], 'state': 'active'})
        self.assertEqual(activated.json()['state'], 'active')
        pack = self._post('context', self.member, {'task_id': self.task.id}).json()
        self.assertEqual(pack['role'], 'member')
        self.assertNotIn('pending_lessons', pack)
        self.assertEqual([r['title'] for r in pack['levels'][1]['rules']], ['Version', 'Weekend'])
        # The finding is still a draft: a member does not find it, the lead sees it in the pack and activates it.
        self.assertEqual(self._post('search', self.member, {'query': 'uom_id purchase', 'scope': 'lessons'}).json()['results'], [])
        lead_pack = self._post('context', self.lead, {'task_id': self.task.id}).json()
        self.assertEqual([l['id'] for l in lead_pack['pending_lessons']], [finding.json()['id']])
        self.assertEqual(self._post('state', self.lead, {'lesson_id': finding.json()['id'], 'state': 'active'}).json()['state'], 'active')
        answer = self._post('search', self.member, {'query': 'uom_id purchase', 'scope': 'lessons'}).json()
        found = answer['results']
        self.assertEqual(len(found), 1)
        # how the search ran: the mode used, what the reranker did, how long it took
        self.assertEqual((answer['mode'], answer['rerank']), ('lexical', 'off'))
        self.assertIsInstance(answer['latency_ms'], int)
        lesson = self._post('read', self.member, {'lesson_id': found[0]['id']}).json()
        self.assertEqual(lesson['solution'], CLEAN_SOLUTION)
        self.assertEqual(self._post('read', self.member, {'note_id': 999999}).status_code, 404)
        review = self._post('review', self.lead, {}).json()
        self.assertEqual(review['drafts'], [])
        self.assertIn('duplicates', review)
        confirmed = self._post('confirm', self.lead, {'note_id': active.json()['id'], 'expires': '2030-01-01'})
        self.assertEqual(confirmed.json()['expires'], '2030-01-01')
        self.assertEqual(self._post('confirm', self.member, {'note_id': active.json()['id']}).status_code, 403)

    def test_show_expired_and_the_metrics(self):
        """An expired fact stays out of the search unless asked for, and then says it is stale; the
        metrics of the memory count the notes by kind and state."""
        expired = self._post('fact', self.lead, {'name': 'Old tariff', 'body': 'The tariff of 2024 was flat.',
                                                 'project_id': self.project.id, 'expires': '2024-12-31'}).json()
        self.assertEqual(self._post('search', self.lead, {'query': 'tariff', 'scope': 'facts'}).json()['results'], [])
        found = self._post('search', self.lead, {'query': 'tariff', 'scope': 'facts', 'show_expired': True}).json()
        self.assertEqual([(r['id'], r['stale']) for r in found['results']], [(expired['id'], 'expired')])
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Admin', 'login': 'chm_http_admin',
            'group_ids': [Command.link(self.env.ref('texo.group_texo_admin').id)]})
        key = self.env['res.users.apikeys'].with_user(admin)._generate('texo', 'test', datetime.now() + timedelta(days=1))
        lines = self.url_open('/texo/metrics', headers={'Authorization': f'Bearer {key}'}).text.splitlines()
        self.assertIn('# TYPE texo_memory_notes gauge', lines)
        self.assertTrue(any(line.startswith('texo_memory_notes{kind="fact",state="active"} ') for line in lines), lines)
        self.assertTrue(any(line.startswith('texo_memory_episodes ') for line in lines))

    @mute_logger('odoo.http')
    def test_a_read_only_token_reads_and_never_writes_and_no_credential_enters(self):
        key = self.env['res.users.apikeys'].with_user(self.lead).with_context(texo_read_only=True)._generate(
            'texo', 'reads', datetime.now() + timedelta(days=1))

        def post(route, payload):
            return self.url_open(f'/texo/v1/memory/{route}', data=json.dumps(payload), headers={
                'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

        self.assertEqual(post('search', {'query': 'anything'}).status_code, 200)
        self.assertEqual(post('context', {'task_id': self.task.id}).status_code, 200)
        refused = post('note', {'name': 'Tariff', 'body': 'The tariff is flat.', 'kind': 'fact', 'project_id': self.project.id})
        self.assertEqual(refused.status_code, 403)
        self.assertIn('read-only', refused.json()['message'])
        # a credential never enters the memory, whoever writes
        leak = self._post('fact', self.lead, {'name': 'Access', 'body': 'TEXO_HUB_TOKEN=4f2a9c1b8d7e6f5a of the stage',
                                             'project_id': self.project.id})
        self.assertEqual(leak.status_code, 422)
        self.assertIn('credential', leak.json()['message'])
        self.assertEqual(self._post('fact', self.lead, {'name': 'Access', 'body': 'The stage asks a password at login.',
                                                        'project_id': self.project.id}).status_code, 200)
