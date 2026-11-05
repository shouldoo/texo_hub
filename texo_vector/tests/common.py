# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""A fake embedding service for the tests: a vector of seven dimensions, one per concept the
texts of the tests talk about (a word in Italian or English, singular or plural, lands on
the same concept) plus a little noise so no vector is zero. The real service is patched
out: no network, and a paraphrase («restituzioni» for «resi») is near where the words are
not, which is what the vectors are for."""
import math
import re
import unittest
from unittest.mock import patch

from odoo.tests.common import TransactionCase

from odoo.addons.texo_memory.tests.common import MemoryFixtures

from ..models.memory_embedding import PARAM_DIMENSIONS, PARAM_ENDPOINT, PARAM_MODEL

CONCEPTS = {
    'return': {'return', 'returns', 'reso', 'resi', 'restituzione', 'restituzioni', 'rientro', 'rientri'},
    'route': {'route', 'routes', 'rotta', 'rotte', 'percorso', 'percorsi', 'instradamento'},
    'supplier': {'supplier', 'suppliers', 'fornitore', 'fornitori', 'vendor'},
    'invoice': {'invoice', 'invoices', 'fattura', 'fatture', 'fatturazione', 'billing'},
    'password': {'password', 'credenziali', 'credentials', 'segreto', 'secret'},
    'deploy': {'deploy', 'deployment', 'rilascio', 'rilasci', 'release'},
}
DIMENSIONS = len(CONCEPTS) + 1
NOISE = 0.3


def fake_vector(text):
    words = re.findall(r'\w+', text.lower())
    counts = [float(sum(1 for word in words if word in synonyms)) for synonyms in CONCEPTS.values()] + [NOISE]
    norm = math.sqrt(sum(count * count for count in counts))
    return [count / norm for count in counts]


def fake_embed(self, texts, kind='passage', timeout=None):
    return [fake_vector(text) for text in texts]


class VectorFixtures(MemoryFixtures):
    """The fixtures of the memory, the fake service in place of the real one and the table
    sized for it; skipped where the extension vector is not available."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Embedding = cls.env['memory.embedding']
        cls.EmbeddingClass = type(Embedding)
        # staticmethod: read from the test, the function must stay a function, not bind to it
        cls.real_embed = staticmethod(cls.EmbeddingClass._embed)
        if not Embedding._ensure_schema():
            raise unittest.SkipTest("the extension vector is not available on this database")
        Params = cls.env['ir.config_parameter'].sudo()
        Params.set_int(PARAM_DIMENSIONS, DIMENSIONS)
        Params.set_str(PARAM_MODEL, 'test/concepts')
        Params.set_str(PARAM_ENDPOINT, 'http://tei:80')
        Embedding._ensure_schema()
        patcher = patch.object(cls.EmbeddingClass, '_embed', fake_embed)
        patcher.start()
        cls.addClassCleanup(patcher.stop)

    def fact(self, name, body, **vals):
        return self.env['memory.note'].create(dict(name=name, body=body, kind='fact', state='active',
                                                   project_id=self.project.id, **vals))

    def lesson(self, name, finding, solution, **vals):
        return self.env['memory.lesson'].create(dict(name=name, finding=finding, solution=solution, state='active', **vals))

    def search(self, user, query, **kwargs):
        return self.env['memory.note'].with_user(user)._agent_search(query, **kwargs)

    def rows(self, record):
        return self.env['memory.embedding'].search([('res_model', '=', record._name), ('res_id', '=', record.id)],
                                                   order='chunk')


class VectorCase(VectorFixtures, TransactionCase):
    pass
