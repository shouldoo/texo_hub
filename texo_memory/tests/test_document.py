# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
import hashlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from ..models import ir_attachment
from .common import CLEAN_FINDING, CLEAN_SOLUTION, MemoryCase

TEXT = "# Returns procedure\n\nReturns go through a dedicated picking type, checked by the warehouse manager.\n"
LINK = 'https://drive.example.com/d/abc'


@tagged('post_install', '-at_install')
class TestDocument(MemoryCase):
    """The documents of the memory are attachments of the record they belong to."""

    def write_as(self, user, **kwargs):
        vals = {'name': 'Returns procedure', 'url': LINK, 'summary': 'How returns are handled in the warehouse.',
                'project_id': self.project.id, 'text': TEXT}
        vals.update(kwargs)
        return self.env['ir.attachment'].with_user(user)._texo_write(**vals)

    def attachment_on(self, record, name='spec.pdf', raw=b'%PDF-1.4 fictional spec'):
        return self.env['ir.attachment'].create({'name': name, 'res_model': record._name, 'res_id': record.id, 'raw': raw})

    def test_a_summary_never_holds_a_credential(self):
        with self.assertRaisesRegex(UserError, "credential"):
            self.env['ir.attachment'].with_user(self.lead)._texo_write(
                name='Access', url='https://example.com/access', project_id=self.project.id,
                summary='The cloud folder: token=4f2a9c1b8d7e6f5a9c1b.')

    def test_a_link_with_its_converted_text(self):
        result = self.write_as(self.member)
        document = self.env['ir.attachment'].browse(result['id'])
        self.assertEqual((document.type, document.url, document.res_model, document.res_id, document.description),
                         ('url', LINK, 'project.project', self.project.id, 'How returns are handled in the warehouse.'))
        self.assertTrue(document.texo_document and document.texo_created)
        self.assertTrue(result['has_text'])
        self.assertEqual(len(document.texo_fingerprint), 64)
        text = document.texo_text_ids
        self.assertEqual((text.name, text.mimetype, text.res_model, text.res_id),
                         ('Returns procedure.md', 'text/markdown', 'project.project', self.project.id))
        read = document.with_user(self.member)._texo_read(text=True, max_chars=30)
        self.assertEqual(read['text'], TEXT[:30])
        self.assertEqual(read['text_next_offset'], 30)
        # the people see it with the permissions of the record
        Attachment = self.env['ir.attachment']
        self.assertEqual(Attachment.with_user(self.member).search([('id', '=', document.id)]), document)
        self.assertFalse(Attachment.with_user(self.outsider).search([('id', '=', document.id)]))
        with self.assertRaises(UserError):
            self.write_as(self.member, url='shared folder, Returns.pdf')
        with self.assertRaises(UserError):
            self.write_as(self.member, url=None)

    def test_a_sensitive_document_keeps_no_text(self):
        result = self.write_as(self.lead, name='Contract', keep_text=False)
        self.assertFalse(result['has_text'])
        self.assertFalse(self.env['ir.attachment'].browse(result['id']).texo_text_ids)
        # switching keep_text off later drops the text that was kept
        kept = self.env['ir.attachment'].browse(self.write_as(self.lead)['id'])
        text = kept.texo_text_ids
        self.env['ir.attachment'].with_user(self.lead)._texo_write(document_id=kept.id, keep_text=False)
        self.assertFalse(text.exists())

    def test_an_attachment_on_a_record_becomes_a_document(self):
        attachment = self.attachment_on(self.task)
        Attachment = self.env['ir.attachment']
        with self.assertRaises(UserError):
            Attachment.with_user(self.outsider)._texo_write(document_id=attachment.id, summary='x')
        result = Attachment.with_user(self.member)._texo_write(
            document_id=attachment.id, summary='The spec.', text=TEXT, fingerprint='a' * 64, read_on='2026-10-27')
        self.assertEqual((result['id'], result['record']), (attachment.id, {'model': 'project.task', 'id': self.task.id}))
        self.assertEqual((attachment.description, attachment.texo_created), ('The spec.', False))
        self.assertEqual(attachment.texo_text_ids.name, 'spec.md')
        # a converted text is not a document of its own
        with self.assertRaises(UserError):
            Attachment.with_user(self.member)._texo_write(document_id=attachment.texo_text_ids.id)
        # the file for the local conversion: who reads the record reads it
        file = Attachment.with_user(self.member)._texo_file(attachment.id)
        self.assertEqual(base64.b64decode(file['data']), b'%PDF-1.4 fictional spec')
        self.assertEqual(file['sha256'], hashlib.sha256(b'%PDF-1.4 fictional spec').hexdigest())
        with self.assertRaises(UserError):
            Attachment.with_user(self.outsider)._texo_file(attachment.id)
        link = self.env['ir.attachment'].browse(self.write_as(self.member)['id'])
        with self.assertRaises(UserError):
            Attachment.with_user(self.member)._texo_file(link.id)
        with patch.object(ir_attachment, 'MAX_ATTACHMENT', 10), self.assertRaises(UserError):
            Attachment.with_user(self.member)._texo_file(attachment.id)

    def test_a_file_received_and_a_text_that_needs_no_conversion(self):
        Attachment = self.env['ir.attachment'].with_user(self.member)
        procedure = "# Procedura resi\n\nLa qualità decide se il reso è riparabile.\n"
        result = Attachment._texo_write(name='procedura.md', data=base64.b64encode(procedure.encode()).decode(),
                                                 summary='Come si gestisce un reso.', task_id=self.task.id)
        document = self.env['ir.attachment'].browse(result['id'])
        self.assertEqual((document.res_model, document.res_id, document.texo_created), ('project.task', self.task.id, True))
        self.assertEqual(document.texo_fingerprint, hashlib.sha256(procedure.encode()).hexdigest())
        self.assertFalse(document.texo_text_ids, "a text is its own converted text")
        self.assertTrue(result['has_text'])
        self.assertEqual(document._texo_read(text=True)['text'], procedure)
        # an accented word, lost by the native index, is found
        found = self.env['memory.note'].with_user(self.member)._agent_search('qualità', scope='documents')
        self.assertEqual([f['id'] for f in found], [document.id])
        with self.assertRaises(UserError):
            Attachment._texo_write(name='both', url=LINK, data='eA==', task_id=self.task.id)

    def test_list_pack_search_and_outsider(self):
        self.write_as(self.lead)
        listed = self.env['ir.attachment'].with_user(self.member)._texo_list(project_id=self.project.id)
        self.assertEqual([d['title'] for d in listed], ['Returns procedure'])
        pack = self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id)
        self.assertEqual([d['title'] for d in pack['levels'][1]['documents']], ['Returns procedure'])
        found = self.env['memory.note'].with_user(self.member)._agent_search('returns warehouse', scope='documents')
        self.assertEqual([f['title'] for f in found], ['Returns procedure'])
        self.assertTrue(found[0]['document'])
        with self.assertRaises(UserError):
            self.env['ir.attachment'].with_user(self.outsider)._texo_list(project_id=self.project.id)
        # an attachment of the record that is not in the memory is not listed
        self.attachment_on(self.project)
        self.assertEqual(len(self.env['ir.attachment'].with_user(self.member)._texo_list(project_id=self.project.id)), 1)

    def test_search_finds_a_word_present_only_in_the_text(self):
        with_text = self.write_as(self.lead, text="The damaged goods are scrapped by the quality team.")
        self.write_as(self.lead, name='Minutes', text="Nothing about the quality team here.", keep_text=False)
        Note = self.env['memory.note'].with_user(self.member)
        found = Note._agent_search('scrapped', scope='documents')
        self.assertEqual([f['id'] for f in found], [with_text['id']])
        # the passage that holds the word is the snippet, no more the summary
        self.assertEqual(found[0]['snippet'], 'The damaged goods are scrapped by the quality team.')
        self.assertEqual(found[0]['passage'], {'path': None, 'start': 0, 'snippet': found[0]['snippet']})
        # the sensitive one keeps no text: a word of its text finds nothing, its title still does
        self.assertEqual(Note._agent_search('nothing', scope='documents'), [])
        self.assertEqual([f['title'] for f in Note._agent_search('minutes', scope='documents')], ['Minutes'])
        # the text dropped later leaves the search too
        self.env['ir.attachment'].with_user(self.lead)._texo_write(document_id=with_text['id'], keep_text=False)
        self.assertEqual(Note._agent_search('scrapped', scope='documents'), [])
        self.assertEqual(Note.with_user(self.outsider)._agent_search('returns', scope='documents'), [])

    def test_the_stored_vector_follows_the_document(self):
        Note = self.env['memory.note'].with_user(self.member)
        Attachment = self.env['ir.attachment'].with_user(self.lead)
        document = self.env['ir.attachment'].browse(self.write_as(self.lead, keywords=['resi', 'rientri'])['id'])
        self.assertEqual(document.texo_keywords, 'resi, rientri')
        self.assertEqual([f['id'] for f in Note._agent_search('rientri', scope='documents')], [document.id])
        self.assertEqual([f['id'] for f in Note._agent_search('pick', scope='documents')], [document.id],
                         "the text, by prefix: «picking»")
        Attachment._texo_write(document_id=document.id, keywords='ritorni')
        self.assertEqual(Note._agent_search('rientri', scope='documents'), [], "the vector follows the keywords")
        self.assertEqual([f['id'] for f in Note._agent_search('ritorni', scope='documents')], [document.id])
        Attachment._texo_write(document_id=document.id, keep_text=False)
        self.assertEqual(Note._agent_search('pick', scope='documents'), [], "the text dropped leaves the vector")
        theirs = self.attachment_on(self.task)
        Attachment._texo_write(document_id=theirs.id, summary='Specifica dei rientri.')
        theirs.with_user(self.lead)._texo_remove()
        self.assertEqual(Note._agent_search('specifica', scope='documents'), [], "out of the memory, out of the search")
        self.assertIn(theirs.id, self.env['ir.attachment'].search([('id', '=', theirs.id)]).ids)

    def test_search_over_everything_ranks_by_score_after_the_notes(self):
        self.write_as(self.lead, text="The unit of the purchase line is read by the quality team of the warehouse.")
        lesson = self.env['memory.lesson'].with_user(self.lead).create({
            'name': 'Purchase line unit on 20.0', 'finding': CLEAN_FINDING, 'solution': CLEAN_SOLUTION, 'state': 'active'})
        note = self.note_as(self.lead, name='Unit field', body='The purchase line unit is uom_id on 20.0.', state='active')
        results = self.env['memory.note'].with_user(self.member)._agent_search('purchase line uom_id', scope='all')
        self.assertEqual(results[0]['id'], note['id'], "the rules come first")
        self.assertEqual([(r['id'], r.get('lesson', False)) for r in results[1:3]], [(lesson.id, True)] + [(results[2]['id'], False)],
                         "the lesson that matches the rare words precedes the document that matches the common ones")
        self.assertTrue(results[2]['document'])

    def test_changed_on_with_a_different_fingerprint_or_a_new_content(self):
        Attachment = self.env['ir.attachment'].with_user(self.lead)
        document = self.env['ir.attachment'].browse(self.write_as(self.lead, fingerprint='a' * 64)['id'])
        Attachment._texo_write(document_id=document.id, fingerprint='a' * 64, read_on='2026-10-27')
        self.assertFalse(document.texo_changed_on)
        result = Attachment._texo_write(document_id=document.id, fingerprint='b' * 64)
        self.assertTrue(document.texo_changed_on)
        self.assertEqual(result['changed_on'], document.texo_changed_on.strftime('%Y-%m-%d %H:%M:%S'))
        # a file replaced on the record after its reading
        attachment = self.attachment_on(self.task)
        Attachment._texo_write(document_id=attachment.id, fingerprint='c' * 64)
        self.assertFalse(attachment.texo_changed_on)
        attachment.raw = b'%PDF-1.4 fictional spec, revised'
        self.assertTrue(attachment.texo_changed_on)

    def test_a_lead_takes_a_document_out_of_the_memory(self):
        link = self.env['ir.attachment'].browse(self.write_as(self.member)['id'])
        text = link.texo_text_ids
        with self.assertRaises(AccessError):
            link.with_user(self.member)._texo_remove()
        link.with_user(self.lead)._texo_remove()
        self.assertFalse(link.exists() or text.exists(), "what the memory brought in goes")
        attachment = self.attachment_on(self.task)
        self.env['ir.attachment'].with_user(self.member)._texo_write(document_id=attachment.id, text=TEXT)
        text = attachment.texo_text_ids
        attachment.with_user(self.lead)._texo_remove()
        self.assertTrue(attachment.exists(), "the attachment the people put on the record stays theirs")
        self.assertFalse(attachment.texo_document or text.exists())

    def test_optout_deletes_what_the_memory_brought_in(self):
        link = self.env['ir.attachment'].browse(self.write_as(self.lead)['id'])
        text = link.texo_text_ids
        theirs = self.attachment_on(self.task)
        self.env['ir.attachment'].with_user(self.lead)._texo_write(document_id=theirs.id, text=TEXT)
        admin = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Admin', 'login': 'chm_doc_admin',
            'group_ids': [Command.link(self.env.ref('texo.group_texo_admin').id)]})
        wizard = self.env['memory.optout.wizard'].with_user(admin).create({
            'partner_id': self.customer.id, 'reason': 'request', 'confirm_name': 'Rossi Meccanica'})
        self.assertEqual((wizard.document_count, wizard.attachment_count), (2, 3))
        certificate = wizard.action_optout()
        self.assertEqual(certificate['deleted']['documents'], 2)
        self.assertFalse(link.exists() or text.exists() or theirs.texo_text_ids)
        self.assertTrue(theirs.exists())
        self.assertFalse(theirs.texo_document)


@tagged('post_install', '-at_install')
class TestDocumentRoutes(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.lead = Users.create({
            'name': 'Lead', 'login': 'chm_doc_lead', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id),
                          Command.link(cls.env.ref('project.group_project_user').id)]})
        cls.project = cls.env['project.project'].create({
            'name': 'Service flows', 'user_id': cls.lead.id, 'allowed_internal_user_ids': [Command.link(cls.lead.id)]})
        cls.attachment = cls.env['ir.attachment'].create({
            'name': 'spec.pdf', 'res_model': 'project.project', 'res_id': cls.project.id, 'raw': b'%PDF-1.4 spec'})

    def _post(self, route, payload):
        key = self.env['res.users.apikeys'].with_user(self.lead)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    # The 404 at the end is expected: odoo.http logs every client error as a warning.
    @mute_logger('odoo.http')
    def test_write_list_read_remove(self):
        fetched = self._post('document/attachment', {'attachment_id': self.attachment.id}).json()
        self.assertEqual(base64.b64decode(fetched['data']), b'%PDF-1.4 spec')
        written = self._post('document/write', {'document_id': self.attachment.id, 'summary': 'The spec.', 'text': TEXT,
                                                'fingerprint': fetched['sha256']})
        self.assertEqual(written.status_code, 200)
        self.assertEqual(written.json()['id'], self.attachment.id)
        self.assertEqual([d['id'] for d in self._post('document/list', {'project_id': self.project.id}).json()['documents']],
                         [self.attachment.id])
        read = self._post('document/read', {'document_id': self.attachment.id, 'text': True}).json()
        self.assertEqual(read['text'], TEXT)
        self.assertTrue(self._post('document/remove', {'document_id': self.attachment.id}).json()['removed'])
        self.assertEqual(self._post('document/read', {'document_id': self.attachment.id}).status_code, 404)


@tagged('post_install', '-at_install')
class TestSource(MemoryCase):
    """A rule taken from a document cites it; a changed original marks the rule to re-check."""

    def setUp(self):
        super().setUp()
        self.document = self.env['ir.attachment'].browse(self.env['ir.attachment'].with_user(self.lead)._texo_write(
            name='Returns spec', url=LINK, summary='The returns flow.', project_id=self.project.id,
            fingerprint='a' * 64, text=TEXT)['id'])

    def reread(self, fingerprint):
        self.env['ir.attachment'].with_user(self.lead)._texo_write(document_id=self.document.id, fingerprint=fingerprint)

    def pack_warnings(self, user=None):
        # the warnings on rules: the project has no update, its now_missing is not the subject here
        warnings = self.env['memory.note'].with_user(user or self.member)._agent_context(task_id=self.task.id)['warnings']
        return [w for w in warnings if 'project_id' not in w]

    def test_note_cites_the_source_and_follows_its_changes(self):
        note = self.env['memory.note'].browse(self.note_as(self.lead, state='active', document_id=self.document.id)['id'])
        self.assertEqual((note.document_id, bool(note.source_checked)), (self.document, True))
        self.assertEqual(note._agent_summary()[0]['document_id'], self.document.id)
        self.assertNotIn('stale', note._agent_summary()[0])
        # the same fingerprint is no change
        self.reread('a' * 64)
        self.assertEqual(self.pack_warnings(), [])
        # a different one marks the note in the pack and in the review queue
        note.source_checked = note.source_checked - timedelta(minutes=1)
        self.reread('b' * 64)
        self.assertEqual(note._agent_summary()[0]['stale'], 'source_changed')
        self.assertIn({'id': note.id, 'concept': f"rules/{note.id}", 'title': note.name, 'stale': 'source_changed'},
                      self.pack_warnings())
        review = self.env['memory.note'].with_user(self.lead)._agent_review()
        self.assertEqual([(n['id'], n['stale']) for n in review['stale']], [(note.id, 'source_changed')])
        # the lead re-checks it: the warning goes
        note.with_user(self.lead)._agent_confirm()
        self.assertEqual(self.pack_warnings(), [])
        self.assertEqual(self.env['memory.note'].with_user(self.lead)._agent_review()['stale'], [])
        # a draft of a member activated by the lead counts as checked too
        draft = self.env['memory.note'].browse(self.note_as(self.member, name='Draft rule', document_id=self.document.id)['id'])
        draft.source_checked = draft.source_checked - timedelta(minutes=1)
        self.reread('c' * 64)
        self.assertEqual(draft._agent_summary()[0]['stale'], 'source_changed')
        draft.with_user(self.lead)._agent_set_state('active')
        self.assertNotIn('stale', draft._agent_summary()[0])
        # the same pack twice
        pack = self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id)
        self.assertEqual(pack, self.env['memory.note'].with_user(self.member)._agent_context(task_id=self.task.id))

    def test_source_must_be_a_readable_document(self):
        with self.assertRaises(UserError):
            self.note_as(self.outsider, document_id=self.document.id, task_id=None, partner_id=self.customer.id)
        with self.assertRaises(UserError):
            self.note_as(self.member, document_id=999999)
        plain = self.env['ir.attachment'].create({'name': 'x.pdf', 'res_model': 'project.project', 'res_id': self.project.id,
                                                  'raw': b'x'})
        with self.assertRaises(UserError):
            self.note_as(self.member, document_id=plain.id)
        # the source gone: the note stays, without it
        note = self.env['memory.note'].browse(self.note_as(self.lead, state='active', document_id=self.document.id)['id'])
        self.document.unlink()
        self.assertFalse(note.document_id)
        self.assertNotIn('stale', note._agent_summary()[0])
