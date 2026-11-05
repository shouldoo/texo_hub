# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The cards of the external sources by meaning. A press clipping, a call or a statement is written
by others and asked about in other words («what did the mayor say about the hospital?»): the
lexical search of texo_sources finds its words, the vector of its card its meaning.

One vector per active card (chunk 0): the title, what it is about (public persons, bodies, places,
themes, acts, keywords) and the abstract written by whoever filled it in. Never the text of the
article: the memory does not keep it."""
from odoo import api, models


class MemoryEmbedding(models.Model):
    _inherit = 'memory.embedding'

    @api.model
    def _sources(self):
        return dict(super()._sources(), **{'memory.source.item': self._texts_of_cards})

    @api.model
    def _texts_of_cards(self):
        Item = self.env['memory.source.item'].sudo()
        rows = []
        for item in Item.search(Item._search_domain()):
            title, about, says = item._search_texts()
            rows.append(('memory.source.item', item.id, 0, f"{title}\n{about}\n{item.abstract or ''}"))
        return rows


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model
    def _semantic_extra(self, vector, scope, limit):
        entries = super()._semantic_extra(vector, scope, limit)
        if scope in ('all', 'sources'):
            Item = self.env['memory.source.item']
            items, similarity = self.env['memory.embedding']._readable(vector, 'memory.source.item',
                                                                       Item._search_domain(), limit)
            entries += items._search_entries({res_id: (None, cosine) for res_id, cosine in similarity.items()})
        return entries
