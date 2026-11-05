# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase


@tagged('post_install', '-at_install')
class TestMemoryUi(MemoryCase):
    """The memory in the backend: the filter To Check, the search of the agent as a page, the
    queues of the review, the buttons on the work records, the text of a document."""

    def note(self, user=None, **kwargs):
        return self.env['memory.note'].browse(self.note_as(user or self.lead, **kwargs)['id'])

    def test_to_check_is_the_stale_of_the_review(self):
        today = fields.Date.context_today(self.env['memory.note'])
        old = self.note(name='Old rule', state='active')
        old.verified = today - timedelta(days=400)
        expired = self.note(name='Expired fact', kind='fact', expires=fields.Date.to_string(today - timedelta(days=1)))
        fresh = self.note(name='Fresh rule', state='active')
        draft = self.note(self.member, name='Idea')
        Note = self.env['memory.note'].with_user(self.lead)
        stale = Note.search([('stale', '=', True)])
        self.assertIn(old, stale)
        self.assertIn(expired, stale)
        self.assertNotIn(fresh, stale)
        self.assertNotIn(draft, stale, "a draft is decided, not checked")
        self.assertTrue(old.stale)
        self.assertFalse(fresh.stale)
        self.assertIn(fresh, Note.search([('stale', '=', False)]))
        self.assertNotIn(old, Note.search([('stale', '=', False)]))

    def test_the_search_page_gives_the_ranking_of_the_agent(self):
        fact = self.note(name='Returns location', kind='fact', body='The returns go to the RMA shelf of the warehouse.')
        with Form(self.env['memory.search'].with_user(self.member)) as page:
            page.query = 'RMA shelf'
            page.scope = 'all'
            search = page.save()
        search.action_search()
        self.assertTrue(search.searched)
        line = search.line_ids[:1]
        self.assertEqual((line.res_model, line.res_id), ('memory.note', fact.id))
        self.assertEqual(line.kind, dict(self.env['memory.note']._fields['kind']._description_selection(
            search.env))['fact'])
        self.assertEqual(line.match, 'all')
        self.assertIn('RMA shelf', line.snippet)
        action = line.action_open()
        self.assertEqual((action['res_model'], action['res_id']), ('memory.note', fact.id))
        # a scope without it: nothing, and the page says so
        search.write({'scope': 'lessons'})
        search.action_search()
        self.assertFalse(search.line_ids)

    def test_the_search_page_opens_a_document_in_its_view(self):
        document = self.env['ir.attachment'].create({
            'name': 'Shelf plan', 'type': 'url', 'url': 'https://example.com/plan', 'res_model': 'project.project',
            'res_id': self.project.id, 'texo_document': True, 'description': 'Where the RMA shelf stands'})
        search = self.env['memory.search'].with_user(self.member).create({'query': 'RMA shelf', 'scope': 'documents'})
        search.action_search()
        line = search.line_ids.filtered(lambda l: l.res_id == document.id)
        self.assertEqual(line.res_model, 'ir.attachment')
        self.assertEqual(line.action_open()['views'][0][0], self.env.ref('texo_memory.view_memory_document_form').id)

    def test_the_review_counts_what_the_user_may_act_on(self):
        self.note(self.member, name='Idea')
        Lesson = self.env['memory.lesson'].with_user(self.lead)
        Lesson.create({'name': 'Draft', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION})
        lead_review = self.env['memory.review'].with_user(self.lead).create({})
        self.assertGreaterEqual(lead_review.draft_rules, 1)
        self.assertGreaterEqual(lead_review.draft_lessons, 1)
        member_review = self.env['memory.review'].with_user(self.member).create({})
        self.assertGreaterEqual(member_review.draft_rules, 1)
        self.assertEqual(member_review.draft_lessons, 0, "the lessons are curated by the leads")
        action = lead_review.with_context(queue='draft_rules').action_open_queue()
        self.assertEqual(action['res_model'], 'memory.note')
        self.assertEqual(self.env['memory.note'].with_user(self.lead).search_count(action['domain']),
                         lead_review.draft_rules)
        documents = lead_review.with_context(queue='changed_documents').action_open_queue()
        self.assertEqual(documents['res_model'], 'ir.attachment')
        self.assertEqual(documents['context'], {})

    def test_the_dashboard_of_the_review_has_a_card_per_area(self):
        """To Review is a dashboard (memory.review.area): one card per area, its main queue as the big
        button, counted as the review counts; an area of the leads is not shown to a member."""
        self.note(self.member, name='Idea')
        Lesson = self.env['memory.lesson'].with_user(self.lead)
        Lesson.create({'name': 'Draft', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION})
        Area = self.env['memory.review.area']
        lead_areas = Area.with_user(self.lead).search([])
        self.assertTrue({'knowledge', 'lessons', 'projects'} <= set(lead_areas.mapped('code')))
        self.assertNotIn('lessons', Area.with_user(self.member).search([]).mapped('code'), "the lessons are the leads'")
        review = self.env['memory.review'].with_user(self.lead).create({})
        knowledge = lead_areas.filtered(lambda a: a.code == 'knowledge')
        lessons = lead_areas.filtered(lambda a: a.code == 'lessons')
        self.assertEqual((knowledge.draft_rules, knowledge.main_count), (review.draft_rules, review.stale_notes))
        self.assertEqual(lessons.main_count, review.draft_lessons)
        self.assertGreaterEqual(lessons.main_count, 1)
        self.assertEqual(knowledge.pending, review.stale_notes + review.draft_rules + review.changed_documents)
        action = lessons.action_open_main()
        self.assertEqual(action['res_model'], 'memory.lesson')
        self.assertEqual(Lesson.search_count(action['domain']), lessons.main_count)
        rules = knowledge.with_context(queue='draft_rules').action_open_queue()
        self.assertEqual(self.env['memory.note'].with_user(self.lead).search_count(rules['domain']), knowledge.draft_rules)
        with self.assertRaises(UserError):
            knowledge.with_context(queue='nothing').action_open_queue()
        self.assertEqual(self.env.ref('texo_memory.menu_memory_review').action,
                         self.env.ref('texo_memory.action_memory_review_area'))
        root = self.env.ref('texo_memory.menu_memory_root')
        first = self.env['ir.ui.menu'].search([('parent_id', '=', root.id)], order='sequence, id', limit=1)
        self.assertEqual(first, self.env.ref('texo_memory.menu_memory_review'),
                         "the app Memory opens on the dashboard of the review")

    def test_the_work_records_open_their_memory(self):
        self.note(name='Project rule', state='active')
        fact = self.note(name='Task fact', kind='fact', task_id=self.task.id)
        self.env['ir.attachment'].create({
            'name': 'Spec', 'type': 'url', 'url': 'https://example.com/spec', 'res_model': 'project.project',
            'res_id': self.project.id, 'texo_document': True})
        project = self.project.with_user(self.member)
        self.assertEqual(project.texo_note_count, 1)
        self.assertEqual(project.texo_document_count, 1)
        action = project.action_texo_notes()
        self.assertEqual(action['domain'], [('project_id', '=', self.project.id)])
        self.assertEqual(action['context']['default_project_id'], self.project.id)
        documents = project.action_texo_documents()
        self.assertEqual(self.env['ir.attachment'].with_user(self.member).search_count(documents['domain']), 1)
        task = self.task.with_user(self.member)
        self.assertEqual(task.texo_note_ids, fact)
        self.assertEqual(task.texo_note_count, 1)

    def test_the_lessons_of_a_project_share_its_tags(self):
        tag = self.env['project.tags'].create({'name': 'warehouse'})
        self.project.tag_ids = tag
        lesson = self.env['memory.lesson'].with_user(self.lead).create({
            'name': 'Returns', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION, 'state': 'active',
            'tag_ids': [fields.Command.link(tag.id)]})
        project = self.project.with_user(self.member)
        self.assertEqual(project.texo_lesson_count, 1)
        self.assertEqual(self.env['memory.lesson'].search(project.action_texo_lessons()['domain']), lesson)

    def test_a_document_shows_its_text_unless_sensitive(self):
        document = self.env['ir.attachment'].create({
            'name': 'notes.md', 'raw': b'# Returns\nThe RMA shelf.', 'mimetype': 'text/markdown',
            'res_model': 'project.project', 'res_id': self.project.id, 'texo_document': True})
        self.assertIn('RMA shelf', document.texo_text)
        document.texo_keep_text = False
        self.assertFalse(document.texo_text)
