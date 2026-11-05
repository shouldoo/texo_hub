# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import VectorCase


@tagged('post_install', '-at_install')
class TestVectorUi(VectorCase):
    """The state of the search for the administrators, and the search page by meaning."""

    def status(self):
        return self.env['memory.vector.status'].create({})

    def test_the_state_counts_the_texts_waiting_for_a_vector(self):
        self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        before = self.status()
        self.assertTrue(before.available)
        self.assertEqual(before.model_name, 'test/concepts')
        self.assertGreaterEqual(before.pending, 2, "the task and the fact")
        self.assertEqual(before.texts, before.stored + before.pending)
        facts = before.line_ids.filtered(lambda line: line.res_model == 'memory.note')
        self.assertEqual((facts.texts, facts.stored), (1, 0))
        self.env['memory.embedding']._cron_embed()
        after = self.status()
        self.assertEqual(after.pending, 0)
        self.assertEqual(after.stored, after.texts)
        self.assertEqual(after.action_compute_now()['tag'], 'display_notification')

    def test_the_state_is_for_the_administrators(self):
        with self.assertRaises(AccessError):
            self.env['memory.vector.status'].with_user(self.lead).create({})

    def test_the_dashboard_has_the_area_of_the_search_for_the_administrators(self):
        """The area Search: the texts waiting for a vector, and its button opens the state of the search; only
        the administrators see it."""
        self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        Area = self.env['memory.review.area']
        self.assertNotIn('search', Area.with_user(self.lead).search([]).mapped('code'))
        admin = self.env.ref('base.user_admin')
        admin.group_ids = [(4, self.env.ref('texo.group_texo_admin').id)]
        search = Area.with_user(admin).search([('code', '=', 'search')])
        self.assertEqual(search.main_count, self.status().pending)
        self.assertGreaterEqual(search.main_count, 2, "the task and the fact")
        self.assertEqual(search.action_open_main()['res_model'], 'memory.vector.status')

    def test_the_search_page_finds_by_meaning(self):
        fact = self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        self.env['memory.embedding']._cron_embed()
        search = self.env['memory.search'].with_user(self.member).create({'query': 'restituzioni', 'scope': 'facts'})
        self.assertTrue(search.vectors)
        self.assertEqual(search.mode, 'hybrid')
        search.action_search()
        line = search.line_ids.filtered(lambda l: l.res_model == 'memory.note' and l.res_id == fact.id)
        self.assertEqual(line.match, 'semantic', "no word in common: found by meaning")
