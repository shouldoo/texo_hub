# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase


@tagged('post_install', '-at_install')
class TestMemoryNote(MemoryCase):

    def test_member_writes_drafts_and_the_lead_gets_a_review_activity(self):
        result = self.note_as(self.member)
        note = self.env['memory.note'].browse(result['id'])
        self.assertEqual((note.kind, note.state, note.origin), ('rule', 'draft', 'agent'))
        self.assertEqual(note.customer_id, self.customer)
        activity = note.activity_ids
        self.assertEqual(activity.user_id, self.lead)
        with self.assertRaises(AccessError):
            self.note_as(self.member, state='active')
        with self.assertRaises(AccessError):
            note.with_user(self.member)._agent_set_state('active')

    def test_lead_writes_active_at_once_and_reviews_drafts(self):
        result = self.note_as(self.lead, state='active')
        note = self.env['memory.note'].browse(result['id'])
        self.assertEqual(note.state, 'active')
        self.assertEqual(note.verified, fields.Date.context_today(note))
        self.assertFalse(note.activity_ids)
        draft = self.env['memory.note'].browse(self.note_as(self.member, name='Second')['id'])
        draft.with_user(self.lead)._agent_set_state('active')
        self.assertEqual(draft.state, 'active')
        self.assertFalse(draft.activity_ids)
        later = self.env['memory.note'].browse(self.note_as(self.lead, name='Third', state='active')['id'])
        draft.with_user(self.lead)._agent_set_state('superseded', superseded_by_id=later.id)
        self.assertEqual(draft.superseded_by_id, later)
        self.assertEqual(later.supersedes_id, draft)

    def test_member_edits_only_own_drafts(self):
        note = self.env['memory.note'].browse(self.note_as(self.lead, state='active')['id'])
        with self.assertRaises(AccessError):
            note.with_user(self.member).write({'body': 'changed'})
        own = self.env['memory.note'].browse(self.note_as(self.member, name='Mine')['id'])
        own.with_user(self.member).write({'body': 'changed by its author while still a draft'})
        self.assertEqual(own.body, 'changed by its author while still a draft')

    def test_one_anchor_and_never_a_task(self):
        with self.assertRaises(UserError):
            self.note_as(self.member, project_id=self.project.id, partner_id=self.customer.id)
        with self.assertRaises(UserError):
            self.env['memory.note'].with_user(self.lead).create({
                'name': 'x', 'body': 'y', 'partner_id': self.customer.id, 'project_id': self.project.id})
        with self.assertRaises(UserError, msg="what concerns one task goes in a note on the task"):
            self.note_as(self.member, task_id=self.task.id)
        with self.assertRaises(UserError):
            self.env['memory.note'].with_user(self.lead).create({'name': 'x', 'body': 'y', 'task_id': self.task.id})

    def test_a_note_is_a_rule(self):
        for kind in ('context', 'decision', 'event', 'finding'):
            with self.assertRaises(UserError):
                self.note_as(self.member, kind=kind)
        self.assertEqual(self.note_as(self.member, kind='rule')['kind'], 'rule')

    def test_a_finding_is_a_lesson_written_directly_and_a_leak_stores_nothing(self):
        Lesson = self.env['memory.lesson']
        result = Lesson.with_user(self.member)._agent_lesson(
            CLEAN_FINDING, CLEAN_SOLUTION, tags=['migrazione', 'purchase'], applies_to='Odoo 20.0', source_ref='MIG-7',
            activities='migration')
        lesson = Lesson.browse(result['id'])
        self.assertEqual((lesson.kind, lesson.state, lesson.origin), ('finding', 'draft', 'agent'))
        self.assertEqual(sorted(lesson.tag_ids.mapped('name')), ['migrazione', 'purchase'], "missing tags are created")
        self.assertEqual(lesson.lesson_activity_ids.mapped('code'), ['migration'])
        self.assertEqual(sorted(result['tags']), ['migrazione', 'purchase'])
        with self.assertRaises(UserError):
            Lesson.with_user(self.member)._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION, tags=['Rossi Meccanica'])
        self.assertEqual(lesson.create_date, lesson.create_date.replace(hour=0, minute=0, second=0, microsecond=0))
        self.assertFalse(any(f in lesson._fields for f in ('task_id', 'project_id', 'partner_id', 'note_id')))
        with self.assertRaises(AccessError):
            Lesson.with_user(self.member)._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION, state='active')
        with self.assertRaises(UserError):
            Lesson.with_user(self.member)._agent_lesson(
                CLEAN_FINDING, CLEAN_SOLUTION + " Rossi Meccanica did it on task MIG-7.", source_ref='MIG-7')
        with self.assertRaises(UserError):
            Lesson.with_user(self.member)._agent_lesson(CLEAN_FINDING, ' ')
        self.assertEqual(Lesson.search_count([('kind', '=', 'finding')]), 1)
        active = Lesson.with_user(self.lead)._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION, title='UoM on 20.0', state='active')
        self.assertEqual((active['title'], active['state']), ('UoM on 20.0', 'active'))

    def test_outsider_reads_the_lesson_but_not_the_rule(self):
        rule = self.note_as(self.lead, state='active')
        self.env['memory.lesson'].with_user(self.lead)._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION, state='active')
        Note = self.env['memory.note'].with_user(self.outsider)
        self.assertFalse(Note.search([('id', '=', rule['id'])]))
        lessons = self.env['memory.lesson'].with_user(self.outsider)._agent_search('uom_id purchase 20.0')
        self.assertEqual([l['title'] for l in lessons], [CLEAN_FINDING[:120]])

    def test_context_pack_walks_the_chain_with_the_rules_of_each_level(self):
        self.note_as(self.lead, state='active', name='Project rule', body='Three warehouses: never merge them.')
        self.note_as(self.lead, state='active', name='No Enterprise', partner_id=self.customer.id,
                     body='Community only, by contract.')
        old = self.env['memory.note'].browse(self.note_as(self.lead, state='active', name='Old')['id'])
        old.verified = fields.Date.context_today(old) - timedelta(days=400)
        self.note_as(self.member, name='Pending idea')
        pack = self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id)
        self.assertEqual(pack['role'], 'member')
        self.assertEqual([lvl['model'] for lvl in pack['levels']], ['project.task', 'project.project', 'res.partner'])
        self.assertEqual(pack['levels'][0]['rules'], [])
        self.assertEqual([r['title'] for r in pack['levels'][1]['rules']], ['Project rule', 'Old'])
        self.assertEqual(pack['levels'][1]['rules'][0]['body'], 'Three warehouses: never merge them.')
        self.assertEqual([r['title'] for r in pack['levels'][2]['rules']], ['No Enterprise'])
        self.assertNotIn('decisions', pack)
        self.assertEqual([p['title'] for p in pack['pending']], ['Pending idea'])
        self.assertEqual(pack['warnings'], [{'id': old.id, 'concept': f"rules/{old.id}", 'title': 'Old', 'stale': 'unverified'},
                                            {'project_id': self.project.id, 'warning': 'now_missing'}])
        self.assertEqual((pack['project']['id'], pack['project']['now']), (self.project.id, None))
        self.assertNotIn('warnings', pack['project'])
        self.assertEqual(pack['task']['name'], 'Returns route')
        with self.assertRaises(UserError):
            self.env['memory.note'].with_user(self.outsider)._agent_context(task_id=self.task.id)

    def test_the_rules_of_the_organisation_open_every_session(self):
        Note = self.env['memory.note']
        self.assertEqual(Note.with_user(self.member)._agent_rules_text("Common.")['rules'], "Common.")
        self.note_as(self.lead, task_id=None, name='Language', body='Answer in Italian.', state='active')
        self.note_as(self.lead, task_id=None, name='Production', body='Never touch production.', state='active')
        self.note_as(self.member, task_id=None, name='Proposal', body='Only a draft.')
        self.note_as(self.lead, name='Of the project', body='Not for every session.', state='active')
        result = Note.with_user(self.member)._agent_rules_text("Common.")
        self.assertEqual(result['rules'], f"Common.\n\nRules of {self.env.company.name}:\n"
                                          "- [must] Language: Answer in Italian.\n"
                                          "- [must] Production: Never touch production.")
        self.assertEqual([r['title'] for r in result['company_rules']], ['Language', 'Production'])

    def test_a_rule_has_a_severity_and_the_activities_it_concerns(self):
        Note = self.env['memory.note']
        code = self.env.ref('texo_memory.activity_code')
        rule = Note.browse(self.note_as(self.lead, state='active', severity='never', activities='code, deploy')['id'])
        self.assertEqual(rule.severity, 'never')
        self.assertEqual(rule.rule_activity_ids.mapped('code'), ['code', 'deploy'])
        self.assertEqual(Note.browse(self.note_as(self.lead, name='Default')['id']).severity, 'must')
        with self.assertRaises(UserError):
            self.note_as(self.lead, severity='always')
        with self.assertRaisesRegex(UserError, 'Unknown activity cooking'):
            self.note_as(self.lead, activities=['code', 'cooking'])
        with self.assertRaises(UserError):
            code.copy({'code': 'Not a word'})
        self.assertEqual(Note.with_user(self.member).browse(rule.id)._agent_summary()[0]['activities'], ['code', 'deploy'])

    def test_the_pack_gives_the_text_of_what_binds_and_the_title_of_a_preference(self):
        never = self.note_as(self.lead, name='Never', body='Never upgrade a module on production.', state='active',
                             severity='never')
        prefer = self.note_as(self.lead, name='Prefer', body='Prefer the OCA module to a custom one.', state='active',
                              severity='prefer')
        rules = {r['id']: r for r in self.env['memory.note'].with_user(self.member)._agent_context(
            project_id=self.project.id)['levels'][0]['rules']}
        self.assertEqual(rules[never['id']]['body'], 'Never upgrade a module on production.')
        self.assertNotIn('body', rules[prefer['id']])
        self.assertTrue(rules[prefer['id']]['body_omitted'])
        self.assertEqual(self.env['memory.note'].browse(prefer['id']).with_user(self.member)._agent_read()['body'],
                         'Prefer the OCA module to a custom one.')

    def test_the_pack_and_the_rules_follow_the_activity_of_the_session(self):
        Note = self.env['memory.note'].with_user(self.member)
        self.note_as(self.lead, state='active', name='Code only', body='Prefix the modules.', severity='prefer',
                     activities='code')
        self.note_as(self.lead, state='active', name='Proposals', body='Disclose the AI.', activities='communication')
        self.note_as(self.lead, state='active', name='Everywhere', body='No secrets.', severity='never')
        self.note_as(self.lead, task_id=None, state='active', name='Org code', body='Tests always.', activities='code')
        self.note_as(self.lead, task_id=None, state='active', name='Org texts', body='A person sends.',
                     activities='communication')

        def titles(pack):
            return [r['title'] for r in pack['levels'][1]['rules']]
        self.assertEqual(titles(Note._agent_context(task_id=self.task.id)), ['Code only', 'Proposals', 'Everywhere'])
        pack = Note._agent_context(task_id=self.task.id, activity='code')
        self.assertEqual(titles(pack), ['Code only', 'Everywhere'])
        self.assertEqual(pack['activities'], ['code'])
        self.assertEqual(titles(Note._agent_context(task_id=self.task.id, activity='code,communication')),
                         ['Code only', 'Proposals', 'Everywhere'])
        with self.assertRaises(UserError):
            Note._agent_context(task_id=self.task.id, activity='cooking')
        result = Note._agent_rules_text("Common.", activity='code')
        self.assertEqual(result['rules'], f"Common.\n\nRules of {self.env.company.name}:\n"
                                          "- [must] Org code: Tests always. (activities: code)")
        self.assertIn('communication', [a['code'] for a in result['activities']])
        self.assertEqual([r['title'] for r in Note._agent_rules_text("Common.")['company_rules']],
                         ['Org code', 'Org texts'])

    def test_search_returns_readable_rules_and_lessons(self):
        self.note_as(self.lead, state='active', name='Picking type', body='Returns always use a dedicated picking type.')
        found = self.env['memory.note'].with_user(self.member)._agent_search('picking returns')
        self.assertEqual([f['title'] for f in found], ['Picking type'])
        self.assertEqual(self.env['memory.note'].with_user(self.outsider)._agent_search('picking returns'), [])

    def test_the_pack_carries_the_project_and_its_present(self):
        self.project.write({'description': '<p>Returns are a separate flow.</p>', 'allow_milestones': True})
        milestone = self.env['project.milestone'].create({'name': 'Returns live', 'project_id': self.project.id})
        self.task.milestone_id = milestone
        update = self.env['project.update'].create({'project_id': self.project.id, 'name': 'Week', 'status': 'at_risk',
                                                    'progress': 20, 'description': '<p>Route designed.</p>'})
        pack = self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id)
        self.assertEqual(pack['project']['description'], 'Returns are a separate flow.')
        self.assertEqual([m['name'] for m in pack['project']['milestones']], ['Returns live'])
        self.assertEqual((pack['project']['now']['id'], pack['project']['now']['status']), (update.id, 'at_risk'))
        self.assertEqual(pack['task']['milestone']['name'], 'Returns live')
        self.assertEqual(pack['warnings'], [])
        self.assertEqual(self.env['memory.note'].with_user(self.member)._agent_context(project_id=self.project.id)['project']['id'],
                         self.project.id)

    def test_the_review_lists_the_projects_without_a_recent_present(self):
        today = fields.Date.context_today(self.project)
        review = self.env['memory.note'].with_user(self.lead)._agent_review()
        self.assertIn({'project_id': self.project.id, 'name': self.project.display_name, 'warning': 'now_missing',
                       'last_update': None}, review['projects_without_now'])
        self.assertEqual(self.env['memory.note'].with_user(self.member)._agent_review()['projects_without_now'], [],
                         "a member sees only the projects they manage")
        update = self.env['project.update'].create({'project_id': self.project.id, 'name': 'Week', 'status': 'on_track',
                                                    'description': '<p>x</p>'})
        update.date = today - timedelta(days=40)
        rows = [r for r in self.env['memory.note'].with_user(self.lead)._agent_review()['projects_without_now']
                if r['project_id'] == self.project.id]
        self.assertEqual(rows[0]['warning'], 'now_stale')
        update.date = today
        self.assertNotIn(self.project.id, [r['project_id'] for r in
                                           self.env['memory.note'].with_user(self.lead)._agent_review()['projects_without_now']])
