# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase


@tagged('post_install', '-at_install')
class TestMemoryLesson(MemoryCase):

    def lesson(self, user, **kwargs):
        vals = {'name': 'UoM field on purchase lines', 'kind': 'lesson',
                'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION, 'applies_to': 'Odoo 20.0'}
        vals.update(kwargs)
        return self.env['memory.lesson'].with_user(user).create(vals)

    def test_lead_curates_member_reads(self):
        lesson = self.lesson(self.lead)
        with self.assertRaises(AccessError):
            self.lesson(self.member)
        with self.assertRaises(AccessError):
            lesson.with_user(self.member).write({'state': 'active'})
        lesson.with_user(self.lead)._agent_set_state('active')
        self.assertEqual(lesson.with_user(self.member)._agent_read()['state'], 'active')

    def test_the_same_finding_is_written_once(self):
        Lesson = self.env['memory.lesson'].with_user(self.member)
        first = Lesson._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION, tags=['purchase'])
        again = Lesson._agent_lesson(f"  {CLEAN_FINDING}  ", CLEAN_SOLUTION, title='Another title')
        self.assertEqual((again['id'], again['existing']), (first['id'], True))
        self.assertNotIn('existing', first)
        other = Lesson._agent_lesson(CLEAN_FINDING, CLEAN_SOLUTION + " Then run the tests.")
        self.assertNotEqual(other['id'], first['id'])

    def test_a_lesson_never_names_a_customer(self):
        with self.assertRaises(UserError):
            self.lesson(self.lead, finding=CLEAN_FINDING + " Seen at Rossi Meccanica.")
        lesson = self.lesson(self.lead)
        with self.assertRaises(UserError):
            lesson.with_user(self.lead).write({'name': 'Rossi Meccanica returns'})

    def test_search_ranks_by_words_in_both_languages(self):
        self.lesson(self.lead, state='active')
        self.lesson(self.lead, name='Report layout', state='active',
                    finding="Il layout del report PDF perde l'intestazione quando la pagina supera le 40 righe.",
                    solution="Set the paper format margin and the header spacing in the report paperformat record.")
        Lesson = self.env['memory.lesson'].with_user(self.member)
        self.assertEqual([r['title'] for r in Lesson._agent_search('intestazione report')], ['Report layout'])
        self.assertEqual([r['title'] for r in Lesson._agent_search('unit field', related_terms=['uom'])],
                         ['UoM field on purchase lines'])
        self.assertEqual(Lesson._agent_search('intestazione', applies_to='Odoo 19.0'), [])
        self.assertEqual(Lesson._agent_search(''), [])

    def test_search_puts_the_lessons_with_every_word_first(self):
        both = self.lesson(self.lead, name='Stock moves', state='active',
                           finding="Reserving stock moves in batch skips the quants that another transaction locked.",
                           solution="Reserve the moves in one transaction per warehouse and retry on a lock error.")
        one = self.lesson(self.lead, name='Batch imports', state='active',
                          finding="Importing records in batch from a CSV file blocks the worker when the file is large.",
                          solution="Split the file and import each part in its own job, with a queue of jobs.")
        Lesson = self.env['memory.lesson'].with_user(self.member)
        self.assertEqual([r['id'] for r in Lesson._agent_search('batch quants')], [both.id, one.id],
                         "every word first, then the lessons with some to fill the limit")
        self.assertEqual([r['id'] for r in Lesson._agent_search('batch quants', limit=1)], [both.id])

    def test_search_by_prefix_and_by_keywords(self):
        lesson = self.lesson(self.lead, name='Regole di accesso', state='active',
                             finding="La migrazione dei moduli custom alla 20.0 converte le regole di accesso in ir.access.",
                             solution="Confrontare il file generato con le regole di prima e provare ogni ruolo a mano.",
                             keywords="ACL, permessi, sicurezza, upgrade_code")
        Lesson = self.env['memory.lesson'].with_user(self.member)
        self.assertEqual([r['id'] for r in Lesson._agent_search('migraz')], [lesson.id], "a long word is a prefix too")
        self.assertEqual([r['id'] for r in Lesson._agent_search('permessi ACL')], [lesson.id],
                         "found by the keywords the writer gave, not in its text")
        self.assertEqual(lesson.with_user(self.member)._agent_read()['keywords'], "ACL, permessi, sicurezza, upgrade_code")
        with self.assertRaises(UserError):
            self.lesson(self.lead, name='Leak', keywords="Rossi Meccanica")
        # a query can never carry the operators of to_tsquery
        self.assertEqual(Lesson._agent_search("':* & | ! ( )"), [])

    def test_the_pack_gives_the_lessons_of_the_tags_of_the_task_and_its_project(self):
        Tag = self.env['project.tags']
        stock, v20, other = Tag.create({'name': 'chm-stock'}), Tag.create({'name': 'chm-20.0'}), Tag.create({'name': 'chm-other'})
        code = self.env['memory.note.activity'].search([('code', '=', 'code')])
        two = self.lesson(self.lead, name='Two tags', state='active', tag_ids=[(6, 0, (stock | v20).ids)])
        one = self.lesson(self.lead, name='One tag', state='active', tag_ids=[(6, 0, stock.ids)],
                          lesson_activity_ids=[(6, 0, code.ids)], finding=CLEAN_FINDING + " Another case.")
        self.lesson(self.lead, name='Elsewhere', state='active', tag_ids=[(6, 0, other.ids)],
                    finding=CLEAN_FINDING + " A third case.")
        self.lesson(self.lead, name='Draft', tag_ids=[(6, 0, stock.ids)], finding=CLEAN_FINDING + " A draft case.")
        Note = self.env['memory.note'].with_user(self.member)
        self.assertEqual(Note._agent_context(task_id=self.task.id)['lessons'], [], "no tag, no lesson: no guess from the title")
        self.project.tag_ids = stock
        self.task.tag_ids = v20
        pack = Note._agent_context(task_id=self.task.id)
        self.assertEqual([l['id'] for l in pack['lessons']], [two.id, one.id], "more tags in common first")
        self.assertEqual(sorted(pack['lessons'][0]['tags']), ['chm-20.0', 'chm-stock'])
        self.assertEqual(set(pack['lessons'][0]), {'id', 'concept', 'title', 'tags', 'applies_to'}, "an outline: the text with memory/read")
        self.assertEqual([l['id'] for l in Note._agent_context(task_id=self.task.id, activity='communication')['lessons']],
                         [two.id], "a lesson of the code is not in a session of communication")
        self.assertEqual([l['id'] for l in Note._agent_context(project_id=self.project.id)['lessons']], [one.id, two.id],
                         "the project alone has one tag: as many in common, the newer first")

    def test_housekeeping_archives_a_lesson_that_names_a_later_customer(self):
        lesson = self.lesson(self.lead, state='active', finding=CLEAN_FINDING + " Seen at Verdi Impianti.")
        self.env['res.partner'].create({'name': 'Verdi Impianti', 'is_company': True})
        self.assertEqual(self.env['memory.lesson']._cron_housekeeping()['archived'], 1)
        self.assertEqual(lesson.state, 'archived')

    def test_housekeeping_proposes_the_merge_of_near_duplicates(self):
        first = self.lesson(self.lead, state='active')
        second = self.lesson(self.lead, name='Same again', state='active',
                             finding=CLEAN_FINDING.replace('fail to load', 'do not load'))
        self.lesson(self.lead, name='Unrelated', state='active',
                    finding="The account chart template of a localisation adds taxes that a custom module expects by xmlid.",
                    solution="Reference the taxes through the chart template data instead of hard-coded xmlids.")
        self.assertEqual(self.env['memory.lesson']._cron_housekeeping()['duplicates'], 1)
        self.assertFalse(first.activity_ids)
        # One activity per lead (the administrator of the instance is a lead too).
        self.assertIn(self.lead, second.activity_ids.user_id)
        self.assertTrue(all(str(first.id) in activity.note for activity in second.activity_ids))
