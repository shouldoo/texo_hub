# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
import hashlib
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.texo import okf
from odoo.addons.texo.models.secrets import check_no_credential

from . import fulltext

MAX_SUMMARY = 20000
MAX_TEXT = 5 * 1024 * 1024
MAX_ATTACHMENT = 20 * 1024 * 1024
MAX_READ = 6000
SNIPPET = 160
TEXT_MIMETYPE = 'text/markdown'
EXTENSION = re.compile(r'\.[A-Za-z0-9]{1,5}$')
# The search vector of a document, stored on the original and indexed: the title weighs
# most, then the summary and the keywords, then the text (the converted one, or the
# document itself when it is text and may be kept). Written by _texo_refresh_tsv
# whenever one of them changes; an attachment out of the memory has none.
TEXT = "coalesce(x.text, CASE WHEN o.texo_keep_text THEN o.index_content END, '')"
SUMMARY = "coalesce(o.description, '') || ' ' || coalesce(o.texo_keywords, '')"
DOCUMENT_TSV = (
    "setweight(to_tsvector('simple', coalesce(o.name, '')), 'A') || "
    f"setweight(to_tsvector('simple', {SUMMARY}), 'B') || "
    f"setweight(to_tsvector('italian', {SUMMARY}), 'B') || "
    f"setweight(to_tsvector('english', {SUMMARY}), 'B') || "
    f"setweight(to_tsvector('simple', {TEXT}), 'C') || "
    f"setweight(to_tsvector('italian', {TEXT}), 'C') || "
    f"setweight(to_tsvector('english', {TEXT}), 'C')"
)
# What the vector is made of: a write of one of these refreshes it.
TSV_FIELDS = {'name', 'description', 'texo_keywords', 'texo_keep_text', 'texo_document',
              'texo_text_of_id', 'raw', 'datas'}


def _bytes(value):
    """Odoo 20: the content of an attachment is `raw`, a lazily loaded BinaryValue; `datas` is gone."""
    if not value:
        return b''
    return value.content if hasattr(value, 'content') else bytes(value)


class IrAttachment(models.Model):
    """The documents of the memory are attachments of the record they belong to.

    A document is an attachment of a task, a project, a customer or, for the
    organisation's own, the company: a file, or a link (type url) to an original
    that lives elsewhere. Its title is the name of the attachment and its summary
    the description. The memory adds when it was read and the fingerprint of the
    original, and keeps the converted text as a second attachment on the same record,
    so later sessions read it without converting again; the people see both with the
    permissions of that record.
    """
    _inherit = 'ir.attachment'

    texo_document = fields.Boolean(
        string="In the Memory", copy=False, index=True,
        help="A document of the memory: the agents find it in the context pack and in the search.")
    texo_read_on = fields.Date(string="Read On", copy=False, help="When the original was last read.")
    texo_fingerprint = fields.Char(
        string="Fingerprint", copy=False,
        help="sha256 of the original when it was read; a different one at a later reading marks it changed.")
    texo_changed_on = fields.Datetime(
        string="Changed On", copy=False,
        help="When a reading found the original changed: the rules taken from it are to re-check.")
    texo_keep_text = fields.Boolean(
        string="Keep the Converted Text", default=True, copy=False,
        help="Switch it off for a sensitive document: the memory keeps no text of it.")
    texo_text_of_id = fields.Many2one(
        'ir.attachment', string="Converted Text Of", ondelete='cascade', index=True, copy=False,
        help="The original this attachment is the converted text of.")
    texo_text_ids = fields.One2many('ir.attachment', 'texo_text_of_id', string="Converted Text")
    texo_keywords = fields.Char(
        string="Keywords", copy=False,
        help="Synonyms, translations and other names of what the document is about, comma separated: the "
             "search finds it by these words too.")
    texo_text = fields.Text(
        string="Text", compute='_compute_texo_text',
        help="The converted text of the document, to read it here without downloading it; empty for a sensitive "
             "document, whose text the memory does not keep.")
    texo_created = fields.Boolean(
        string="Created by the Memory", copy=False,
        help="The memory brought this attachment in (a link, a file it received, a converted text): "
             "an opt-out of the customer deletes it.")

    def init(self):
        # Raw SQL: a tsvector column and its GIN index have no ORM field; the index is partial,
        # only the documents of the memory have a vector.
        self.env.cr.execute("ALTER TABLE ir_attachment ADD COLUMN IF NOT EXISTS texo_tsv tsvector")
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS ir_attachment_texo_tsv_idx ON ir_attachment "
            "USING gin (texo_tsv) WHERE texo_tsv IS NOT NULL")

    @api.model_create_multi
    def create(self, vals_list):
        attachments = super().create(vals_list)
        attachments._texo_index()
        attachments._texo_documents_touched()._texo_refresh_tsv()
        return attachments

    def unlink(self):
        originals = self.texo_text_of_id - self
        result = super().unlink()
        originals.exists()._texo_refresh_tsv()
        return result

    def write(self, vals):
        result = super().write(vals)
        if 'raw' in vals or 'datas' in vals:
            # a new content of a document already read: the rules taken from it are to re-check
            changed = self.filtered(lambda a: a.texo_document and a.texo_fingerprint)
            if changed:
                super(IrAttachment, changed).write({'texo_changed_on': fields.Datetime.now()})
        if vals.keys() & {'raw', 'datas', 'texo_document', 'texo_text_of_id'}:
            self._texo_index()
        if vals.keys() & TSV_FIELDS:
            self._texo_documents_touched(vals)._texo_refresh_tsv()
        return result

    def _texo_documents_touched(self, vals=None):
        """The originals whose search vector these attachments make: the documents among them
        (all of them when the write puts them in or out of the memory), and the original of a
        converted text. Any other attachment of Odoo is left alone."""
        documents = self if vals and 'texo_document' in vals else self.filtered('texo_document')
        return documents | self.texo_text_of_id

    def _texo_refresh_tsv(self):
        """Write the search vector of these originals from their title, summary, keywords and
        text; none for an attachment that is not a document of the memory."""
        if not self.ids:
            return
        self.flush_model(['name', 'description', 'index_content', 'texo_keywords', 'texo_keep_text',
                          'texo_document', 'texo_text_of_id'])
        # Raw SQL: a tsvector is written by PostgreSQL, the ORM has no such value.
        self.env.cr.execute(
            f"UPDATE ir_attachment o SET texo_tsv = CASE WHEN o.texo_document THEN {DOCUMENT_TSV} END "
            "FROM (SELECT d.id, (SELECT t.index_content FROM ir_attachment t WHERE t.texo_text_of_id = d.id "
            "                    ORDER BY t.id LIMIT 1) AS text FROM ir_attachment d WHERE d.id IN %s) x "
            "WHERE o.id = x.id", [tuple(self.ids)])
        # the passages follow the same text, title and state
        self.env['memory.document.passage']._cut(self)

    def _texo_index(self):
        """The text of the memory indexed whole: the native index keeps only the ASCII words of
        a text, an accented word would be lost."""
        for attachment in self:
            if (attachment.texo_document or attachment.texo_text_of_id) and attachment._texo_is_text():
                # sudo: the index is derived from the content, whoever wrote it
                super(IrAttachment, attachment.sudo()).write(
                    {'index_content': _bytes(attachment.raw).decode('utf-8', errors='replace')})

    # -- reading --------------------------------------------------------------
    def _texo_summary(self):
        result = []
        for document in self:
            entry = {'id': document.id, 'concept': okf.concept_id(document), 'title': document.name, 'type': document.type,
                     'record': {'model': document.res_model, 'id': document.res_id},
                     'has_text': bool(document._texo_text_source()),
                     'fingerprint': document.texo_fingerprint or None}
            if document.type == 'url':
                entry['url'] = document.url
            else:
                entry['mimetype'] = document.mimetype
            if document.texo_read_on:
                entry['read_on'] = fields.Date.to_string(document.texo_read_on)
            if document.texo_changed_on:
                entry['changed_on'] = fields.Datetime.to_string(document.texo_changed_on)
            if document.description:
                entry['summary'] = document.description[:300]
            if document.texo_keywords:
                entry['keywords'] = document.texo_keywords
            result.append(entry)
        return result

    def _texo_is_text(self):
        """A file that is text already (a Markdown procedure, a plain text) needs no conversion."""
        self.ensure_one()
        return self.type == 'binary' and (self.mimetype or '').startswith('text/')

    def _texo_text_source(self):
        """Where the text of a document is: its converted text, or itself when it is text."""
        self.ensure_one()
        if not self.texo_keep_text:
            return self.browse()
        return self.texo_text_ids[:1] or (self if self._texo_is_text() else self.browse())

    def _texo_plain_text(self):
        """The content of a text attachment as a string: the offsets of the passages and of a reading count in it."""
        self.ensure_one()
        return _bytes(self.raw).decode('utf-8', errors='replace')

    @api.depends('texo_keep_text', 'texo_text_ids')
    def _compute_texo_text(self):
        for document in self:
            source = document.texo_document and document._texo_text_source()
            document.texo_text = source._texo_plain_text() if source else False

    def _texo_read(self, text=False, max_chars=MAX_READ, offset=0):
        self.ensure_one()
        result = self._texo_summary()[0]
        result['summary'] = self.description or None
        source = self._texo_text_source()
        if text and source:
            content = _bytes(source.raw).decode('utf-8', errors='replace')
            offset = max(0, int(offset or 0))
            result['text'] = content[offset:offset + max_chars]
            result['text_total'] = len(content)
            if offset + max_chars < len(content):
                result['text_next_offset'] = offset + max_chars
        return result

    def _okf_concept(self, text=False, max_chars=MAX_READ, offset=0):
        """The document as an OKF concept: type Document, the original as its resource, read
        by the person who brought it in, its summary and, with text, a slice of its text.
        A document is the source the rules and the facts cite."""
        self.ensure_one()
        read = self._texo_read(text, max_chars, offset)
        base = self.get_base_url()
        record = self.env[self.res_model].browse(self.res_id) if self.res_model in okf.KINDS and self.res_id else None
        anchor = 'organisation' if self.res_model == 'res.company' else (okf.link(record) if record else None)
        meta = {
            'type': 'Document', 'title': self.name, 'description': okf.description(self.description),
            'resource': self.url if self.type == 'url' else f"{base}/web/content/{self.id}",
            'status': 'stable',
            'generated': {'by': okf.human(self.create_uid), 'at': okf.timestamp(self.texo_read_on or self.write_date)},
            'anchor': anchor,
            'last_modified': okf.timestamp(self.texo_changed_on),
            'mimetype': self.mimetype if self.type != 'url' else None,
            'fingerprint': self.texo_fingerprint or None, 'keywords': self.texo_keywords or None,
            'text_total': read.get('text_total'), 'text_next_offset': read.get('text_next_offset'),
        }
        body = self.description or ''
        if read.get('text'):
            body += f"\n\n# Text\n\n{read['text']}"
        return okf.concept(meta, body)

    @api.model
    def _texo_documents_of(self, record, limit=None):
        """The documents of the memory on one record, in creation order."""
        return self.search([('res_model', '=', record._name), ('res_id', '=', record.id),
                            ('texo_document', '=', True)], order='id', limit=limit)

    @api.model
    def _texo_document(self, document_id):
        """A document of the memory the user may read."""
        document = self.browse(int(document_id)).exists()
        if not document or not document.texo_document or not document.has_access('read'):
            raise UserError(self.env._("Document %s does not exist or is not visible to you.", document_id))
        return document

    @api.model
    def _texo_anchor(self, task_id=None, project_id=None, partner_id=None, company_id=None):
        """The record a document belongs to: the task, the project, the customer, else the
        company (the organisation itself), when the user may read it."""
        anchor = self.env['memory.note']._anchor_vals(task_id, project_id, partner_id, company_id)
        for field, model in (('task_id', 'project.task'), ('project_id', 'project.project'), ('partner_id', 'res.partner'),
                             ('company_id', 'res.company')):
            if anchor[field]:
                record = self.env[model].browse(anchor[field]).exists()
                if not record or not record.has_access('read'):
                    raise UserError(self.env._("The record does not exist or is not visible to you."))
                return record
        return None

    @api.model
    def _texo_list(self, task_id=None, project_id=None, partner_id=None, company_id=None):
        """The documents of a record; with none, those of the organisation itself (the company)."""
        self.env.user._texo_check_role()
        record = self._texo_anchor(task_id, project_id, partner_id, company_id)
        return self._texo_documents_of(record)._texo_summary() if record else []

    @api.model
    def _texo_search(self, query, related_terms=None, limit=5):
        """Documents ranked by PostgreSQL full-text search over the title, the summary, the
        keywords and the text, on the stored vector: first those that hold every word, then,
        only to fill the limit, those that hold some (fulltext.rank)."""
        limit = max(1, min(int(limit or 5), 20))
        word_list = fulltext.words(query, related_terms)
        best = {}

        def ranker(window, readable):
            # the document whole and its passages: a document ranks with the better of the two, and
            # holds every word when the whole or one passage does; only the documents the user may read
            ranked = fulltext.rank(self.env.cr, 'ir_attachment', 'texo_tsv', word_list, window,
                                   "texo_tsv IS NOT NULL", readable)
            passages = fulltext.rank(self.env.cr, 'memory_document_passage', 'search_tsv', word_list, window * 4,
                                     readable=readable, readable_column='attachment_id')
            if passages:
                self.env['memory.document.passage'].flush_model(['attachment_id'])
                self.env.cr.execute("SELECT id, attachment_id FROM memory_document_passage WHERE id IN %s",
                                    [tuple(passages)])
                for passage_id, document_id in self.env.cr.fetchall():
                    every, score = passages[passage_id]
                    if document_id not in best or (every, score) > passages[best[document_id]]:
                        best[document_id] = passage_id
                for document_id, passage_id in best.items():
                    every, score = passages[passage_id]
                    whole_every, whole_score = ranked.get(document_id, (False, 0.0))
                    ranked[document_id] = (every or whole_every, max(score, whole_score))
            return ranked

        documents, ranked = fulltext.search_ranked(self, ranker, limit, self._texo_search_domain())
        # the passages of each document found that hold the words, the best first
        Passage = self.env['memory.document.passage']
        return Passage._annotate(documents._texo_search_entries(ranked),
                                 {document.id: Passage._by_words(document.id, word_list) for document in documents})

    @api.model
    def _texo_search_domain(self):
        return [('texo_document', '=', True)]

    def _texo_search_entries(self, ranked):
        """The search results of these documents, in this order: the summary, the score and the
        words (fulltext.fields of ranked) and the first words of the summary, flagged as documents.
        The passages that answered are put on them by memory.document.passage._annotate."""
        return [dict(s, document=True, **fulltext.fields(ranked, d.id), snippet=(d.description or '')[:SNIPPET],
                     updated=fields.Date.to_string(d.texo_read_on or d.write_date))
                for d, s in zip(self, self._texo_summary(), strict=True)]

    @api.model
    def _texo_file(self, attachment_id):
        """The file of an attachment the user may read, for the local conversion: name,
        type, size, fingerprint and content in base64, within MAX_ATTACHMENT."""
        self.env.user._texo_check_role()
        attachment = self.browse(int(attachment_id)).exists()
        # has_access on an attachment is the access to the record it is attached to; an
        # attachment without a record is readable by its creator and the administrators only
        if not attachment or not attachment.has_access('read'):
            raise UserError(self.env._("Attachment %s does not exist or is not visible to you.", attachment_id))
        if attachment.type != 'binary' or not attachment.raw:
            raise UserError(self.env._("Attachment %s has no file: it is a link.", attachment_id))
        if attachment.file_size > MAX_ATTACHMENT:
            raise UserError(self.env._("Attachment %s is larger than %s MB.", attachment_id, MAX_ATTACHMENT // (1024 * 1024)))
        raw = _bytes(attachment.raw)
        record = {'model': attachment.res_model, 'id': attachment.res_id} if attachment.res_model and attachment.res_id else None
        return {'id': attachment.id, 'name': attachment.name, 'mimetype': attachment.mimetype, 'size': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest(), 'record': record, 'data': base64.b64encode(raw).decode()}

    # -- writing --------------------------------------------------------------
    @api.model
    def _texo_write(self, name=None, url=None, data=None, summary=None, task_id=None, project_id=None,
                             partner_id=None, company_id=None, read_on=None, fingerprint=None, keep_text=True,
                             text=None, document_id=None, keywords=None):
        """Bring a document into the memory, or read one again.

        With document_id, an attachment of a record the user may read becomes a
        document, or a document gets its new reading (summary, date, fingerprint,
        text); a fingerprint different from the recorded one marks it changed. Without,
        a new attachment on the anchor: a link (url) to an original that lives
        elsewhere, or a file (data, base64). With no anchor the document is the
        organisation's own: it goes on the company. The converted
        text is kept only when keep_text is set."""
        role = self.env.user._texo_check_role()
        if summary and len(summary) > MAX_SUMMARY:
            raise UserError(self.env._("The summary is longer than %s characters.", MAX_SUMMARY))
        check_no_credential(self.env, name, summary, keywords if isinstance(keywords, str) else keywords)
        if text is not None and len(text.encode()) > MAX_TEXT:
            raise UserError(self.env._("The converted text is larger than %s MB.", MAX_TEXT // (1024 * 1024)))
        if url and not url.startswith(('http://', 'https://')):
            raise UserError(self.env._("The link of a document is a web address (http or https)."))
        vals = {'texo_document': True, 'texo_keep_text': bool(keep_text)}
        if isinstance(keywords, (list, tuple)):
            keywords = ", ".join(k.strip() for k in keywords if k and k.strip())
        for key, value in (('name', name), ('description', summary), ('texo_read_on', read_on),
                           ('texo_keywords', keywords)):
            if value is not None:
                vals[key] = value
        if document_id:
            document = self.browse(int(document_id)).exists()
            if not document or not document.has_access('read'):
                raise UserError(self.env._("Attachment %s does not exist or is not visible to you.", document_id))
            if document.texo_text_of_id or not (document.res_model and document.res_id) or document.res_field:
                raise UserError(self.env._("Attachment %s is not a document of a record.", document_id))
            if fingerprint:
                if document.texo_fingerprint and fingerprint != document.texo_fingerprint:
                    vals['texo_changed_on'] = fields.Datetime.now()
                vals['texo_fingerprint'] = fingerprint
            if url:
                if document.type != 'url':
                    raise UserError(self.env._("Attachment %s is a file, not a link.", document_id))
                vals['url'] = url
            # sudo: the memory's own fields of an attachment the user reads; the record it
            # belongs to needs no write right for that
            document.sudo().write(vals)
        else:
            if not name or bool(url) == bool(data):
                raise UserError(self.env._(
                    "A new document has a title and either a link (url) or a file (data); an attachment already "
                    "in Odoo is brought in with document_id."))
            record = self._texo_anchor(task_id, project_id, partner_id, company_id)
            vals.update({'res_model': record._name, 'res_id': record.id, 'texo_created': True,
                         'texo_fingerprint': fingerprint or False})
            if url:
                vals.update({'type': 'url', 'url': url})
            else:
                raw = base64.b64decode(data)
                if len(raw) > MAX_ATTACHMENT:
                    raise UserError(self.env._("The file is larger than %s MB.", MAX_ATTACHMENT // (1024 * 1024)))
                vals.update({'raw': raw, 'texo_fingerprint': fingerprint or hashlib.sha256(raw).hexdigest()})
            # sudo: an attachment on a record needs the right to write it; the memory puts its
            # documents on the records the user reads, as the people see them there
            document = self.sudo().create(vals)
        document = document.sudo(False)
        if text is None and document._texo_is_text():
            text = _bytes(document.raw).decode('utf-8', errors='replace')
        if text is not None:
            document._texo_store_text(text)
        elif not document.texo_keep_text:
            document._texo_store_text('')
        result = document._texo_summary()[0]
        result['role'] = role
        return result

    def _texo_text_name(self):
        """The name of the converted text: the name of the original with .md for its extension."""
        self.ensure_one()
        return f"{EXTENSION.sub('', self.name)}.md"

    def _texo_store_text(self, text):
        """The converted text as one attachment next to the original, replaced at every
        reading; dropped when the document must not keep it."""
        self.ensure_one()
        # sudo: the converted text lives on the record of the original, as the people see it
        existing = self.sudo().texo_text_ids
        if not self.texo_keep_text or not text.strip():
            existing.unlink()
            return
        if self._texo_is_text():
            # the document is its own text, indexed whole
            existing.unlink()
            return
        if existing:
            existing[1:].unlink()
            existing = existing[:1]
            existing.write({'raw': text.encode()})
        else:
            existing = self.sudo().create({
                'name': self._texo_text_name(), 'res_model': self.res_model, 'res_id': self.res_id, 'mimetype': TEXT_MIMETYPE,
                'raw': text.encode(), 'texo_text_of_id': self.id, 'texo_created': True})
        if not self.texo_fingerprint:
            self.sudo().texo_fingerprint = hashlib.sha256(text.encode()).hexdigest()
        self.invalidate_recordset(['texo_text_ids'])

    def _texo_remove(self):
        """A lead takes a document out of the memory: what the memory brought in goes
        (the link, the file it received, the converted text), an attachment the people
        put on the record stays as theirs."""
        self.ensure_one()
        if not (self.env.su or self.env.user._texo_role() in ('lead', 'admin')):
            raise AccessError(self.env._("Only a Texo lead takes a document out of the memory."))
        document = self.sudo()
        result = {'id': document.id, 'title': document.name, 'removed': True}
        document.texo_text_ids.unlink()
        if document.texo_created:
            document.unlink()
        else:
            document.write({'texo_document': False, 'texo_read_on': False, 'texo_keywords': False,
                            'texo_fingerprint': False, 'texo_changed_on': False})
        return result
