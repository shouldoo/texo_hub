# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from unittest.mock import MagicMock, patch

import requests

from odoo.tests import tagged

from ..models import memory_rerank
from ..models.memory_embedding import PARAM_ALLOW_REMOTE
from .common import VectorCase


class FakeReranker:
    """A reranker that prefers the texts holding a word, and records what it was asked."""

    def __init__(self, favourite, api='tei'):
        self.favourite, self.api, self.calls = favourite, api, []

    def __call__(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        texts = json['texts'] if self.api == 'tei' else json['documents']
        scores = [(index, 1.0 if self.favourite in text else 0.1 / (index + 1)) for index, text in enumerate(texts)]
        answer = MagicMock()
        answer.raise_for_status.return_value = None
        if self.api == 'tei':
            answer.json.return_value = [{'index': i, 'score': s} for i, s in sorted(scores, key=lambda x: -x[1])]
        else:
            answer.json.return_value = {'results': [{'index': i, 'relevance_score': s} for i, s in scores]}
        return answer


@tagged('post_install', '-at_install')
class TestRerank(VectorCase):

    def setUp(self):
        super().setUp()
        self.first = self.fact('Resi in magazzino', 'I resi dei clienti tornano con una rotta dedicata.')
        self.second = self.fact('Resi dal fornitore', 'I resi al fornitore partono il venerdì con il corriere.')
        self.env['memory.embedding']._cron_embed()
        self.Params = self.env['ir.config_parameter'].sudo()

    def configure(self, endpoint='http://tei-rerank:80', api='tei'):
        self.Params.set_str(memory_rerank.PARAM_RERANK_ENDPOINT, endpoint)
        self.Params.set_str(memory_rerank.PARAM_RERANK_API, api)

    def ids(self, **kwargs):
        return [r['id'] for r in self.search(self.member, 'resi', scope='facts', **kwargs)]

    def test_off_unless_configured(self):
        fake = FakeReranker('venerdì')
        with patch.object(memory_rerank.requests, 'post', fake):
            before = self.ids()
        self.assertFalse(fake.calls, "no endpoint: no text leaves Odoo")
        self.assertEqual(self.env['memory.embedding']._rerank_pool(), 0)
        self.assertEqual(set(before), {self.first.id, self.second.id})

    def test_the_reranker_reorders_the_hybrid(self):
        self.configure()
        for api in ('tei', 'llamacpp'):
            self.configure(api=api)
            for favourite, top in (('venerdì', self.second), ('rotta', self.first)):
                fake = FakeReranker(favourite, api)
                with patch.object(memory_rerank.requests, 'post', fake):
                    found = self.search(self.member, 'resi', scope='facts')
                self.assertEqual(found[0]['id'], top.id, (api, favourite))
                self.assertIn('rerank', found[0])
                url, payload, timeout = fake.calls[0]
                self.assertEqual(url, 'http://tei-rerank:80/rerank' if api == 'tei' else 'http://tei-rerank:80/v1/rerank')
                self.assertEqual(timeout, memory_rerank.DEFAULT_TIMEOUT)
                texts = payload['texts'] if api == 'tei' else payload['documents']
                self.assertTrue(all(len(text) <= memory_rerank.DEFAULT_CHARS for text in texts))
                self.assertTrue(any(text.startswith('Resi dal fornitore\n') for text in texts), "the title, then the text")
        # the lexical mode is never reranked
        fake = FakeReranker('venerdì')
        with patch.object(memory_rerank.requests, 'post', fake):
            self.ids(mode='lexical')
        self.assertFalse(fake.calls)

    def test_the_order_of_the_reranker_is_fused_with_the_order_of_the_search(self):
        from ..models import hybrid

        def ids(scores):
            return [e['id'] for e in hybrid.blend([{'id': i} for i in range(1, len(scores) + 1)], scores)]

        self.assertEqual(ids([0.1, 0.9]), [2, 1], "two neighbours swap when the reranker says so")
        # a far result the reranker puts first climbs a few places, not over the first of the search:
        # a record asked by its exact title stays where the words and the vectors put it
        self.assertEqual(ids([0.5, 0.4, 0.3, 0.2, 0.9]), [1, 5, 2, 3, 4])
        self.assertEqual(ids([0.5, 0.4, 0.3, 0.2, 0.1]), [1, 2, 3, 4, 5], "agreeing, nothing moves")
        blended = hybrid.blend([{'id': 1, 'ranks': {'lexical': 1}}, {'id': 2}], [0.25, 0.75])
        self.assertEqual((blended[0]['rerank'], blended[0]['ranks']), (0.75, {'rerank': 1}))
        self.assertEqual(blended[1]['ranks'], {'lexical': 1, 'rerank': 2}, "the explanation keeps every rank")

    def test_the_reranker_reads_the_chatter_of_a_task(self):
        """The description of a task is often one line: the reranker reads its chatter too, newest first,
        where the episode says what happened."""
        self.task.description = '<p>Domanda sulla piattaforma</p>'
        Task = self.task.with_user(self.member)
        Task._texo_post_note("Chiesti 12.000 euro per il progetto.")
        Task._texo_post_note("Assegnati 9.000 euro: tagliata la voce del personale.")
        text = self.env['memory.note']._rerank_text({'task': True, 'id': self.task.id, 'title': self.task.name}, 2000)
        self.assertTrue(text.startswith(f"{self.task.name}\nDomanda sulla piattaforma"), text)
        self.assertLess(text.index('Assegnati 9.000'), text.index('Chiesti 12.000'), "the newest message first")
        self.assertLessEqual(len(self.env['memory.note']._rerank_text(
            {'task': True, 'id': self.task.id, 'title': self.task.name}, 60)), 60)

    def test_no_answer_in_time_keeps_the_hybrid_order(self):
        hybrid = self.ids()
        self.configure()

        def timeout(*args, **kwargs):
            raise requests.Timeout("too slow")

        with patch.object(memory_rerank.requests, 'post', timeout), \
                self.assertLogs('odoo.addons.texo_vector.models.memory_rerank', 'WARNING'):
            self.assertEqual(self.ids(), hybrid)

    def test_a_remote_reranker_needs_the_opt_in(self):
        self.configure('https://rerank.example.com')
        fake = FakeReranker('venerdì')
        with patch.object(memory_rerank.requests, 'post', fake), \
                self.assertLogs('odoo.addons.texo_vector.models.memory_rerank', 'WARNING'):
            self.ids()
        self.assertFalse(fake.calls, "the texts of the memory do not leave the local network")
        self.Params.set_bool(PARAM_ALLOW_REMOTE, True)
        with patch.object(memory_rerank.requests, 'post', fake):
            self.assertEqual(self.ids()[0], self.second.id)
        self.assertTrue(fake.calls)

    def test_the_search_says_what_the_reranker_did(self):
        Note = self.env['memory.note'].with_user(self.member)

        def report(**kwargs):
            answer = Note._agent_search_report('resi', scope='facts', **kwargs)
            return answer['mode'], answer['rerank']

        self.assertEqual(report(), ('hybrid', 'off'))
        self.configure()
        fake = FakeReranker('venerdì')
        with patch.object(memory_rerank.requests, 'post', fake):
            self.assertEqual(report(), ('hybrid', 'applied'))
            self.assertEqual(report(mode='lexical'), ('lexical', 'skipped'))
            self.assertEqual(report(mode='semantic'), ('semantic', 'skipped'))
            self.assertIsInstance(Note._agent_search_report('resi', scope='facts')['latency_ms'], int)

        def timeout(*args, **kwargs):
            raise requests.Timeout("too slow")

        with patch.object(memory_rerank.requests, 'post', timeout), \
                self.assertLogs('odoo.addons.texo_vector.models.memory_rerank', 'WARNING'):
            self.assertEqual(report(), ('hybrid', 'unavailable'))
        self.configure('https://rerank.example.com')
        with self.assertLogs('odoo.addons.texo_vector.models.memory_rerank', 'WARNING'):
            self.assertEqual(report(), ('hybrid', 'unavailable'), "refused outside the local network")

    def test_the_state_of_the_search_says_it(self):
        self.assertNotIn('http', self.env['memory.vector.status'].create({}).rerank)
        self.configure()
        self.assertIn('http://tei-rerank:80', self.env['memory.vector.status'].create({}).rerank)
