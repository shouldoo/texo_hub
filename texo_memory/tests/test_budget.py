# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests import tagged

from ..models.memory_note import MIN_TOKENS, tokens_of
from .common import MemoryCase


@tagged('post_install', '-at_install')
class TestBudget(MemoryCase):
    """A pack or a search cut to a budget of tokens: in a fixed order, never a rule dropped, never an
    empty answer, and the answer says what was cut."""

    def setUp(self):
        super().setUp()
        Note = self.env['memory.note'].with_user(self.lead)
        self.rule = Note._agent_note('Long rule', 'Never merge the warehouses. ' * 60, project_id=self.project.id,
                                     state='active', severity='never')
        for n in range(8):
            Note._agent_note(f'Fact {n}', f'The warehouse number {n} holds the returns of its area. ' * 5,
                             kind='fact', project_id=self.project.id)
            Note._agent_note(f'Procedure {n}', f'Step {n}: count, then move. ' * 5, kind='procedure',
                             project_id=self.project.id)
        for n in range(6):
            self.task.with_user(self.member)._texo_post_note(f"Message {n}: the route of the returns was checked again. " * 4)

    def pack(self, **kwargs):
        return self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id, messages=6, **kwargs)

    def test_the_pack_is_cut_in_order_and_says_so(self):
        whole = self.pack()
        self.assertNotIn('budget', whole)
        self.assertEqual(len(whole['task']['messages']), 6)
        tight = self.pack(max_tokens=MIN_TOKENS)
        budget = tight['budget']
        self.assertEqual(budget['max_tokens'], MIN_TOKENS)
        self.assertEqual(budget['trimmed'][0], 'messages:2', "the messages of the task go first")
        self.assertEqual(len(tight['task']['messages']), 2)
        level = next(l for l in tight['levels'] if l['model'] == 'project.project')
        self.assertLessEqual(len(level['facts']), 5)
        self.assertLessEqual(len(level['procedures']), 5)
        rule = next(r for r in level['rules'] if r['id'] == self.rule['id'])
        self.assertTrue(rule['body'], "a rule is cut, never dropped")
        self.assertTrue(rule.get('truncated'))
        self.assertIn('rule_body:500', budget['trimmed'])
        self.assertLessEqual(budget['tokens'], tokens_of(whole))
        # a budget the whole pack fits in cuts nothing
        loose = self.pack(max_tokens=100000)
        self.assertEqual((loose['budget']['trimmed'], len(loose['task']['messages'])), ([], 6))
        okf = self.env['memory.note'].with_user(self.member)._okf_context(
            tight, self.env['project.task'].browse(self.task.id), 6)
        self.assertIn("* Budget: 200 tokens asked", "".join(f['text'] for f in okf['files']))

    def test_the_search_keeps_what_fits_and_never_nothing(self):
        Note = self.env['memory.note'].with_user(self.member)
        whole = Note._agent_search_report('warehouse returns', scope='facts', limit=8)
        self.assertNotIn('budget', whole)
        self.assertGreater(len(whole['results']), 1)
        one = tokens_of(whole['results'][0])
        report = Note._agent_search_report('warehouse returns', scope='facts', limit=8, max_tokens=MIN_TOKENS)
        fits = max(1, MIN_TOKENS // one)
        self.assertEqual(len(report['results']), min(fits, len(whole['results'])))
        self.assertEqual(report['budget']['skipped'], len(whole['results']) - len(report['results']))
        self.assertLessEqual(report['budget']['tokens'], MIN_TOKENS)
        self.assertEqual([r['id'] for r in report['results']], [r['id'] for r in whole['results'][:len(report['results'])]],
                         "the order of the search, cut, never reordered")
