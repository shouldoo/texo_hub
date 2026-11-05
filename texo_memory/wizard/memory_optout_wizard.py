# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class MemoryOptoutWizard(models.TransientModel):
    """A customer opts out: their project memory goes, the lessons stay.

    The wizard shows what will be deleted, deletes it after confirmation, adds the
    customer's names to the opt-out list so no future finding can name them,
    archives the partner and posts a certificate (counts and a hash) on the task
    that tracks the request. Timesheets, invoices and the tasks themselves are
    company records and stay out of its scope.
    """
    _name = 'memory.optout.wizard'
    _description = "Memory Opt-out Wizard"

    partner_id = fields.Many2one('res.partner', string="Customer", required=True, domain=[('parent_id', '=', False)])
    task_id = fields.Many2one('project.task', string="Request Task",
                              help="The internal task that tracks the opt-out request; the certificate is posted there.")
    reason = fields.Char(required=True, help="A reference to the request, no customer data.")
    confirm_name = fields.Char(help="Type the customer's name to confirm the deletion.")
    note_count = fields.Integer(compute='_compute_counts')
    fact_count = fields.Integer(compute='_compute_counts')
    document_count = fields.Integer(compute='_compute_counts')
    attachment_count = fields.Integer(compute='_compute_counts')
    project_count = fields.Integer(compute='_compute_counts')
    preview = fields.Text(compute='_compute_counts')

    # sudo: the opt-out covers every note and document of the customer, on records the
    # administrator may not read; the action is theirs and confirmed by name.
    def _notes(self):
        self.ensure_one()
        return self.env['memory.note'].sudo().with_context(active_test=False).search([('customer_id', '=', self.partner_id.id)])

    def _documents(self):
        """The documents of the memory on the customer, its projects and their tasks, with
        their converted texts."""
        self.ensure_one()
        partners = self.env['res.partner'].sudo().with_context(active_test=False).search([('id', 'child_of', self.partner_id.id)])
        projects = self.env['project.project'].sudo().with_context(active_test=False).search([('partner_id', 'in', partners.ids)])
        tasks = self.env['project.task'].sudo().with_context(active_test=False).search(
            ['|', ('project_id', 'in', projects.ids), ('partner_id', 'in', partners.ids)])
        return self.env['ir.attachment'].sudo().search([
            '|', ('texo_document', '=', True), ('texo_text_of_id', '!=', False),
            '|', '|', '&', ('res_model', '=', 'res.partner'), ('res_id', 'in', partners.ids),
            '&', ('res_model', '=', 'project.project'), ('res_id', 'in', projects.ids),
            '&', ('res_model', '=', 'project.task'), ('res_id', 'in', tasks.ids)])

    def _attachments(self, notes, documents):
        """What goes: the files of the notes and what the memory brought in among the
        documents (the links, the files it received, the converted texts). An attachment
        the people put on a record stays there, out of the memory."""
        return self.env['ir.attachment'].sudo().search(
            [('res_model', '=', 'memory.note'), ('res_id', 'in', notes.ids)]) | documents.filtered('texo_created')

    @api.depends('partner_id')
    def _compute_counts(self):
        for wizard in self:
            notes = wizard._notes() if wizard.partner_id else self.env['memory.note']
            documents = wizard._documents() if wizard.partner_id else self.env['ir.attachment']
            attachments = wizard._attachments(notes, documents)
            wizard.document_count = len(documents.filtered('texo_document'))
            projects = self.env['project.project'].with_context(active_test=False).search(
                [('partner_id', 'child_of', wizard.partner_id.id)]) if wizard.partner_id else self.env['project.project']
            wizard.note_count = len(notes)
            wizard.fact_count = len(notes.filtered(lambda n: n.kind == 'fact'))
            wizard.attachment_count = len(attachments)
            wizard.project_count = len(projects)
            kinds = {}
            for note in notes:
                kinds[note.kind] = kinds.get(note.kind, 0) + 1
            wizard.preview = "\n".join(f"{kind}: {count}" for kind, count in sorted(kinds.items())) or "-"

    def action_optout(self):
        self.ensure_one()
        if self.env.user._texo_role() != 'admin':
            raise AccessError(self.env._("Only a Texo administrator runs an opt-out."))
        if self.env['project.project']._texo_is_own_partner(self.partner_id):
            raise UserError(self.env._("%s is one of our companies, not a customer: nothing to opt out.", self.partner_id.name))
        if (self.confirm_name or '').strip().lower() != (self.partner_id.name or '').strip().lower():
            raise UserError(self.env._("Type the customer's name exactly to confirm."))
        notes = self._notes()
        facts = notes.filtered(lambda n: n.kind == 'fact')
        documents = self._documents()
        attachments = self._attachments(notes, documents)
        counts = {'notes': len(notes), 'facts': len(facts), 'documents': len(documents.filtered('texo_document')),
                  'attachments': len(attachments), 'projects': self.project_count}
        names = {n.strip() for n in (self.partner_id.name, self.partner_id.ref) if n and n.strip()}
        Optout = self.env['memory.optout.name']
        for name in names:
            if not Optout.search_count([('name', '=ilike', name)]):
                Optout.create({'name': name, 'reason': self.reason})
        attachments.unlink()
        # the attachments the people put on the records stay, out of the memory
        (documents - attachments).exists().write({
            'texo_document': False, 'texo_read_on': False, 'texo_fingerprint': False,
            'texo_keywords': False,
            'texo_changed_on': False})
        notes.unlink()
        # sudo: the opt-out is a confirmed administrator action and must not stop
        # halfway because the hub administrator has no rights on contacts.
        self.partner_id.sudo().active = False
        certificate = {
            'customer_id': self.partner_id.id, 'reason': self.reason, 'by': self.env.user.login,
            'date': fields.Datetime.to_string(fields.Datetime.now()), 'deleted': counts, 'lessons_kept': True,
        }
        digest = hashlib.sha256(json.dumps(certificate, sort_keys=True).encode()).hexdigest()
        certificate['sha256'] = digest
        if self.task_id:
            body = self.env._("Memory opt-out done. Deleted: %(notes)s notes, %(facts)s facts, %(documents)s documents, %(attachments)s files. Lessons kept. sha256 %(digest)s",
                              notes=counts['notes'], facts=counts['facts'], documents=counts['documents'], attachments=counts['attachments'], digest=digest)
            self.task_id.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
        return certificate
