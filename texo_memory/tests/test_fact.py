# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .common import MemoryCase


@tagged('post_install', '-at_install')
class TestFact(MemoryCase):
    """What a customer, a project or a task is, one fact at a time: written as it is by
    whoever may write on its anchor, given by title in the pack, never overwritten."""

    def fact_as(self, user, **kwargs):
        vals = {'name': 'Warehouse', 'body': 'Two locations: the shop and the yard.', 'project_id': self.project.id}
        vals.update(kwargs)
        return self.env['memory.note'].with_user(user)._agent_note(kind='fact', **vals)

    def test_a_member_writes_a_fact_and_the_pack_gives_its_title(self):
        written = self.fact_as(self.member, keywords=['magazzino', 'ubicazioni'])
        fact = self.env['memory.note'].browse(written['id'])
        self.assertEqual((fact.state, fact.verified, fact.customer_id), ('active', fields.Date.today(), self.customer))
        on_task = self.fact_as(self.member, name='Returns agreed', body='Returns within 30 days.', project_id=None,
                               task_id=self.task.id)
        pack = self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id)
        levels = {(l['model'], l['id']): l for l in pack['levels']}
        self.assertEqual([f['id'] for f in levels[('project.task', self.task.id)]['facts']], [on_task['id']])
        project_facts = levels[('project.project', self.project.id)]['facts']
        self.assertEqual([f['title'] for f in project_facts], ['Warehouse'])
        self.assertNotIn('text', project_facts[0], "an outline: the text with memory/read")
        read = fact.with_user(self.member)._agent_read()
        self.assertEqual(read['body'], 'Two locations: the shop and the yard.')
        self.assertEqual(read['keywords'], 'magazzino, ubicazioni')
        self.assertTrue(read['version'])
        with self.assertRaises(UserError):
            self.fact_as(self.outsider)

    def test_the_same_text_on_the_same_record_is_written_once(self):
        """A session that proposes a note twice, a call retried: the existing note comes back, with
        existing true; another title or text, another record or another kind is a new note."""
        first = self.fact_as(self.member)
        again = self.fact_as(self.member, name=' warehouse', body='  Two locations:  the shop and the yard. ')
        self.assertEqual((again['id'], again['existing']), (first['id'], True))
        self.assertNotIn('existing', first)
        self.assertNotEqual(self.fact_as(self.member, name='Warehouse (bis)')['id'], first['id'], "another title")
        elsewhere = self.fact_as(self.member, project_id=None, task_id=self.task.id)
        self.assertNotEqual(elsewhere['id'], first['id'])
        rule = self.env['memory.note'].with_user(self.lead)._agent_note(
            'Warehouse', 'Two locations: the shop and the yard.', project_id=self.project.id, kind='rule', state='active')
        self.assertNotEqual(rule['id'], first['id'], "another kind")
        self.assertEqual(self.env['memory.note'].with_user(self.lead)._agent_note(
            'Warehouse', 'Two locations: the shop and the yard.', project_id=self.project.id, kind='rule')['id'], rule['id'])
        self.env['memory.note'].browse(first['id']).with_user(self.lead)._agent_set_state('archived')
        self.assertNotEqual(self.fact_as(self.member)['id'], first['id'], "an archived note is not the live one")

    def test_append_merges_and_update_needs_the_version_read(self):
        fact = self.env['memory.note'].browse(self.fact_as(self.member)['id'])
        version = fact.with_user(self.member)._agent_read()['version']
        appended = fact.with_user(self.lead)._agent_append('A third location from November.', keywords='ubicazioni')
        self.assertIn('A third location from November.', appended['body'])
        self.assertIn(', Lead]', appended['body'], "the paragraph is signed")
        self.assertEqual(fact.keywords, 'ubicazioni')
        # the version read before the append is old: a replacement built on it is refused
        with self.assertRaises(UserError):
            fact.with_user(self.member)._agent_update(version, body='Only the shop.')
        current = fact.with_user(self.member)._agent_read()['version']
        updated = fact.with_user(self.member)._agent_update(current, body='Only the shop.')
        self.assertEqual(updated['body'], 'Only the shop.')
        with self.assertRaises(UserError):
            fact.with_user(self.member)._agent_update()

    def test_stale_expired_and_who_archives(self):
        fact = self.env['memory.note'].browse(self.fact_as(self.member)['id'])
        fact.verified = fields.Date.today() - timedelta(days=200)
        Note = self.env['memory.note'].with_user(self.member)
        [outline] = Note._agent_context(project_id=self.project.id)['levels'][0]['facts']
        self.assertEqual(outline['stale'], 'unverified')
        fact.with_user(self.member)._agent_update(verified=True)
        self.assertEqual(fact.verified, fields.Date.today())
        fact.expires = fields.Date.today() - timedelta(days=1)
        self.assertNotIn('facts', Note._agent_context(project_id=self.project.id)['levels'][0], "expired: out of the pack")
        self.assertEqual(Note._agent_search('locations', scope='facts'), [], "expired: out of the search")
        fact.expires = False
        other = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other', 'login': 'chm_fact_other',
            'group_ids': [Command.link(self.env.ref('texo.group_texo_member').id),
                          Command.link(self.env.ref('project.group_project_user').id)]})
        self.project.allowed_internal_user_ids = [Command.link(other.id)]
        with self.assertRaises(AccessError):
            fact.with_user(other)._agent_set_state('archived')
        fact.with_user(self.member)._agent_set_state('archived')
        self.assertEqual(fact.state, 'archived')

    def test_search_by_keyword_and_only_what_the_person_may_read(self):
        readable = self.env['memory.note'].browse(self.fact_as(
            self.member, name='Picking', body='One picking per order, wave picking for the shop.',
            keywords='prelievo')['id'])
        hidden = self.env['project.project'].create({'name': 'Hidden', 'privacy_visibility': 'followers'})
        Fact = self.env['memory.note']
        for i in range(8):
            # stronger matches the member may not read: the search reaches past them
            Fact.create({'name': f'Prelievo picking {i}', 'body': 'prelievo picking prelievo picking', 'kind': 'fact',
                         'keywords': 'prelievo', 'project_id': hidden.id})
        found = self.env['memory.note'].with_user(self.member)._agent_search('prelievo', scope='facts', limit=1)
        self.assertEqual([(f['id'], f['fact']) for f in found], [(readable.id, True)])
        self.assertEqual(self.env['memory.note'].with_user(self.outsider)._agent_search('prelievo', scope='facts'), [])
        # the access rules are in the query: more stronger matches the member may not read than any
        # window could hold, and the readable one is still found
        Fact.create([{'name': f'Prelievo {i}', 'body': 'prelievo picking prelievo picking', 'kind': 'fact',
                      'keywords': 'prelievo', 'project_id': hidden.id} for i in range(500)])
        found = self.env['memory.note'].with_user(self.member)._agent_search('prelievo', scope='facts', limit=1)
        self.assertEqual([f['id'] for f in found], [readable.id])

    def test_optout_deletes_the_facts_of_the_customer(self):
        fact = self.env['memory.note'].browse(self.fact_as(self.lead)['id'])
        home = self.env['memory.note'].browse(self.fact_as(self.lead, project_id=None)['id'])
        self.assertEqual(home.company_id, self.env.company, "no anchor: the organisation itself")
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Admin', 'login': 'chm_fact_admin',
            'group_ids': [Command.link(self.env.ref('texo.group_texo_admin').id)]})
        wizard = self.env['memory.optout.wizard'].with_user(admin).create({
            'partner_id': self.customer.id, 'reason': 'request', 'confirm_name': 'Rossi Meccanica'})
        self.assertEqual(wizard.fact_count, 1)
        self.assertEqual(wizard.action_optout()['deleted']['facts'], 1)
        self.assertFalse(fact.exists())
        self.assertTrue(home.exists(), "a fact of the organisation is not the customer's")


@tagged('post_install', '-at_install')
class TestFactRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lead = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Lead', 'login': 'chm_fact_lead', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id),
                          Command.link(cls.env.ref('project.group_project_user').id)]})
        cls.project = cls.env['project.project'].create({
            'name': 'Service flows', 'user_id': cls.lead.id, 'allowed_internal_user_ids': [Command.link(cls.lead.id)]})

    def _post(self, route, payload):
        key = self.env['res.users.apikeys'].with_user(self.lead)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    # The 422 and the 404 are expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_write_append_update_read_state(self):
        written = self._post('memory/fact', {'name': 'Opening hours', 'body': 'Open 8 to 17.', 'project_id': self.project.id,
                                             'keywords': ['orari']}).json()
        self.assertEqual(written['body'], 'Open 8 to 17.')
        appended = self._post('memory/fact_append', {'fact_id': written['id'], 'text': 'Closed in August.'}).json()
        self.assertIn('Closed in August.', appended['body'])
        stale = self._post('memory/fact_update', {'fact_id': written['id'], 'body': 'x', 'expected_version': 'old'})
        self.assertEqual(stale.status_code, 422)
        updated = self._post('memory/fact_update', {'fact_id': written['id'], 'body': 'Open 9 to 18.',
                                                    'expected_version': appended['version']}).json()
        self.assertEqual(updated['body'], 'Open 9 to 18.')
        self.assertEqual(self._post('memory/read', {'fact_id': written['id']}).json()['body'], 'Open 9 to 18.')
        self.assertEqual(self._post('memory/state', {'fact_id': written['id'], 'state': 'archived'}).json()['state'],
                         'archived')
        self.assertEqual(self._post('memory/read', {'fact_id': 999999}).status_code, 404)
