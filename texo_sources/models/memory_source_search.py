# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The cards of the external sources in the search of the memory: scope sources, and in all.

A card is found by its words as a note is: the title weighs most, then what it is about (public
persons, bodies, places, themes, acts, keywords), then what it says (abstract, quotes, the note of
the triage). The labels live in other tables, so the vector is a plain column written here when
the card or a label changes (as the episodes of texo_memory), not a generated one. Only
the active cards: a candidate is not knowledge yet, a card waiting for its approval names persons
nobody has checked. Raw SQL on purpose: tsvector has no ORM form."""
from odoo import api, models

from odoo.addons.texo import okf
from odoo.addons.texo_memory.models import fulltext

SNIPPET = 160
LIVE = ('active',)
# what the vector is made of: a write of one of these refreshes it
TSV_FIELDS = {'title', 'keywords', 'acts', 'abstract', 'quotes', 'triage_note', 'person_ids', 'body_ids', 'place_ids',
              'theme_ids', 'state'}
TSV = ("setweight(to_tsvector('simple', %(a)s), 'A') || "
       "setweight(to_tsvector('simple', %(b)s), 'B') || setweight(to_tsvector('italian', %(b)s), 'B') || "
       "setweight(to_tsvector('english', %(b)s), 'B') || "
       "setweight(to_tsvector('simple', %(c)s), 'C') || setweight(to_tsvector('italian', %(c)s), 'C') || "
       "setweight(to_tsvector('english', %(c)s), 'C')")
REFRESH_BATCH = 500


class MemorySourceItem(models.Model):
    _inherit = 'memory.source.item'

    def init(self):
        self.env.cr.execute("ALTER TABLE memory_source_item ADD COLUMN IF NOT EXISTS search_tsv tsvector")
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS memory_source_item_search_tsv_idx ON memory_source_item "
                            "USING gin (search_tsv)")
        # the cards of before this column get their vector once, at install or update
        self.env.cr.execute("SELECT id FROM memory_source_item WHERE search_tsv IS NULL AND state IN %s ORDER BY id",
                            (LIVE,))
        ids = [row[0] for row in self.env.cr.fetchall()]
        for start in range(0, len(ids), REFRESH_BATCH):
            self.sudo().browse(ids[start:start + REFRESH_BATCH])._search_refresh()

    def _search_texts(self):
        """(title, what it is about, what it says) of the card, as the search reads them."""
        self.ensure_one()
        about = " ".join(filter(None, [self.keywords, self.acts] + (self.person_ids | self.body_ids | self.place_ids
                                                                    | self.theme_ids).mapped('name')))
        says = " ".join(filter(None, [self.abstract, self.quotes, self.triage_note]))
        return self.title or '', about, says

    def _search_refresh(self):
        """Write the search vector of these cards; none for a card that is not active."""
        if not self.ids:
            return
        cr = self.env.cr
        for item in self.sudo():
            if item.state in LIVE:
                title, about, says = item._search_texts()
                cr.execute(f"UPDATE memory_source_item SET search_tsv = {TSV} WHERE id = %(id)s",
                           {'a': title, 'b': about, 'c': says, 'id': item.id})
            else:
                cr.execute("UPDATE memory_source_item SET search_tsv = NULL WHERE id = %s", (item.id,))

    @api.model_create_multi
    def create(self, vals_list):
        items = super().create(vals_list)
        items._search_refresh()
        return items

    def write(self, vals):
        result = super().write(vals)
        if vals.keys() & TSV_FIELDS:
            self._search_refresh()
        return result

    @api.model
    def _search_domain(self):
        return [('state', 'in', LIVE)]

    def _search_entries(self, ranked):
        """The search results of these cards, in this order, flagged as cards: the score and the words
        (fulltext.fields of ranked), the channel, the event date, the link and the first words of the abstract."""
        return [{'id': item.id, 'concept': okf.concept_id(item), 'title': item.title, 'source': True,
                 'state': item.state, 'channel': item.channel_id.name, 'url': item.url,
                 'event_date': item.event_date and item.event_date.isoformat() or None,
                 'persons': item.person_ids.mapped('name'), 'themes': item.theme_ids.mapped('name'),
                 'snippet': " ".join((item.abstract or item.triage_note or '').split())[:SNIPPET],
                 **fulltext.fields(ranked, item.id)} for item in self]

    @api.model
    def _search_words(self, query, related_terms=None, limit=5):
        limit = max(1, min(int(limit or 5), 20))
        self.flush_model()
        items, ranked = fulltext.search(self, 'memory_source_item', 'search_tsv', fulltext.words(query, related_terms),
                                        limit, self._search_domain(), where="search_tsv IS NOT NULL")
        return items._search_entries(ranked)


class MemorySourceTag(models.Model):
    _inherit = 'memory.source.tag'

    def write(self, vals):
        result = super().write(vals)
        if 'name' in vals:
            Item = self.env['memory.source.item'].sudo()
            Item.search(['|', '|', '|', ('person_ids', 'in', self.ids), ('body_ids', 'in', self.ids),
                         ('place_ids', 'in', self.ids), ('theme_ids', 'in', self.ids)])._search_refresh()
        return result


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model
    def _agent_search_extra(self, query, related_terms, scope, limit):
        results = super()._agent_search_extra(query, related_terms, scope, limit)
        if scope in ('all', 'sources'):
            results += self.env['memory.source.item']._search_words(query, related_terms, limit)
        return results
