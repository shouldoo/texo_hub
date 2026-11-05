# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models

from . import fulltext, structure

# the passages a hit of a document names, the one that answered first: on the scenarios of the
# demo customers the right passage is the first in 3 of 4 questions and among three in 9 of 10
PASSAGES_PER_HIT = 3

# The search vector of a passage: its path weighs above its text, the title of its document
# least (it is the same for every passage of the document, and the document has its own vector).
PASSAGE_TSV = (
    "setweight(to_tsvector('simple', coalesce(path, '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(text, '')), 'C') || "
    "setweight(to_tsvector('italian', coalesce(text, '')), 'C') || "
    "setweight(to_tsvector('english', coalesce(text, '')), 'C') || "
    "setweight(to_tsvector('simple', coalesce(title, '')), 'D')"
)


class MemoryDocumentPassage(models.Model):
    """A passage of the converted text of a document of the memory, cut by its structure
    (structure.py): the full-text search finds a rare word, an article number or an amount in
    an act of hundreds of pages, the vectors are computed on it, and the results say which
    passage answered. Derived from the text, never written by hand: the passages of a document
    are cut again when its text changes. A document whose text is not kept has none.

    No one reads this model directly: the search reads it as the system and gives a passage
    only with a document the user may read."""
    _name = 'memory.document.passage'
    _description = "Memory Document Passage"
    _order = 'attachment_id, sequence'
    _log_access = False

    attachment_id = fields.Many2one('ir.attachment', string="Document", required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(required=True)
    path = fields.Char(help="Where the passage stands in the document, e.g. «Art. 43 > comma 2».")
    title = fields.Char(help="The title of the document, the context of the passage in its vector and its index.")
    start = fields.Integer(help="Offset of the passage in the converted text: read it from there.")
    stop = fields.Integer(help="Offset past the end of the passage in the converted text.")
    text = fields.Text(required=True)

    _unique_sequence = models.Constraint('UNIQUE(attachment_id, sequence)', "One passage per place in a document.")

    def init(self):
        self.env.cr.execute(
            "ALTER TABLE memory_document_passage ADD COLUMN IF NOT EXISTS search_tsv tsvector "
            f"GENERATED ALWAYS AS ({PASSAGE_TSV}) STORED")
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS memory_document_passage_search_tsv_idx ON memory_document_passage "
            "USING gin (search_tsv)")

    def _context(self):
        """The text a vector is computed on: the title of the document and the path before the passage."""
        self.ensure_one()
        head = " > ".join(part for part in (self.title, self.path) if part)
        return f"{head}\n{self.text}" if head else self.text

    def _entry(self, snippet=160):
        """What a search result says of the passage that answered."""
        self.ensure_one()
        return {'path': self.path or None, 'start': self.start, 'snippet': " ".join(self.text.split())[:snippet]}

    @api.model
    def _by_words(self, document_id, word_list, limit=PASSAGES_PER_HIT):
        """The passages of a document that hold the words, the best first (every word, then rank)."""
        ranked = fulltext.rank(self.env.cr, 'memory_document_passage', 'search_tsv', word_list, limit,
                               f"attachment_id = {int(document_id)}")
        return self.sudo().browse(sorted(ranked, key=lambda pid: (not ranked[pid][0], -ranked[pid][1], pid)))

    @api.model
    def _annotate(self, entries, ranked_passages):
        """Put on the entries of documents the passage that answered and the others to read:
        {document id: passages, the best first}."""
        for entry in entries:
            passages = ranked_passages.get(entry['id']) if entry.get('document') else None
            if passages:
                entry['passage'] = passages[0]._entry()
                entry['passages'] = [{'path': p.path or None, 'start': p.start} for p in passages[:PASSAGES_PER_HIT]]
                entry['snippet'] = entry['passage']['snippet']
        return entries

    @api.model
    def _cut(self, documents):
        """Cut the passages of these documents again from their text: those of a document out of
        the memory, or without a kept text, are deleted."""
        documents = documents.sudo()
        self.sudo().search([('attachment_id', 'in', documents.ids)]).unlink()
        vals = []
        for document in documents.filtered('texo_document'):
            source = document._texo_text_source()
            if not source:
                continue
            text = source._texo_plain_text()
            vals += [{'attachment_id': document.id, 'sequence': number, 'title': document.name, 'path': passage['path'],
                      'start': passage['start'], 'stop': passage['end'], 'text': passage['text']}
                     for number, passage in enumerate(structure.passages(text), 1)]
        if vals:
            self.sudo().create(vals)
