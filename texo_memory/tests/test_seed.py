# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .common import MemoryCase


def industry_seed(**changes):
    """The seed of a fictional sector, as the CLI sends it from hub/seed.toml."""
    seed = {
        'industry': 'bakery',
        'activities': [{'code': 'baking', 'name': 'Baking', 'description': 'Recipes and ovens.', 'sequence': 30}],
        'sections': [{'code': 'hygiene', 'name': 'Hygiene', 'description': 'Food safety and its checks.'}],
        'rules': [
            {'key': 'allergens', 'name': 'Allergens', 'body': 'Never publish a recipe without its allergens.',
             'severity': 'never', 'activities': ['baking', 'communication'], 'section': 'hygiene',
             'keywords': 'allergeni, allergens'},
            {'key': 'oven_log', 'name': 'Oven log', 'body': 'Record the temperature of every batch.'},
        ],
        'project_templates': [
            {'key': 'new_shop', 'name': 'New shop', 'description': '<p>Opening a shop.</p>',
             'tasks': [{'name': 'Find the premises'},
                       {'name': 'Hygiene plan', 'description': '<p>The HACCP plan.</p>'}]},
        ],
    }
    seed.update(changes)
    return seed


@tagged('post_install', '-at_install')
class TestSeed(MemoryCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Admin', 'login': 'chm_seed_admin',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_admin').id)]})

    def seed(self, user=None, **kwargs):
        return self.env['memory.seed'].with_user(user or self.admin)._agent_seed(**kwargs)

    def statuses(self, result):
        return {(item['kind'], item['key']): item['status'] for item in result['items']}

    def test_only_an_administrator_seeds(self):
        for user in (self.member, self.lead):
            with self.assertRaises(AccessError):
                self.seed(user, **industry_seed())
        with self.assertRaises(UserError):
            self.seed(**industry_seed(industry='Bakery Shop'))
        with self.assertRaises(UserError):
            self.seed(**industry_seed(activities=[{'code': 'baking'}, {'code': 'baking'}]))

    def test_a_dry_run_writes_nothing(self):
        result = self.seed(**industry_seed())
        self.assertFalse(result['applied'])
        self.assertEqual(result['counts'], {'created': 5})
        self.assertFalse(self.env['memory.note.activity'].search([('code', '=', 'baking')]))
        self.assertFalse(self.env['memory.note'].search([('seed_key', '=like', 'bakery/%')]))

    def test_apply_creates_then_a_second_run_changes_nothing(self):
        result = self.seed(apply=True, **industry_seed())
        self.assertEqual(result['counts'], {'created': 5})
        rule = self.env['memory.note'].search([('seed_key', '=', 'bakery/rule/allergens')])
        self.assertRecordValues(rule, [{'kind': 'rule', 'state': 'active', 'severity': 'never',
                                        'company_id': self.env.company.id, 'verified_by_id': self.admin.id}])
        self.assertEqual(sorted(rule.rule_activity_ids.mapped('code')), ['baking', 'communication'])
        self.assertEqual(rule.section_id.code, 'hygiene')
        template = self.env['project.project'].search([('seed_key', '=', 'bakery/project_template/new_shop')])
        self.assertTrue(template.is_template)
        self.assertEqual(template.task_ids.sorted('sequence').mapped('name'), ['Find the premises', 'Hygiene plan'])
        self.assertIn("Never publish a recipe", self.env['memory.note'].with_user(self.member)._agent_rules_text(
            "Common.", activity='baking')['rules'], "a rule of the seed binds the sessions of the organisation")
        again = self.seed(apply=True, **industry_seed())
        self.assertEqual(again['counts'], {'unchanged': 5})

    def test_what_a_lead_changed_is_kept_and_the_rest_follows_the_seed(self):
        self.seed(apply=True, **industry_seed())
        rule = self.env['memory.note'].search([('seed_key', '=', 'bakery/rule/oven_log')])
        rule.with_user(self.lead).body = 'Record the temperature and the time of every batch.'
        seed = industry_seed()
        seed['activities'][0]['description'] = 'Recipes, ovens and proofing.'
        seed['rules'][1]['body'] = 'Record the oven temperature of every batch.'
        del seed['rules'][0]
        result = self.seed(**seed)
        self.assertEqual(self.statuses(result), {
            ('activity', 'baking'): 'updated', ('section', 'hygiene'): 'unchanged',
            ('rule', 'oven_log'): 'kept', ('rule', 'allergens'): 'left_seed',
            ('project_template', 'new_shop'): 'unchanged'})
        kept = next(item for item in result['items'] if item['key'] == 'oven_log')
        self.assertEqual((kept['reason'], kept['changes']), ('changed_here', ['body']))
        self.seed(apply=True, **seed)
        self.assertEqual(self.env['memory.note.activity'].search([('code', '=', 'baking')]).description,
                         'Recipes, ovens and proofing.')
        self.assertEqual(rule.body, 'Record the temperature and the time of every batch.')
        self.assertTrue(self.env['memory.note'].search([('seed_key', '=', 'bakery/rule/allergens')]),
                        "an item that left the seed is reported, never deleted")

    def test_a_template_follows_the_seed_while_nobody_touched_it(self):
        self.seed(apply=True, **industry_seed())
        seed = industry_seed()
        seed['project_templates'][0]['tasks'].append({'name': 'Opening day'})
        self.assertEqual(self.statuses(self.seed(apply=True, **seed))[('project_template', 'new_shop')], 'updated')
        template = self.env['project.project'].search([('seed_key', '=', 'bakery/project_template/new_shop')])
        self.assertEqual(template.task_ids.sorted('sequence').mapped('name'),
                         ['Find the premises', 'Hygiene plan', 'Opening day'])

    def test_a_code_written_by_hand_is_left_alone(self):
        result = self.seed(apply=True, **industry_seed(
            activities=[{'code': 'communication', 'name': 'Talking to customers'}], sections=[], rules=[],
            project_templates=[]))
        self.assertEqual(result['items'][0]['status'], 'kept')
        self.assertEqual(result['items'][0]['reason'], 'not_from_seed')
        self.assertEqual(self.env.ref('texo_memory.activity_communication').name, 'Communication')


@tagged('post_install', '-at_install')
class TestSeedRoute(HttpCase):

    def _post(self, user, payload):
        key = self.env['res.users.apikeys'].with_user(user)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open('/texo/v1/admin/seed', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    # The refusal below is expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_the_route_answers_the_administrator_only(self):
        Users = self.env['res.users'].with_context(no_reset_password=True)
        admin = Users.create({'name': 'Admin', 'login': 'chm_seed_route_admin', 'lang': 'en_US',
                              'group_ids': [Command.link(self.env.ref('texo.group_texo_admin').id)]})
        lead = Users.create({'name': 'Lead', 'login': 'chm_seed_route_lead', 'lang': 'en_US',
                             'group_ids': [Command.link(self.env.ref('texo.group_texo_lead').id)]})
        self.assertEqual(self._post(lead, industry_seed()).status_code, 403)
        answer = self._post(admin, industry_seed())
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()['counts'], {'created': 5})
