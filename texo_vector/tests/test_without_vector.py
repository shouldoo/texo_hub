# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Without the extension vector (or before the cron ran) the hub answers as before: these
tests make the vectors unavailable on purpose, so they say the same on every database."""
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.texo_memory.tests.common import MemoryCase


@tagged('post_install', '-at_install')
class TestWithoutVector(MemoryCase):

    def setUp(self):
        super().setUp()
        self.EmbeddingClass = type(self.env['memory.embedding'])
        for method in ('_available', '_ensure_schema'):
            patcher = patch.object(self.EmbeddingClass, method, return_value=False)
            patcher.start()
            self.addCleanup(patcher.stop)

    def search(self, user, query, **kwargs):
        return self.env['memory.note'].with_user(user)._agent_search(query, **kwargs)

    def test_the_search_stays_lexical(self):
        fact = self.env['memory.note'].create({'name': 'Resi', 'body': 'I resi dei clienti tornano con una rotta dedicata.',
                                               'kind': 'fact', 'state': 'active', 'project_id': self.project.id})
        for mode in (None, 'lexical', 'semantic', 'hybrid'):
            found = self.search(self.member, 'resi', scope='facts', mode=mode)
            self.assertEqual([r['id'] for r in found], [fact.id], mode)
            self.assertNotIn('match', found[0], "a lexical hit, nothing more to say")
            self.assertEqual(self.search(self.member, 'restituzioni', scope='facts', mode=mode), [], mode)
        self.assertEqual(self.env['memory.embedding']._mode('hybrid'), 'lexical')

    def test_the_cron_waits_for_the_extension(self):
        self.assertEqual(self.env['memory.embedding']._cron_embed(), {'skipped': 'extension'})

    def test_the_near_duplicates_by_difflib(self):
        Lesson = self.env['memory.lesson']
        first = Lesson.create({'name': 'Fatture in ritardo', 'finding': 'Le fatture escono tardi.',
                               'solution': 'Emettere le fatture a fine mese.', 'state': 'active'})
        twin = Lesson.create({'name': 'Fatture in ritardo', 'finding': 'Le fatture escono tardi.',
                              'solution': 'Emettere le fatture a fine mese!', 'state': 'active'})
        self.assertEqual([(a.id, b.id) for a, b, _ in Lesson._duplicate_pairs(lessons=first | twin)], [(first.id, twin.id)])
