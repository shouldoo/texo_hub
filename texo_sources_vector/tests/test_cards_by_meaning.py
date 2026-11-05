# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests import tagged

from odoo.addons.texo_vector.tests.common import VectorCase


@tagged('post_install', '-at_install')
class TestCardsByMeaning(VectorCase):
    """A card of the external sources is found by other words than its own, as a fact is."""

    def setUp(self):
        super().setUp()
        self.channel = self.env['memory.source.channel'].create({
            'name': 'Local news', 'kind': 'press', 'website': 'https://news.example.com'})
        self.card = self.env['memory.source.item'].create({
            'channel_id': self.channel.id, 'url': 'https://news.example.com/invoices', 'state': 'active',
            'title': 'Il Comune paga in ritardo', 'abstract': 'Le fatture dei fornitori sono pagate dopo 120 giorni.'})
        self.candidate = self.env['memory.source.item'].create({
            'channel_id': self.channel.id, 'url': 'https://news.example.com/other', 'state': 'candidate',
            'title': 'Fatture e fornitori, un candidato'})

    def test_a_card_gets_a_vector_and_is_found_by_meaning(self):
        self.env['memory.embedding']._cron_embed()
        rows = self.env['memory.embedding'].search([('res_model', '=', 'memory.source.item')])
        self.assertEqual(rows.mapped('res_id'), [self.card.id], "the active cards only, not the candidates")
        Note = self.env['memory.note'].with_user(self.member)
        self.assertEqual(Note._agent_search('billing vendor', scope='sources', mode='lexical'), [],
                         "other words: the lexical search does not find it")
        found = Note._agent_search('billing vendor', scope='sources')
        self.assertEqual((found[0]['id'], found[0]['source'], found[0]['match']), (self.card.id, True, 'semantic'))
        self.assertIn(self.card.id, [r['id'] for r in Note._agent_search('billing vendor', scope='all',
                                                                       mode='semantic') if r.get('source')])
        # archived: out of the vectors at the next run, and out of the search
        self.card.state = 'archived'
        self.env['memory.embedding']._cron_embed()
        self.assertFalse(self.env['memory.embedding'].search([('res_model', '=', 'memory.source.item')]))
        self.assertEqual(Note._agent_search('billing vendor', scope='sources'), [])

    def test_the_reranker_reads_the_card_not_a_note_with_its_id(self):
        """A card reordered by the reranker is read from its own abstract: its id is not a note's (the search
        failed with a MissingError when it looked for a note with the id of the card)."""
        from unittest.mock import patch

        from odoo.addons.texo_vector.models import memory_rerank
        from odoo.addons.texo_vector.tests.test_rerank import FakeReranker
        self.env['memory.embedding']._cron_embed()
        Params = self.env['ir.config_parameter'].sudo()
        Params.set_str(memory_rerank.PARAM_RERANK_ENDPOINT, 'http://tei-rerank:80')
        Params.set_str(memory_rerank.PARAM_RERANK_API, 'llamacpp')
        # a second card, and a note that has the id of the first one if the ids happen to meet
        self.env['memory.source.item'].create({
            'channel_id': self.channel.id, 'url': 'https://news.example.com/late', 'state': 'active',
            'title': 'Ritardi nei pagamenti', 'abstract': 'Il Comune salda le fatture dei fornitori in ritardo.'})
        self.env['memory.embedding']._cron_embed()
        fake = FakeReranker('120 giorni', 'llamacpp')
        with patch.object(memory_rerank.requests, 'post', fake):
            found = self.env['memory.note'].with_user(self.member)._agent_search('fatture fornitori', scope='sources')
        self.assertEqual(found[0]['id'], self.card.id, "the card whose abstract the reranker prefers")
        self.assertIn('rerank', found[0])
        documents = fake.calls[0][1]['documents']
        self.assertTrue(any('pagate dopo 120 giorni' in text for text in documents), documents)
