# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase


@tagged('post_install', '-at_install')
class TestReview(MemoryCase):

    def test_review_lists_drafts_stale_rules_and_duplicates(self):
        today = fields.Date.context_today(self.env['memory.note'])
        draft = self.env['memory.note'].browse(self.note_as(self.member, name='Idea')['id'])
        stale = self.env['memory.note'].browse(self.note_as(self.lead, name='Old rule', state='active')['id'])
        stale.verified = today - timedelta(days=400)
        fresh = self.env['memory.note'].browse(self.note_as(self.lead, name='Fresh', state='active')['id'])
        Lesson = self.env['memory.lesson'].with_user(self.lead)
        first = Lesson.create({'name': 'A', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION, 'state': 'active'})
        second = Lesson.create({'name': 'B', 'finding': CLEAN_FINDING.replace('fail to load', 'do not load'),
                                'solution': CLEAN_SOLUTION, 'state': 'active'})
        pending = Lesson.create({'name': 'C', 'finding': 'A' * 30, 'solution': 'B' * 30})

        review = self.env['memory.note'].with_user(self.lead)._agent_review()
        self.assertEqual(review['role'], 'lead')
        self.assertEqual([d['title'] for d in review['drafts']], ['Idea'])
        self.assertEqual(review['drafts'][0]['anchor']['model'], 'project.project')
        self.assertEqual([s['id'] for s in review['stale']], [stale.id])
        self.assertNotIn(fresh.id, [s['id'] for s in review['stale']])
        self.assertNotIn('old_events', review)
        self.assertEqual([l['id'] for l in review['draft_lessons']], [pending.id])
        self.assertEqual([(d['lesson_id'], d['other_id']) for d in review['duplicates']], [(first.id, second.id)])
        member_review = self.env['memory.note'].with_user(self.member)._agent_review()
        self.assertEqual(member_review['draft_lessons'], [])
        self.assertEqual(member_review['duplicates'], [])
        self.assertEqual([d['title'] for d in member_review['drafts']], ['Idea'])
        draft.unlink()

    def test_confirm_resets_the_date_and_closes_the_activity(self):
        today = fields.Date.context_today(self.env['memory.note'])
        note = self.env['memory.note'].browse(self.note_as(self.lead, name='Old rule', state='active')['id'])
        note.verified = today - timedelta(days=400)
        self.assertEqual(self.env['memory.note']._cron_housekeeping(), 1)
        self.assertEqual(note.activity_ids.user_id, self.lead)
        self.assertEqual(self.env['memory.note']._cron_housekeeping(), 1)
        self.assertEqual(len(note.activity_ids), 1, "the same reason never gets a second activity")
        with self.assertRaises(AccessError):
            note.with_user(self.member)._agent_confirm()
        result = note.with_user(self.lead)._agent_confirm(expires=fields.Date.to_string(today + timedelta(days=90)))
        self.assertEqual(result['verified'], fields.Date.to_string(today))
        self.assertEqual(note.expires, today + timedelta(days=90))
        self.assertFalse(note.activity_ids)
        self.assertEqual(self.env['memory.note']._cron_housekeeping(), 0)
        draft = self.env['memory.note'].browse(self.note_as(self.lead, name='Draft')['id'])
        with self.assertRaises(UserError):
            draft.with_user(self.lead)._agent_confirm()

    def test_lesson_housekeeping_never_duplicates_its_activities(self):
        Lesson = self.env['memory.lesson'].with_user(self.lead)
        Lesson.create({'name': 'A', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION, 'state': 'active'})
        second = Lesson.create({'name': 'B', 'finding': CLEAN_FINDING.replace('fail to load', 'do not load'),
                                'solution': CLEAN_SOLUTION, 'state': 'active'})
        first_run = self.env['memory.lesson']._cron_housekeeping()
        self.assertEqual(first_run['duplicates'], 1)
        count = len(second.activity_ids)
        self.env['memory.lesson']._cron_housekeeping()
        self.assertEqual(len(second.activity_ids), count)
