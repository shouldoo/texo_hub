# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models

from . import hybrid, memory_embedding

# the scopes whose records have vectors; the rules stay lexical (in all, they come from the words only)
SEMANTIC_SCOPES = ('all', 'facts', 'procedures', 'lessons', 'documents', 'tasks', 'sources')
# the kinds of note with vectors, per scope
SEMANTIC_KINDS = {'all': ('fact', 'procedure'), 'facts': ('fact',), 'procedures': ('procedure',)}


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model
    def _agent_search(self, query, related_terms=None, scope='all', applies_to=None, limit=5, mode=None):
        """The search with a mode: lexical (the words, as texo_memory does), semantic
        (the nearest vectors among the episodes, the facts, the procedures, the lessons and the
        documents the user may read)
        or hybrid (both, fused by reciprocal rank: hybrid.py). The configured mode when the
        call gives none; lexical when the vectors are not available here, when the scope has
        none (the rules) or when the embedding service does not answer."""
        Embedding = self.env['memory.embedding']
        mode = Embedding._mode(mode)
        if mode == 'lexical' or scope not in SEMANTIC_SCOPES:
            return super()._agent_search(query, related_terms, scope, applies_to, limit, mode=mode)
        vector = Embedding._embed_query(query)
        if vector is None:
            return super()._agent_search(query, related_terms, scope, applies_to, limit, mode=mode)
        limit = max(1, min(int(limit or 5), 20))
        # each search gives twice the limit, so the fusion has something to choose from
        window = min(max(limit * 2, 10), 20)
        semantic = self._semantic_entries(vector, scope, applies_to, window)
        if mode == 'semantic':
            return self._passages_by_meaning(semantic[:limit], vector)
        lexical = super()._agent_search(query, related_terms, scope, applies_to, window, mode=mode)
        pool = Embedding._rerank_pool()
        if not pool:
            return self._passages_by_meaning(hybrid.fuse(lexical, semantic, limit), vector)
        # the optional reranker (memory_rerank.py) reorders the first pool results, the passages chosen first
        fused = self._passages_by_meaning(hybrid.fuse(lexical, semantic, max(limit, pool)), vector)
        return (self._reranked(query, fused[:pool]) + fused[pool:])[:limit]

    @api.model
    def _passages_by_meaning(self, entries, vector):
        """The passages of each document found, the nearest to the question first, in place of
        those the words chose: inside the right document the vectors name the passage that answers
        far more often (the first in 32 of 40 questions on the demo customers, the words
        in 21). The passage the words found best stays among them."""
        Passage = self.env['memory.document.passage']
        per_hit = memory_embedding.PASSAGES_PER_HIT
        chosen = {}
        for entry in entries:
            if not entry.get('document'):
                continue
            sequences = self.env['memory.embedding']._nearest_in(vector, 'ir.attachment', entry['id'], per_hit)
            if not sequences:
                continue
            words = (entry.get('passages') or [])[:1]
            passages = Passage.sudo().search([('attachment_id', '=', entry['id']), ('sequence', 'in', sequences)])
            passages = passages.sorted(lambda p: sequences.index(p.sequence))
            if words and words[0]['start'] not in passages.mapped('start'):
                passages = (passages[:per_hit - 1] | Passage.sudo().search(
                    [('attachment_id', '=', entry['id']), ('start', '=', words[0]['start'])], limit=1))
            chosen[entry['id']] = passages
        return Passage._annotate(entries, chosen)

    @api.model
    def _semantic_entries(self, vector, scope, applies_to, limit):
        """The entries of the records nearest to the vector in the scope, the user's access rules
        and the domains of the lexical search applied, by similarity (score and similarity are
        the cosine), flagged as the lexical entries are and with match semantic."""
        Embedding = self.env['memory.embedding']
        entries = []

        def ranked(similarity):
            # as fulltext ranks, without the words: the score is the cosine as it is
            return {res_id: (None, cosine) for res_id, cosine in similarity.items()}

        if scope in SEMANTIC_KINDS:
            today = fields.Date.context_today(self)
            notes, similarity = Embedding._readable(
                vector, 'memory.note', self._search_domain(SEMANTIC_KINDS[scope], today), limit)
            entries += notes._search_entries(ranked(similarity), today)
        if scope in ('all', 'lessons'):
            Lesson = self.env['memory.lesson']
            lessons, similarity = Embedding._readable(vector, 'memory.lesson', Lesson._search_domain(applies_to), limit)
            entries += lessons._search_entries(ranked(similarity))
        if scope in ('all', 'documents'):
            Attachment = self.env['ir.attachment']
            documents, nearest = Embedding._readable_chunks(
                vector, 'ir.attachment', Attachment._texo_search_domain(), limit,
                candidates=memory_embedding.DOCUMENT_CANDIDATES)
            similarity = {res_id: value for res_id, (value, _chunk) in nearest.items()}
            # the passages are chosen afterwards, inside each document (_passages_by_meaning)
            entries += documents._texo_search_entries(ranked(similarity))
        if scope == 'tasks':
            Task = self.env['project.task']
            tasks, similarity = Embedding._readable(vector, 'project.task', Task._texo_search_domain(), limit)
            entries += tasks._texo_search_entries(ranked(similarity))
        entries += self._semantic_extra(vector, scope, limit)
        for entry in entries:
            entry.update(similarity=entry['score'], match='semantic')
        return sorted(entries, key=lambda e: (-e['score'], -e['id']))[:limit]

    @api.model
    def _semantic_extra(self, vector, scope, limit):
        """The nearest entries of the scopes other modules add (the cards of the external sources, through
        texo_sources_vector), score the cosine. None here."""
        return []
