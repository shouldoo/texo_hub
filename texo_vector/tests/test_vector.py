# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import threading
import time
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models import memory_embedding
from ..models.memory_embedding import PARAM_ALLOW_REMOTE, PARAM_API, PARAM_DIMENSIONS, PARAM_ENDPOINT, PARAM_MODE
from .common import DIMENSIONS, VectorCase, fake_embed

LOGGER = 'odoo.addons.texo_vector.models.memory_embedding'


@tagged('post_install', '-at_install')
class TestVector(VectorCase):

    def cron(self):
        return self.env['memory.embedding']._cron_embed()

    def test_the_cron_keeps_the_vectors_of_the_memory(self):
        Embedding = self.env['memory.embedding']
        fact = self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        lesson = self.lesson('Reso bloccato', 'Il reso resta in attesa.', 'Si sblocca la rotta dei resi.')
        rule = self.env['memory.note'].browse(self.note_as(
            self.lead, name='Resi mai in produzione', body='Agents never test the returns route on production.')['id'])
        outcome = self.cron()
        self.assertEqual(outcome['deleted'], 0)
        self.assertGreaterEqual(outcome['embedded'], 3, "the task, the fact and the lesson")
        self.assertEqual(len(self.rows(fact)), 1)
        self.assertEqual(len(self.rows(lesson)), 1)
        self.assertEqual(self.rows(self.task).mapped('chunk'), [0], "the title and the description of the task")
        self.assertFalse(self.rows(rule), "a rule never gets a vector: the pack gives it by chain")
        self.assertEqual(self.cron()['embedded'], 0, "nothing changed, nothing is computed again")
        # a message of the chatter is a chunk of its own, keyed by its id
        posted = self.task.with_user(self.member)._texo_post_note("Il rientro dal cliente era in attesa.")
        message_id = posted['message_id']
        self.assertEqual(self.cron()['embedded'], 1)
        self.assertEqual(self.rows(self.task).mapped('chunk'), [0, message_id])
        self.env['mail.message'].browse(message_id).sudo().unlink()
        self.assertEqual(self.cron()['deleted'], 1)
        self.assertEqual(self.rows(self.task).mapped('chunk'), [0])
        # a changed text is computed again; a record out of the scope loses its vector
        before = self.rows(fact).text_hash
        fact.write({'body': 'I resi dei clienti tornano con una rotta dedicata dal magazzino.'})
        self.assertEqual(self.cron()['embedded'], 1)
        self.assertNotEqual(self.rows(fact).text_hash, before)
        fact.write({'state': 'superseded'})
        lesson.write({'state': 'archived'})
        self.task.action_archive()
        self.assertEqual(self.cron()['deleted'], 3)
        self.assertFalse(self.rows(fact) or self.rows(lesson) or self.rows(self.task))
        # a to-do without a project is not an episode
        todo = self.env['project.task'].with_user(self.member).create({'name': 'Call the supplier back'})
        self.cron()
        self.assertFalse(self.rows(todo))
        # another model: every vector is computed again, the rows say which model they hold (a live
        # record of the scope first: everything above left it, and a clean database has nothing else)
        self.fact('Fatturazione', 'Le fatture si emettono a fine mese.')
        self.cron()
        self.env['ir.config_parameter'].sudo().set_str(memory_embedding.PARAM_MODEL, 'test/other')
        self.assertGreaterEqual(self.cron()['embedded'], 1)
        self.assertEqual(set(Embedding.search([]).mapped('model_name')), {'test/other'})

    def test_the_cron_works_off_a_backlog_in_committed_batches(self):
        """Inside the cron every batch is committed through ir.cron._commit_progress and the run
        stops when its time is up; the rest stays pending for the next run, nothing is lost."""
        for n in range(memory_embedding.BATCH + 5):
            self.fact(f'Fatto {n}', f'Le fatture del fornitore numero {n} si registrano a fine mese.')
        calls = []

        def progress(cron_self, processed=0, *, remaining=None, deactivate=False):
            calls.append((processed, remaining))
            return 0 if processed else 60  # the time is up after the first batch

        with patch.object(type(self.env['ir.cron']), '_commit_progress', progress), self.no_thread_limit():
            outcome = self.env['memory.embedding'].with_context(cron_id=1)._cron_embed()
        self.assertEqual(calls[0][0], 0, "the run first says how much it has to do")
        self.assertGreater(calls[0][1], memory_embedding.BATCH)
        self.assertEqual(outcome['embedded'], memory_embedding.CRON_BATCH, "one batch, then the time was up")
        self.assertGreater(outcome['pending'], 0)
        rest = self.cron()
        self.assertEqual(rest['embedded'], outcome['pending'], "outside the cron the rest in one go, no commit")
        self.assertEqual(self.cron()['embedded'], 0)

    def test_the_cron_reports_no_work_without_a_service(self):
        """Without an endpoint nothing is computed: the cron does not announce a backlog it
        cannot work off (ir.cron would log a warning at every run)."""
        self.fact('Fatturazione', 'Le fatture si emettono a fine mese.')
        self.env['ir.config_parameter'].sudo().set_str(PARAM_ENDPOINT, '')
        calls = []

        def progress(cron_self, processed=0, *, remaining=None, deactivate=False):
            calls.append((processed, remaining))
            return 60

        with patch.object(type(self.env['ir.cron']), '_commit_progress', progress):
            outcome = self.env['memory.embedding'].with_context(cron_id=1)._cron_embed()
        self.assertEqual(calls, [])
        self.assertEqual((outcome['embedded'], outcome['skipped']), (0, 'endpoint'))
        self.assertGreater(outcome['pending'], 0)

    def no_thread_limit(self):
        return patch.object(memory_embedding, 'config', {'limit_time_real_cron': -1, 'limit_time_real': 0})

    def cron_run(self, times, embed=fake_embed):
        """_cron_embed inside a cron whose _commit_progress answers the given times left, the
        last one ever after; the calls to the service, with their timeouts."""
        answers, calls = list(times), []

        def progress(cron_self, processed=0, *, remaining=None, deactivate=False):
            return answers.pop(0) if len(answers) > 1 else answers[0]

        def service(embedding_self, texts, kind='passage', timeout=None):
            calls.append((len(texts), timeout))
            return embed(embedding_self, texts, kind)

        with patch.object(type(self.env['ir.cron']), '_commit_progress', progress), \
                patch.object(self.EmbeddingClass, '_embed', service):
            return self.env['memory.embedding'].with_context(cron_id=1)._cron_embed(), calls

    def test_the_cron_sends_no_batch_without_the_time_for_it(self):
        """A batch is sent only with more than CRON_MARGIN seconds left, counted on the time of
        the job and on the real-time limit of the cron thread, whichever ends first: a call
        still running at that limit makes the whole server reload."""
        for n in range(3):
            self.fact(f'Fatto {n}', f'Le fatture del fornitore numero {n} si registrano a fine mese.')
        with self.no_thread_limit():
            outcome, calls = self.cron_run([memory_embedding.CRON_MARGIN - 1])
        self.assertEqual((outcome['embedded'], calls), (0, []), "the job has no time left: no call")
        self.assertGreater(outcome['pending'], 0)
        thread = threading.current_thread()
        had = getattr(thread, 'start_time', None)
        thread.start_time = time.time() - 100  # the cron thread entered the database 100 s ago
        try:
            with patch.object(memory_embedding, 'config', {'limit_time_real_cron': -1, 'limit_time_real': 120}):
                outcome, calls = self.cron_run([300])
        finally:
            thread.start_time = had
        self.assertEqual((outcome['embedded'], calls), (0, []), "the job has time, the thread has 20 s: no call")
        with self.no_thread_limit():
            outcome, calls = self.cron_run([300])
        self.assertGreaterEqual(outcome['embedded'], 3, "the facts, and the task of the fixtures")
        self.assertEqual(outcome['pending'], 0)
        self.assertEqual(calls[0][1], 300 - memory_embedding.CRON_MARGIN / 2, "the call ends before the time of the job")

    def test_the_cron_waits_for_twice_its_slowest_batch_and_bounds_the_call(self):
        """After a batch the run sends another only with twice the time of its slowest batch
        left; each call may last no longer than the time left, less half the margin."""
        for n in range(memory_embedding.CRON_BATCH + 5):
            self.fact(f'Fatto {n}', f'Le fatture del fornitore numero {n} si registrano a fine mese.')

        def slow(embedding_self, texts, kind='passage'):
            time.sleep(0.2)
            return fake_embed(embedding_self, texts, kind)

        with self.no_thread_limit(), patch.object(memory_embedding, 'CRON_MARGIN', 0):
            outcome, calls = self.cron_run([1.0, 0.3], embed=slow)
        self.assertEqual(outcome['embedded'], memory_embedding.CRON_BATCH, "0.3 s left, a batch took 0.2 s: stop")
        self.assertEqual(calls, [(memory_embedding.CRON_BATCH, 1.0)])
        self.assertGreater(outcome['pending'], 0)

    def test_hybrid_finds_a_paraphrase_and_keeps_the_lexical_hits(self):
        returns = self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        invoices = self.fact('Fatturazione', 'Le fatture si emettono a fine mese.')
        self.cron()
        lexical = self.search(self.member, 'restituzioni', scope='facts', mode='lexical')
        self.assertEqual(lexical, [], "another word for the same thing: the words do not find it")
        self.assertNotIn('match', self.search(self.member, 'resi', scope='facts', mode='lexical')[0])
        hybrid = self.search(self.member, 'restituzioni', scope='facts')
        self.assertEqual(hybrid[0]['id'], returns.id, "the vectors do, in the configured mode (hybrid)")
        self.assertEqual((hybrid[0]['match'], hybrid[0]['fact']), ('semantic', True))
        self.assertGreater(hybrid[0]['similarity'], 0.8)
        self.assertLess(hybrid[0]['score'], 1, "the score of a hybrid hit is its fused rank, not a similarity")
        both = self.search(self.member, 'fatture', scope='facts', mode='hybrid')
        self.assertEqual((both[0]['id'], both[0]['match']), (invoices.id, 'both'), "found by the words and by the vectors")
        self.assertEqual([r['id'] for r in both], [invoices.id, returns.id], "what only the vectors found fills the rest")
        self.assertEqual((both[0]['words'], both[1].get('words')), ('all', None))
        self.assertEqual((both[0]['ranks'], both[1]['ranks']), ({'lexical': 1, 'semantic': 1}, {'semantic': 2}),
                         "the explanation of a fused score: the rank in each list")
        # a hit of every word stays ahead of what only the vectors found, however many they are:
        # an acronym is far from every vector, the question has no other word
        vdi = self.fact('VDI', 'Resi, rotte, fornitori, fatture e rilasci: dal cliente solo via VDI, mai dal portatile.')
        for n in range(11):
            self.fact(f'Nota {n}', 'Un reso con una rotta.')
        self.cron()
        found = self.search(self.member, 'VDI', scope='facts')
        self.assertEqual((found[0]['id'], found[0]['match'], found[0]['words']), (vdi.id, 'lexical', 'all'))
        self.assertEqual([r['match'] for r in found[1:]], ['semantic'] * 4)
        semantic = self.search(self.member, 'restituzioni', scope='facts', mode='semantic', limit=1)
        self.assertEqual((semantic[0]['id'], semantic[0]['match'], semantic[0]['score']),
                         (returns.id, 'semantic', semantic[0]['similarity']))
        # the scopes without vectors stay lexical whatever the mode
        rule_id = self.note_as(self.lead, name='Resi', body='Agents never delete a return.')['id']
        found = self.search(self.member, 'return', scope='rules', mode='semantic')
        self.assertEqual([r['id'] for r in found], [rule_id])
        self.assertNotIn('match', found[0])
        self.assertEqual(self.search(self.member, 'restituzioni', scope='rules', mode='semantic'), [])
        # all: the facts and the lessons by meaning, the rules by their words
        lesson = self.lesson('Restituzioni ferme', 'Le restituzioni non avanzano.', 'Correggere il percorso.')
        self.cron()
        everything = self.search(self.member, 'rientri dei clienti', scope='all')
        self.assertEqual([r['id'] for r in everything if r.get('fact')][0], returns.id)
        self.assertEqual([r['id'] for r in everything if r.get('lesson')], [lesson.id])
        self.assertNotIn(rule_id, [r['id'] for r in everything if r['kind'] == 'rule'])
        # the episodes: the task first; the other tasks the member may read fill the list
        episodes = self.search(self.member, 'rientri dalla clientela', scope='tasks')
        self.assertEqual((episodes[0]['id'], episodes[0]['task'], episodes[0]['match']), (self.task.id, True, 'semantic'))
        with self.assertRaises(UserError):
            self.search(self.member, 'resi', mode='magic')
        self.env['ir.config_parameter'].sudo().set_str(PARAM_MODE, 'lexical')
        self.assertEqual(self.search(self.member, 'restituzioni', scope='facts'), [], "the configured mode")

    def test_documents_and_procedures_by_meaning(self):
        """A document by the title, summary and keywords, then by each piece of its converted text;
        a procedure as a fact; a sensitive document by its summary only; never a rule."""
        filler = " ".join(["Il magazzino centrale lavora su due turni con carico e scarico in banchina."] * 30)
        text = f"{filler}\n\nI resi dei clienti tornano con una rotta dedicata e una sotto-ubicazione propria.\n\n{filler}"
        written = self.env['ir.attachment'].with_user(self.member)._texo_write(
            name='Manuale di magazzino', url='https://docs.example.com/manuale', project_id=self.project.id,
            summary='Come si registrano le fatture dei fornitori.', text=text)
        document = self.env['ir.attachment'].browse(written['id'])
        procedure = self.env['memory.note'].create({
            'name': 'Come si chiude un rientro', 'body': 'Si controlla il collo, poi si conferma la ricezione del reso.',
            'kind': 'procedure', 'state': 'active', 'project_id': self.project.id})
        rule = self.env['memory.note'].browse(self.note_as(
            self.lead, name='Resi mai in produzione', body='Agents never test the returns route on production.')['id'])
        self.cron()
        chunks = self.rows(document).mapped('chunk')
        self.assertEqual(chunks[0], 0, "the title, the summary and the keywords")
        self.assertGreaterEqual(len(chunks), 4, "then the pieces of the converted text")
        self.assertEqual(len(self.rows(procedure)), 1)
        self.assertFalse(self.rows(rule))
        self.assertEqual(self.search(self.member, 'restituzioni', scope='documents', mode='lexical'), [],
                         "another word for the same thing: the words do not find it")
        found = self.search(self.member, 'restituzioni', scope='documents')
        self.assertEqual((found[0]['id'], found[0]['match'], found[0]['document']), (document.id, 'semantic', True),
                         "a piece deep in the text finds its document")
        answered = self.env['memory.document.passage'].search([('attachment_id', '=', document.id),
                                                                ('start', '=', found[0]['passage']['start'])])
        self.assertIn('rotta dedicata', answered.text, "and says which passage answered")
        self.assertEqual(self.search(self.member, 'restituzioni', scope='procedures')[0]['id'], procedure.id)
        found_all = {r['id'] for r in self.search(self.member, 'restituzioni', scope='all', mode='semantic')}
        self.assertTrue({document.id, procedure.id} <= found_all)
        self.assertNotIn(rule.id, found_all, "a rule is found by its words only")
        # a sensitive document: the memory keeps no text of it, so no vector of its text either
        self.env['ir.attachment'].with_user(self.member)._texo_write(document_id=document.id, keep_text=False)
        self.cron()
        self.assertEqual(self.rows(document).mapped('chunk'), [0])
        self.assertEqual(self.search(self.outsider, 'restituzioni', scope='documents', mode='semantic'), [],
                         "the documents of a followers-only project do not exist for who is not on it")

    def test_a_vector_per_passage_with_its_path(self):
        """The passages of the structure are the chunks of a document; the vector of a passage carries
        the title of the document and its path; the hybrid keeps the passage that answered."""
        text = ("# Regolamento resi\n\n## Art. 1.\n## Oggetto\n1. Il regolamento disciplina il magazzino.\n\n"
                "## Art. 2.\n## Resi\n1. I resi dei clienti tornano con una rotta dedicata.\n"
                "2. La rotta ha una sotto-ubicazione propria.\n")
        written = self.env['ir.attachment'].with_user(self.member)._texo_write(
            name='Regolamento di magazzino', url='https://docs.example.com/regolamento', project_id=self.project.id,
            summary='Le regole del magazzino.', text=text)
        document = self.env['ir.attachment'].browse(written['id'])
        passages = self.env['memory.document.passage'].search([('attachment_id', '=', document.id)])
        self.cron()
        self.assertEqual(self.rows(document).mapped('chunk'), [0] + passages.mapped('sequence'))
        texts = self.env['memory.embedding']._texts()
        resi = passages.filtered(lambda p: 'Art. 2' in p.path)
        self.assertTrue(texts[('ir.attachment', document.id, resi.sequence)].startswith(
            'Regolamento di magazzino > Art. 2 (Resi)'))
        found = self.search(self.member, 'restituzioni', scope='documents')
        self.assertEqual(found[0]['passage']['path'], 'Art. 2 (Resi)')
        self.assertEqual(found[0]['passage']['start'], resi.start)
        both = self.search(self.member, 'rotta resi', scope='documents')
        self.assertEqual((both[0]['match'], both[0]['passage']['path']), ('both', 'Art. 2 (Resi)'))
        # inside the document the vectors choose the passage, the nearest first, the others after
        self.assertEqual([p['path'] for p in both[0]['passages']][:1], ['Art. 2 (Resi)'])
        self.assertEqual(len(both[0]['passages']), len(passages[:3]))
        self.assertEqual(self.env['memory.embedding']._pending()['pending'], 0)

    def test_only_what_the_user_may_read(self):
        fact = self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        self.cron()
        self.assertEqual(self.search(self.outsider, 'restituzioni', scope='facts', mode='semantic'), [],
                         "a followers-only project: its facts do not exist for who is not on it")
        self.assertNotIn(self.task.id, [r['id'] for r in self.search(self.outsider, 'restituzioni', scope='tasks',
                                                                     mode='semantic')], "nor its tasks")
        self.assertEqual([r['id'] for r in self.search(self.member, 'restituzioni', scope='facts', mode='semantic')],
                         [fact.id])
        self.assertEqual(self.search(self.member, 'restituzioni', scope='tasks', mode='semantic')[0]['id'], self.task.id)
        # the access rules are in the query of the nearest chunks: more nearer facts the member may not
        # read than the candidates read per search, and the readable one is still found
        hidden = self.env['project.project'].create({'name': 'Hidden', 'privacy_visibility': 'followers'})
        self.env['memory.note'].create([{'name': f'Resi {i}', 'body': 'Resi resi resi: restituzioni dei clienti.',
                                         'kind': 'fact', 'state': 'active', 'project_id': hidden.id}
                                        for i in range(memory_embedding.CANDIDATES + 10)])
        self.cron()
        self.assertEqual([r['id'] for r in self.search(self.member, 'restituzioni', scope='facts', mode='semantic')],
                         [fact.id])

    def test_the_service_down_falls_back_to_lexical(self):
        fact = self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        self.cron()
        down = patch.object(memory_embedding.requests, 'post', side_effect=requests.ConnectionError('down'))
        with patch.object(self.EmbeddingClass, '_embed', self.real_embed), down, self.assertLogs(LOGGER, 'WARNING') as log:
            self.assertEqual(self.search(self.member, 'restituzioni', scope='facts'), [])
            self.assertEqual([r['id'] for r in self.search(self.member, 'resi', scope='facts')], [fact.id])
            self.assertEqual(self.cron()['pending'], 0, "nothing to compute: no call")
            fact.write({'body': 'I resi dei clienti tornano con una rotta dedicata dal magazzino.'})
            self.assertEqual(self.cron(), {'embedded': 0, 'deleted': 0, 'pending': 1}, "it waits for the next run")
        self.assertTrue(all('did not answer' in line for line in log.output), log.output)
        # the service answers with vectors of another size: a misconfiguration, said once per call
        answer = patch.object(memory_embedding.requests, 'post')
        with patch.object(self.EmbeddingClass, '_embed', self.real_embed), answer as post, self.assertLogs(LOGGER, 'WARNING'):
            post.return_value.json.return_value = [[0.1, 0.2]]
            self.assertIsNone(self.env['memory.embedding']._embed(['a text']))
            self.assertEqual(post.call_args.kwargs['json'], {'inputs': ['a text'], 'truncate': True})

    def test_the_api_of_llamacpp(self):
        Params = self.env['ir.config_parameter'].sudo()
        Params.set_str(PARAM_API, 'llamacpp')
        answer = patch.object(memory_embedding.requests, 'post')
        with patch.object(self.EmbeddingClass, '_embed', self.real_embed), answer as post:
            # the vectors come back in the order of their index, whatever the order of the list
            post.return_value.json.return_value = {'data': [
                {'index': 1, 'embedding': [0.0] * (DIMENSIONS - 1) + [1.0]},
                {'index': 0, 'embedding': [1.0] + [0.0] * (DIMENSIONS - 1)}]}
            vectors = self.env['memory.embedding']._embed(['first', 'second'])
            self.assertEqual(post.call_args.args[0], 'http://tei:80/v1/embeddings')
            self.assertEqual(post.call_args.kwargs['json'], {'input': ['first', 'second']})
            self.assertEqual([vector[0] for vector in vectors], [1.0, 0.0])
            # an answer without data is a service that did not answer: no vectors, a warning
            post.return_value.json.return_value = {'error': {'message': 'too long'}}
            with self.assertLogs(LOGGER, 'WARNING') as log:
                self.assertIsNone(self.env['memory.embedding']._embed(['first']))
            self.assertIn('did not answer', log.output[0])

    def test_a_remote_endpoint_needs_the_opt_in(self):
        Embedding = self.env['memory.embedding']
        for host in ('tei', 'localhost', '127.0.0.1', '10.0.0.5', '192.168.1.37', 'host.docker.internal', 'db.lan'):
            self.assertTrue(Embedding._is_local(host), host)
        for host in ('api.example.com', '8.8.8.8', 'tei.example.org'):
            self.assertFalse(Embedding._is_local(host), host)
        Params = self.env['ir.config_parameter'].sudo()
        Params.set_str(PARAM_ENDPOINT, 'https://api.example.com/v1/')
        with self.assertLogs(LOGGER, 'WARNING') as log:
            self.assertIsNone(Embedding._endpoint())
        self.assertIn('not on the local network', log.output[0])
        Params.set_bool(PARAM_ALLOW_REMOTE, True)
        self.assertEqual(Embedding._endpoint(), 'https://api.example.com/v1')
        Params.set_str(PARAM_ENDPOINT, '')
        self.assertIsNone(Embedding._endpoint(), "no endpoint, no vectors")
        with patch.object(self.EmbeddingClass, '_embed', self.real_embed):
            self.assertIsNone(Embedding._embed(['a text']), "and no call")

    def test_the_dimensions_follow_the_model(self):
        Embedding = self.env['memory.embedding']
        self.fact('Resi', 'I resi dei clienti tornano con una rotta dedicata.')
        self.cron()
        self.assertEqual(Embedding._column_type(), f"vector({DIMENSIONS})")
        self.assertTrue(Embedding.search([]))
        self.env['ir.config_parameter'].sudo().set_int(PARAM_DIMENSIONS, 5)
        self.assertTrue(Embedding._ensure_schema())
        self.assertEqual(Embedding._column_type(), "vector(5)")
        self.assertFalse(Embedding.search([]), "the vectors of another size are gone: the cron computes them again")
        self.env['ir.config_parameter'].sudo().set_int(PARAM_DIMENSIONS, DIMENSIONS)
        Embedding._ensure_schema()
        self.assertGreaterEqual(self.cron()['embedded'], 1)

    def test_near_duplicates_by_meaning(self):
        Lesson = self.env['memory.lesson']
        first = self.lesson('Reso bloccato', 'Il reso del cliente resta in attesa.', 'Si sblocca la rotta dei resi.')
        second = self.lesson('Restituzioni ferme', 'Le restituzioni non avanzano.', 'Correggere il percorso delle restituzioni.')
        other = self.lesson('Fatture in ritardo', 'Le fatture escono tardi.', 'Emettere le fatture a fine mese.')
        self.assertEqual(Lesson._duplicate_pairs(lessons=first | second | other), [],
                         "without vectors yet, difflib: two different texts")
        self.cron()
        pairs = Lesson._duplicate_pairs(lessons=first | second | other)
        self.assertEqual([(a.id, b.id) for a, b, _ in pairs], [(first.id, second.id)])
        self.assertGreaterEqual(pairs[0][2], 80)
        # about different things (a tag each): not a pair, however close
        tags = self.env['project.tags'].create([{'name': 'returns'}, {'name': 'invoicing'}])
        first.write({'tag_ids': [(6, 0, tags[0].ids)]})
        second.write({'tag_ids': [(6, 0, tags[1].ids)]})
        self.assertEqual(Lesson._duplicate_pairs(lessons=first | second | other), [])
        second.write({'tag_ids': [(6, 0, tags[0].ids)]})
        self.assertEqual(len(Lesson._duplicate_pairs(lessons=first | second | other)), 1)
        # a lesson without a vector yet is compared by difflib with the others
        twin = self.lesson('Fatture in ritardo', 'Le fatture escono tardi.', 'Emettere le fatture a fine mese!')
        pairs = Lesson._duplicate_pairs(lessons=first | second | other | twin)
        self.assertEqual([(a.id, b.id) for a, b, _ in pairs], [(first.id, second.id), (other.id, twin.id)])
        self.assertGreaterEqual(Lesson._cron_housekeeping()['duplicates'], 2)
