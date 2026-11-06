# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.texo import okf

STATES = [('draft', "Draft"), ('active', "Active"), ('superseded', "Superseded"), ('archived', "Archived")]


class MemoryAnchorMixin(models.AbstractModel):
    """Where a record of the memory stands: one anchor among the company, a customer, a
    project and a task (the hierarchy of the OKF bundle: organisation, customers,
    projects), the customer derived from it (for the opt-out), the state, and the role
    guards: a member writes drafts and edits only their own, a lead decides.

    A record with no anchor of its own belongs to the organisation: it is anchored to the
    company. The organisation is never a customer: a record on the company, or on the
    partner of one of our companies, has no customer and stays out of the opt-out."""
    _name = 'memory.anchor.mixin'
    _description = "Memory Anchor Mixin"

    # No tracking here: the mixin has no chatter; the models that inherit it add it.
    state = fields.Selection(STATES, required=True, default='draft', index=True)
    partner_id = fields.Many2one('res.partner', string="Customer", ondelete='cascade', index=True,
                                 domain=[('parent_id', '=', False)])
    project_id = fields.Many2one('project.project', string="Project", ondelete='cascade', index=True)
    task_id = fields.Many2one('project.task', string="Task", ondelete='cascade', index=True)
    company_id = fields.Many2one('res.company', string="Organisation", ondelete='cascade', index=True,
                                 help="The organisation itself: what belongs to it and to no customer.")
    customer_id = fields.Many2one('res.partner', string="Customer Company", compute='_compute_customer_id',
                                  store=True, index=True,
                                  help="The customer the record belongs to, whatever its anchor; used by the opt-out.")
    superseded_on = fields.Date(
        readonly=True, copy=False,
        help="The day the record stopped holding: when it was superseded or archived. With valid_from and expires, "
             "what the memory knew on a given day (as_of of the search).")
    # Provenance and trust, named as Open Knowledge Format renders them (texo/okf.py):
    # who wrote the content (generated), the document it was taken from (sources).
    origin = fields.Selection([('agent', "Agent"), ('person', "Person")], required=True, default='person')
    generated_by = fields.Char(
        string="Written By (Agent)",
        help="The agent that wrote the content for the person, as <producer>/<version> (e.g. claude-code/2.1); "
             "empty, the tool of the hub it called.")
    source_ref = fields.Char(help="Where the record comes from: a task, a commit, a session.")
    document_id = fields.Many2one('ir.attachment', string="Source Document", ondelete='set null', index=True,
                                  domain=[('texo_document', '=', True)],
                                  help="The document of the memory the record was taken from.")
    source_checked = fields.Datetime(help="When the record was last written or confirmed against its source document: "
                                          "an original changed after it marks the record to re-check.")

    @api.depends('partner_id', 'project_id', 'task_id', 'task_id.project_id', 'project_id.partner_id')
    def _compute_customer_id(self):
        Project = self.env['project.project']
        for record in self:
            # sudo: the customer of a task the user can read, even when the project is restricted
            anchor = record.task_id.sudo() or record.project_id.sudo()
            partner = record.partner_id or (anchor.partner_id if anchor else self.env['res.partner'])
            if not partner and record.task_id:
                partner = record.task_id.sudo().project_id.partner_id
            # the organisation is not a customer: nothing of its own goes with an opt-out
            if partner and Project._texo_is_own_partner(partner):
                partner = self.env['res.partner']
            record.customer_id = partner.commercial_partner_id if partner else False

    @api.constrains('partner_id', 'project_id', 'task_id', 'company_id')
    def _check_anchor(self):
        for record in self:
            if len(list(filter(None, (record.partner_id, record.project_id, record.task_id, record.company_id)))) != 1:
                raise UserError(self.env._("A record belongs to exactly one organisation, customer, project or task."))

    def _anchor(self):
        self.ensure_one()
        return self.task_id or self.project_id or self.partner_id or self.company_id

    @api.model
    def _company(self, company_id=None):
        """The company that anchors what has no anchor: the current one, or company_id when
        the user works in it."""
        if not company_id:
            return self.env.company
        company = self.env['res.company'].browse(int(company_id)).exists()
        if not company or company not in self.env.user.company_ids:
            raise UserError(self.env._("Company %s does not exist or is not yours.", company_id))
        return company

    @api.model
    def _anchor_vals(self, task_id=None, project_id=None, partner_id=None, company_id=None):
        """The anchor as field values; none given means the organisation, the company."""
        anchors = [a for a in (task_id, project_id, partner_id) if a]
        if len(anchors) > 1:
            raise UserError(self.env._("A record belongs to exactly one organisation, customer, project or task."))
        return {'task_id': int(task_id) if task_id else False, 'project_id': int(project_id) if project_id else False,
                'partner_id': int(partner_id) if partner_id else False,
                'company_id': False if anchors else self._company(company_id).id}

    # -- role guards ----------------------------------------------------------
    def _is_lead(self):
        return self.env.su or self.env.user._texo_role() in ('lead', 'admin')

    def _check_lead(self):
        if not self._is_lead():
            raise AccessError(self.env._("Only a Texo lead can activate, supersede or archive this record."))

    @api.model
    def _reviewed_vals(self, vals):
        """Whether a record written with these values waits for a lead's review."""
        return True

    def _is_reviewed(self):
        """Whether the record is a member's draft until a lead decides (a rule), or is written
        as it is by whoever may write on its anchor (a record that only describes)."""
        self.ensure_one()
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if self._reviewed_vals(vals) and vals.get('state', 'draft') != 'draft' and not self._is_lead():
                raise AccessError(self.env._("A member writes drafts; a lead reviews them."))
            if not any(vals.get(key) for key in ('task_id', 'project_id', 'partner_id', 'company_id')):
                # no anchor: the record belongs to the organisation
                vals.update(self._anchor_vals())
        return super().create(vals_list)

    def write(self, vals):
        reviewed = self.filtered(lambda r: r._is_reviewed())
        if reviewed and not self._is_lead():
            if 'state' in vals:
                reviewed._check_lead()
            if (set(vals) - {'message_main_attachment_id'}
                    and any(r.state != 'draft' or r.create_uid != self.env.user for r in reviewed)):
                raise AccessError(self.env._("A member edits only their own drafts."))
        return super().write(vals)

    # -- provenance -------------------------------------------------------------
    @api.model
    def _source_vals(self, document_id=None, source_ref=None, generated_by=None):
        """The provenance of a record an agent writes: the document it cites, checked now,
        where it comes from, and the agent that wrote it."""
        vals = {'origin': 'agent', 'generated_by': okf.actor(generated_by) or False}
        if source_ref:
            vals['source_ref'] = source_ref
        if document_id:
            document = self.env['ir.attachment']._texo_document(document_id)
            vals.update({'document_id': document.id, 'source_checked': fields.Datetime.now()})
        return vals

    def _source_changed(self):
        """The original of the cited document changed after the record was written or last checked."""
        self.ensure_one()
        # sudo: the flag of a document the reader may not open says nothing of its content
        changed_on = self.document_id.sudo().texo_changed_on
        return bool(changed_on and (not self.source_checked or changed_on > self.source_checked))

    # -- Open Knowledge Format ------------------------------------------------
    def _okf_sources(self):
        """sources (OKF § 5.1): the document of the memory the record cites, with when it last
        changed, and the reference it comes from."""
        self.ensure_one()
        sources = []
        if self.document_id:
            # sudo: the name and the dates of a cited document, which the summary of the rule shows
            document = self.document_id.sudo()
            sources.append({'id': f"document-{document.id}", 'resource': okf.link(document), 'title': document.name,
                            'last_modified': okf.timestamp(document.texo_changed_on or document.write_date)})
        if self.source_ref:
            sources.append({'id': 'ref', 'resource': self.source_ref})
        return sources

    def _okf_anchor(self):
        """The record the concept is about, as a link; the organisation as itself."""
        anchor = self._anchor()
        return 'organisation' if anchor._name == 'res.company' else okf.link(anchor)

    def _okf_meta(self, okf_type):
        """The frontmatter every record of the memory shares: type, title, status, who wrote
        it and when, what it was taken from, the record it is about."""
        self.ensure_one()
        return {
            'type': okf_type, 'title': self.name, 'status': okf.status(self.state),
            'resource': self._okf_resource(),
            'generated': okf.generated(self.origin, self.create_uid, self.generated_by, self.write_date),
            'sources': self._okf_sources(),
            'anchor': self._okf_anchor(),
        }

    def _okf_resource(self):
        """The record in Odoo, for a person who opens it."""
        base = self.get_base_url()
        return f"{base}/mail/view?model={self._name}&res_id={self.id}"

    def _state_summary(self):
        self.ensure_one()
        return {'id': self.id, 'title': self.name, 'state': self.state}

    def _agent_set_state(self, state, superseded_by_id=None):
        """A lead activates, supersedes or archives; superseding links the two records."""
        self.ensure_one()
        self._check_lead()
        if state not in dict(STATES) or state == 'draft':
            raise UserError(self.env._("A record becomes active, superseded or archived."))
        vals = {'state': state}
        if state == 'active':
            vals.update({'verified': fields.Date.context_today(self), 'verified_by_id': self.env.uid,
                         'superseded_on': False})
        else:
            vals['superseded_on'] = fields.Date.context_today(self)
        if state == 'superseded':
            later = self.browse(int(superseded_by_id or 0)).exists()
            if not later or not later.has_access('read'):
                raise UserError(self.env._("A superseded record needs the record that replaces it."))
            vals['superseded_by_id'] = later.id
            later.write({'supersedes_id': self.id})
        self.write(vals)
        if 'activity_ids' in self._fields:
            self.activity_feedback(['mail.mail_activity_data_todo'])
        return self._agent_summary()[0] if hasattr(self, '_agent_summary') else self._state_summary()
