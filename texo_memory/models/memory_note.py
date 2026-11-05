# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import hashlib
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.texo import okf

from . import fulltext

# What the memory knows of the organisation, a customer, a project or a task, one record at a
# time: its kind is the type of its OKF concept. Only what Odoo does not hold: what was decided
# and what happened are the updates of the project and the chatter of the task.
KINDS = [('rule', "Rule"), ('fact', "Fact"), ('procedure', "Procedure")]
OKF_TYPES = {'rule': 'Rule', 'fact': 'Fact', 'procedure': 'Playbook'}
OKF_KINDS = {'rule': 'rules', 'fact': 'facts', 'procedure': 'procedures'}
SEVERITIES = [('never', "Never"), ('must', "Must"), ('prefer', "Prefer")]
STALE_DAYS = 180
REVIEW_LIMIT = 50
MAX_BODY = 20000
MAX_READ = 6000
PACK_BODY = 1500
PACK_RULES = 20
PACK_NOTES = 20
PACK_DOCUMENTS = 20
MAX_CHAIN = 6
SNIPPET = 160
# The updates of the project in the log of an OKF pack: the recent ones; the whole history with project/log.
PACK_LOG = 3
# The title weighs most, then the keywords, then the text; plain words, Italian and English
# stems side by side.
SEARCH_TSV = (
    "setweight(to_tsvector('simple', coalesce(name, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(keywords, '')), 'B') || "
    "setweight(to_tsvector('italian', coalesce(keywords, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(keywords, '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(body, '')), 'C') || "
    "setweight(to_tsvector('italian', coalesce(body, '')), 'C') || "
    "setweight(to_tsvector('english', coalesce(body, '')), 'C')"
)
LEVEL_FIELDS = {'project.task': 'task_id', 'project.project': 'project_id', 'res.partner': 'partner_id',
                'res.company': 'company_id'}
LEVEL_LABELS = {'project.task': "Task", 'project.project': "Project", 'res.partner': "Customer",
                'res.company': "Organisation"}


class MemoryNote(models.Model):
    """What the memory knows of the organisation (the company), a customer, a project or a
    task, one record at a time, of three kinds:

    - a rule: what an agent must always or never do. Only an active rule binds; a member
      proposes a draft, a lead decides. Its severity says how it binds (a prohibition, an
      obligation, a preference) and its activities which work it concerns. Never on a task.
    - a fact: what the record is (who decides, how a process runs, what was agreed).
    - a procedure: how an operation is done, step by step. It describes, it does not bind:
      what in it binds is a rule.

    A fact and a procedure are written as they are by whoever may write on the anchor,
    after the person's yes; two sessions never overwrite each other (an append locks the
    row, a replacement needs the version that was read). Every record carries its section,
    when it was last verified and by whom, its expiry and the document it was taken from.
    """
    _name = 'memory.note'
    _description = "Memory Note"
    _inherit = ['memory.anchor.mixin', 'memory.seed.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'write_date desc, id desc'

    name = fields.Char(string="Title", required=True, tracking=True)
    body = fields.Text(required=True)
    kind = fields.Selection(KINDS, required=True, default='rule', tracking=True, index=True)
    state = fields.Selection(tracking=True)
    section_id = fields.Many2one('memory.section', string="Section", ondelete='restrict', index=True,
                                 help="The part of what the memory knows of the record: profile, operations, compliance...")
    severity = fields.Selection(
        SEVERITIES, default='must', tracking=True, index=True,
        help="Of a rule. Never: a prohibition. Must: an obligation. Prefer: what the agent does unless the person "
             "decides otherwise.")
    # Not activity_ids: that is the to-do list of mail.activity.mixin.
    rule_activity_ids = fields.Many2many(
        'memory.note.activity', string="Applies to",
        help="The work the record concerns; none means every activity.")
    keywords = fields.Char(help="Synonyms, translations and other names of what the record is about, comma "
                                "separated: the search finds it by these words too.")
    applies_to = fields.Char(help="Where it holds: a site, a version, a period.")
    verified = fields.Date(tracking=True,
                           help="Last day the content was checked (for a rule, confirmed by a lead); after %s days "
                                "it is to re-check." % STALE_DAYS)
    verified_by_id = fields.Many2one('res.users', string="Verified By", ondelete='set null',
                                     help="Who last checked the content: the verified of its OKF rendering.")
    expires = fields.Date(help="After this day the record no longer holds on its own.")
    supersedes_id = fields.Many2one('memory.note', string="Supersedes", ondelete='set null')
    superseded_by_id = fields.Many2one('memory.note', string="Superseded By", ondelete='set null')
    # the review of the person in the lists: what _is_stale says, as a filter
    stale = fields.Boolean(string="To Check", compute='_compute_stale', search='_search_stale',
                           help="Active, and expired, not verified for %s days, or its source document changed."
                                % STALE_DAYS)

    def init(self):
        self.env.cr.execute(
            "ALTER TABLE memory_note ADD COLUMN IF NOT EXISTS search_tsv tsvector "
            f"GENERATED ALWAYS AS ({SEARCH_TSV}) STORED")
        self.env.cr.execute("CREATE INDEX IF NOT EXISTS memory_note_search_tsv_idx ON memory_note USING gin (search_tsv)")

    @api.constrains('task_id', 'kind')
    def _check_rule_anchor(self):
        if self.filtered(lambda n: n.task_id and n.kind == 'rule'):
            raise UserError(self.env._(
                "A rule binds the organisation, a customer or a project, not a task: what concerns one task "
                "goes in a note on the task."))

    # -- the kind decides the review ------------------------------------------
    @api.model
    def _reviewed_vals(self, vals):
        return vals.get('kind', 'rule') == 'rule'

    def _is_reviewed(self):
        self.ensure_one()
        return self.kind == 'rule'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('kind', 'rule') == 'rule':
                vals.setdefault('severity', 'must')
            else:
                # a record that only describes is born active and verified by who writes it
                vals.setdefault('state', 'active')
                vals.setdefault('severity', False)
                vals.setdefault('verified', fields.Date.context_today(self))
                vals.setdefault('verified_by_id', self.env.uid)
        return super().create(vals_list)

    # -- chain ----------------------------------------------------------------
    def _chain(self, record):
        """Levels from the record up to its customer, most specific first. The organisation
        is a level of its own, the company: never a customer of the chain."""
        levels, seen = [], set()
        current = record
        while current and len(levels) < MAX_CHAIN and (current._name, current.id) not in seen:
            seen.add((current._name, current.id))
            readable = current.has_access('read')
            level = {'model': current._name, 'id': current.id, 'readable': readable,
                     'name': current.display_name if readable else None}
            levels.append(level)
            # sudo: walk the links of a record the user may not read, to report the gap
            linked = current.sudo()
            if current._name == 'project.task':
                current = linked.parent_id or linked.project_id
            elif current._name == 'project.project':
                partner = linked.partner_id.commercial_partner_id
                current = partner if partner and not current._texo_is_own_partner(partner) else None
            else:
                current = None
        return levels

    def _anchor_domain(self, level):
        return [(LEVEL_FIELDS[level['model']], '=', level['id'])]

    @api.model
    def _activity_domain(self, activities):
        """The records of the activities of a session and those that concern every
        activity; no activity given, every record."""
        if not activities:
            return []
        return ['|', ('rule_activity_ids', '=', False), ('rule_activity_ids', 'in', activities.ids)]

    @api.model
    def _live_domain(self):
        """What holds today: an active record not expired."""
        today = fields.Date.context_today(self)
        return [('state', '=', 'active'), '|', ('expires', '=', False), ('expires', '>=', today)]

    # -- reading --------------------------------------------------------------
    def _okf_kind(self):
        """The kind of the record in its concept id: rules/12, facts/3, procedures/7."""
        self.ensure_one()
        return OKF_KINDS[self.kind]

    def _version(self):
        """The version of the text a replacement must name: a fingerprint of the text, so any
        change since the reading, even in the same second, refuses the replacement."""
        self.ensure_one()
        return hashlib.sha256((self.body or '').encode()).hexdigest()[:16]

    def _is_stale(self, today):
        """Why an active record is to re-check: expired, its source document changed, or not
        verified for STALE_DAYS."""
        self.ensure_one()
        if self.expires and self.expires < today:
            return 'expired'
        if self._source_changed():
            return 'source_changed'
        if not self.verified or self.verified < today - timedelta(days=STALE_DAYS):
            return 'unverified'
        return None

    @api.depends('state', 'expires', 'verified', 'source_checked', 'document_id.texo_changed_on')
    def _compute_stale(self):
        today = fields.Date.context_today(self)
        for note in self:
            note.stale = note.state == 'active' and bool(note._is_stale(today))

    def _search_stale(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        today = fields.Date.context_today(self)
        # the dates in the domain; the changed source documents, few, by their flag
        changed = self.search([('state', '=', 'active'), ('document_id.texo_changed_on', '!=', False)])
        domain = ['|', ('id', 'in', changed.filtered(lambda n: n._source_changed()).ids),
                  '&', ('state', '=', 'active'),
                  '|', '|', ('expires', '<', today), ('verified', '=', False),
                  ('verified', '<', today - timedelta(days=STALE_DAYS))]
        return domain if operator == 'in' else ['!'] + domain

    def _agent_summary(self, today=None):
        today = today or fields.Date.context_today(self)
        result = []
        for note in self:
            entry = {'id': note.id, 'concept': okf.concept_id(note), 'title': note.name, 'kind': note.kind,
                     'state': note.state, 'updated': fields.Date.to_string(note.write_date)}
            if note.kind == 'rule':
                entry['severity'] = note.severity
            if note.section_id:
                entry['section'] = note.section_id.code
            if note.rule_activity_ids:
                entry['activities'] = note.rule_activity_ids.mapped('code')
            for key in ('verified', 'expires'):
                if note[key]:
                    entry[key] = fields.Date.to_string(note[key])
            if note.applies_to:
                entry['applies_to'] = note.applies_to
            if note.document_id:
                entry['document_id'] = note.document_id.id
            stale = note._is_stale(today)
            if stale:
                entry['stale'] = stale
            if note.state == 'draft':
                entry['author'] = note.create_uid.name
            result.append(entry)
        return result

    def _agent_read(self, max_chars=MAX_READ):
        self.ensure_one()
        result = self._agent_summary()[0]
        body = self.body or ''
        result.update({'body': body[:max_chars], 'author': self.create_uid.name, 'keywords': self.keywords or None,
                       'anchor': {'model': self._anchor()._name, 'id': self._anchor().id}})
        if len(body) > max_chars:
            # a cut text carries no version: a replacement is never built on a part
            result.update({'truncated': True, 'total_chars': len(body)})
        else:
            result['version'] = self._version()
        for key in ('supersedes_id', 'superseded_by_id'):
            if self[key]:
                result[key] = self[key].id
        return result

    def _okf_concept(self, today=None):
        """The record as an OKF concept: its kind as the type, verified by who last checked
        it, stale after its expiry, 180 days without a check or a change of its source
        document; a rule with its severity, its activities as tags."""
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        meta = self._okf_meta(OKF_TYPES[self.kind])
        changed_on = self.document_id.sudo().texo_changed_on if self._source_changed() else None
        meta.update({
            'description': okf.description(self.body), 'tags': self.rule_activity_ids.mapped('code'),
            'verified': okf.verified(self.verified_by_id, self.verified),
            'stale_after': okf.stale_after(
                okf.day_after(self.expires), changed_on,
                self.verified + timedelta(days=STALE_DAYS + 1) if self.verified
                else (self.create_date if self.state == 'active' else None)),
            'stale': self._is_stale(today),
            'severity': self.severity if self.kind == 'rule' else None,
            'section': self.section_id.code or None,
            'keywords': self.keywords or None, 'applies_to': self.applies_to or None,
            'version': self._version(),
            'supersedes': okf.link(self.supersedes_id) if self.supersedes_id else None,
            'superseded_by': okf.link(self.superseded_by_id) if self.superseded_by_id else None,
        })
        return okf.concept(meta, self.body)

    def _outline(self, today):
        """A fact or a procedure in the pack: its title, its section and its dates; the text
        with memory/read."""
        result = []
        for note, summary in zip(self, self._agent_summary(today), strict=True):
            result.append({key: summary[key] for key in ('id', 'concept', 'title', 'section', 'verified', 'expires',
                                                          'applies_to', 'document_id', 'stale') if key in summary})
        return result

    @api.model
    def _agent_context_record(self, task_id=None, project_id=None, company_id=None):
        """The record a context pack is about: the task, the project, else the company (the
        memory of the organisation itself)."""
        if task_id:
            record = self.env['project.task'].browse(int(task_id)).exists()
        elif project_id:
            record = self.env['project.project'].browse(int(project_id)).exists()
        else:
            record = self._company(company_id)
        if not record or not record.has_access('read'):
            raise UserError(self.env._("The record does not exist or is not visible to you."))
        return record

    @api.model
    def _agent_context(self, task_id=None, project_id=None, messages=5, company_id=None, activity=None):
        """The context pack of a task or project, or of the organisation itself when
        neither is given: deterministic, budgeted, same for every assistant. With the
        activity of the session, the records of that activity and those of every
        activity."""
        record = self._agent_context_record(task_id, project_id, company_id)
        activities = self.env['memory.note.activity']._from_codes(activity)
        today = fields.Date.context_today(self)
        role = self.env.user._texo_check_role()
        pack = {'role': role, 'levels': [], 'pending': [], 'warnings': [], 'lessons': []}
        if activities:
            pack['activities'] = activities.mapped('code')
        if record._name == 'project.task':
            pack['task'] = record._texo_context(messages)
        for level in self._chain(record):
            entry = {'model': level['model'], 'id': level['id'], 'name': level['name']}
            if not level['readable']:
                entry['skipped'] = 'not readable'
                pack['levels'].append(entry)
                continue
            # Creation order, not last edit: the pack reads the same way in every session.
            notes = self.search(self._anchor_domain(level) + self._activity_domain(activities)
                                + [('state', 'in', ('draft', 'active'))], order='id')
            rules = notes.filtered(lambda n: n.kind == 'rule' and n.state == 'active')[:PACK_RULES]
            entry['rules'] = [n._pack_rule(summary) for n, summary in zip(rules, rules._agent_summary(today), strict=True)]
            live = notes.filtered(lambda n: n.kind != 'rule' and n.state == 'active'
                                  and not (n.expires and n.expires < today))
            for kind, key in (('fact', 'facts'), ('procedure', 'procedures')):
                outline = live.filtered(lambda n, kind=kind: n.kind == kind)[:PACK_NOTES]._outline(today)
                if outline:
                    entry[key] = outline
            documents = self.env['ir.attachment']._texo_documents_of(
                self.env[level['model']].browse(level['id']), limit=PACK_DOCUMENTS)
            if documents:
                entry['documents'] = documents._texo_summary()
            pack['levels'].append(entry)
            drafts = notes.filtered(lambda n: n.state == 'draft')
            pack['pending'] += drafts._agent_summary(today)
            for note in notes.filtered(lambda n: n.kind == 'rule' and n.state == 'active'):
                stale = note._is_stale(today)
                if stale:
                    pack['warnings'].append({'id': note.id, 'concept': okf.concept_id(note), 'title': note.name,
                                             'stale': stale})
        if role in ('lead', 'admin'):
            # The lead's review queue, notes and the lessons born with them: the pack is the
            # first thing read in a session.
            pack['pending'].sort(key=lambda d: d['id'])
            drafts = self.env['memory.lesson'].search([('state', '=', 'draft')], order='id desc', limit=PACK_RULES)
            pack['pending_lessons'] = [lesson._agent_summary() for lesson in drafts]
        project = self._agent_context_project(record, pack['levels'])
        if project:
            pack['project'] = project._texo_context()
            pack['warnings'] += [{'project_id': project.id, 'warning': warning}
                                 for warning in pack['project'].pop('warnings')]
        if record._name == 'res.company':
            pack['sections'] = self.env['memory.section'].search([])._agent_summary()
        pack['lessons'] = self.env['memory.lesson']._agent_pack(self._pack_tags(record), activities)
        return pack

    def _okf_line(self, today):
        """A record in the index of an OKF pack: its kind, a rule's severity and activities,
        its first sentence, its expiry and why it is stale."""
        self.ensure_one()
        head = OKF_TYPES[self.kind] if self.kind != 'procedure' else "Procedure"
        if self.kind == 'rule':
            activities = self.rule_activity_ids.mapped('code')
            head += f", {self.severity}" + (f" ({', '.join(activities)})" if activities else "")
        stale = self._is_stale(today)
        return okf.entry(self.name, okf.link(self), f"{head}: {okf.description(self.body)}"
                         + (f" (expires {self.expires})" if self.expires and self.kind != 'rule' else "")
                         + (f" (stale: {stale})" if stale else ""))

    @api.model
    def _okf_context(self, pack, record, messages=5):
        """The context pack as an OKF bundle: index.md (every level with its rules, facts,
        procedures and documents by title and one line, the organisation by section, the
        lessons, what waits for review, the warnings), the task and the project as concepts,
        the rules that bind (never, must) in full when their line in the index does not
        already carry their whole text, and log.md with the latest updates of the project
        and the chatter of the task. A preference, a fact, a procedure, a document or a
        lesson is read on request (memory/read with its concept)."""
        today = fields.Date.context_today(self)
        Attachment, Lesson = self.env['ir.attachment'], self.env['memory.lesson']
        sections, concepts, log_entries = [], [], []
        task = record if record._name == 'project.task' else None
        project = self.env['project.project'].browse(pack['project']['id']) if pack.get('project') else None
        for item in (task, project):
            if item:
                concepts.append((f"{okf.concept_id(item)}.md", item._okf_concept()))
                log_entries += item._okf_log_entries(messages if item is task else PACK_LOG)
        sections.append(("Work", [okf.entry(item.name, okf.link(item), LEVEL_LABELS[item._name])
                                  for item in (task, project) if item]))
        binding = self.browse()
        for level in pack['levels']:
            heading = f"{LEVEL_LABELS[level['model']]}: {level['name'] or level['id']}"
            if level.get('skipped'):
                sections.append((heading, [f"* {level['model']} {level['id']}: {level['skipped']}"]))
                continue
            rules = self.browse([r['id'] for r in level.get('rules', [])])
            # a short rule is whole in its line: its file would say it twice
            binding |= rules.filtered(lambda r: r.severity != 'prefer'
                                      and okf.description(r.body) != " ".join((r.body or '').split()))
            notes = rules | self.browse([n['id'] for key in ('facts', 'procedures') for n in level.get(key, [])])
            documents = Attachment.browse([d['id'] for d in level.get('documents', [])])
            document_lines = [okf.entry(document.name, okf.link(document), "Document"
                                        + (f": {okf.description(document.description)}" if document.description else "")
                                        + (" (original changed)" if document.texo_changed_on else ""))
                              for document in documents]
            if level['model'] == 'res.company':
                # the organisation by section, as the levels of its bundle
                for section in list(notes.section_id.sorted()) + [self.env['memory.section']]:
                    in_section = notes.filtered(lambda n, section=section: n.section_id == section)
                    if in_section:
                        title = f"{heading} / {section.name}" if section else heading
                        sections.append((title, [note._okf_line(today) for note in in_section]))
                sections.append((f"{heading} / Documents", document_lines))
                continue
            sections.append((heading, [note._okf_line(today) for note in notes] + document_lines))
        lessons = Lesson.browse([lesson['id'] for lesson in pack['lessons']])
        sections.append(("Lessons", [okf.entry(lesson.name, okf.link(lesson), f"{lesson.kind.capitalize()}: "
                                               + ", ".join(lesson.tag_ids.mapped('name'))
                                               + (f"; {lesson.applies_to}" if lesson.applies_to else ""))
                                     for lesson in lessons]))
        drafts = self.browse([d['id'] for d in pack['pending']])
        pending = [okf.entry(d.name, okf.link(d), f"draft {d.kind} by {d.create_uid.name}") for d in drafts]
        pending += [okf.entry(lesson['title'], f"/{lesson['concept']}.md", "draft lesson")
                    for lesson in pack.get('pending_lessons', [])]
        sections.append(("Pending review", pending))
        sections.append(("Warnings", [
            okf.entry(w['title'], f"/{w['concept']}.md", f"stale: {w['stale']}") if 'stale' in w
            else f"* Project {w['project_id']}: {w['warning']}" for w in pack['warnings']]))
        meta = [f"* Role: {pack['role']}"] + ([f"* Activities: {', '.join(pack['activities'])}"] if pack.get('activities') else [])
        sections.append(("Session", meta))
        files = [('index.md', okf.index(sections, version=True))] + concepts
        files += [(f"{okf.concept_id(rule)}.md", rule._okf_concept(today)) for rule in binding]
        if log_entries:
            files.append(('log.md', okf.log(f"{(task or project).name}: log", log_entries)))
        return okf.bundle(files)

    @api.model
    def _pack_tags(self, record):
        """The tags the lessons of a pack are chosen by: those of the task and of its project."""
        if record._name == 'res.company':
            return self.env['project.tags']
        # sudo: the tags of the project of a task the user reads; a tag says nothing of the project
        project = record.sudo().project_id if record._name == 'project.task' else record.sudo()
        tags = project.tag_ids
        if record._name == 'project.task':
            tags |= record.tag_ids.sudo()
        return tags.sudo(False)

    def _pack_rule(self, summary):
        """A rule in the pack: a prohibition or an obligation with its text, which binds; a
        preference by its title, read with memory/read when the work touches it."""
        self.ensure_one()
        if self.severity == 'prefer':
            return dict(summary, body_omitted=True)
        body = self.body or ''
        return dict(summary, body=body[:PACK_BODY], **({'truncated': True} if len(body) > PACK_BODY else {}))

    @api.model
    def _agent_context_project(self, record, levels):
        """The project of the pack: the record itself or the project of the task, when
        the user can read it."""
        for level in levels:
            if level['model'] == 'project.project' and not level.get('skipped'):
                return self.env['project.project'].browse(level['id'])
        return None

    @api.model
    def _agent_rules(self, company_id=None, activity=None):
        """The active rules of the organisation, which bind every session, in creation
        order; with the activity of the session, those of that activity and of every
        activity."""
        activities = self.env['memory.note.activity']._from_codes(activity)
        return self.search([('company_id', '=', self._company(company_id).id), ('kind', '=', 'rule'),
                            ('state', '=', 'active')] + self._activity_domain(activities), order='id', limit=PACK_RULES)

    @api.model
    def _agent_rules_text(self, common, company_id=None, activity=None):
        """The rules text of a session: the common rules, then the organisation's own,
        each with its severity and, when it concerns only some, its activities; the
        activities and the sections the organisation knows."""
        rules = self._agent_rules(company_id, activity)
        text = common
        if rules:
            company = self._company(company_id)
            # English, like the common rules: they are read by language models, not translated.
            text += f"\n\nRules of {company.name}:" + "".join(
                f"\n- [{rule.severity}] {rule.name}: {rule.body}"
                + (f" (activities: {', '.join(rule.rule_activity_ids.mapped('code'))})" if rule.rule_activity_ids else "")
                for rule in rules)
        return {'rules': text, 'company_rules': rules._agent_summary(),
                'activities': self.env['memory.note.activity'].search([])._agent_summary(),
                'sections': self.env['memory.section'].search([])._agent_summary()}

    @api.model
    def _search_domain(self, kinds, today=None):
        """The notes the search may give: of these kinds, live (the drafts of the rules too: a
        proposal is found, and the pack says it does not bind), not expired."""
        today = today or fields.Date.context_today(self)
        return [('kind', 'in', kinds), ('state', 'in', ('draft', 'active')),
                '|', ('expires', '=', False), ('expires', '>=', today)]

    def _search_entries(self, ranked, today=None):
        """The search results of these notes, in this order: the summary, the score and the
        words (fulltext.fields of ranked) and the first words of the body; a fact or a
        procedure is flagged by its kind."""
        today = today or fields.Date.context_today(self)
        entries = []
        for note, summary in zip(self, self._agent_summary(today), strict=True):
            entry = dict(summary, **fulltext.fields(ranked, note.id), snippet=" ".join(note.body.split())[:SNIPPET])
            if note.kind != 'rule':
                entry[note.kind] = True
            entries.append(entry)
        return entries

    @api.model
    def _agent_search(self, query, related_terms=None, scope='all', applies_to=None, limit=5, mode=None):
        """Rules, facts and procedures the user may read, documents and lessons when scope
        allows, ranked together by the full-text search: every word first, then the best
        score, whatever the kind. The scope tasks searches the episodes instead: the title,
        the description and the chatter of the tasks the user may read; they are not part
        of all, which is the memory. mode (lexical, semantic, hybrid) means something with
        texo_vector; here the search is lexical whatever it says."""
        limit = max(1, min(int(limit or 5), 20))
        word_list = fulltext.words(query, related_terms)
        results = []
        kinds = {'all': ('rule', 'fact', 'procedure'), 'notes': ('rule',), 'rules': ('rule',), 'facts': ('fact',),
                 'procedures': ('procedure',)}.get(scope, ())
        if kinds:
            today = fields.Date.context_today(self)
            notes, ranked = fulltext.search(self, 'memory_note', 'search_tsv', word_list, limit,
                                            self._search_domain(kinds, today))
            results += notes._search_entries(ranked, today)
        if scope in ('all', 'documents'):
            results += self.env['ir.attachment']._texo_search(query, related_terms, limit)
        if scope in ('all', 'lessons'):
            results += self.env['memory.lesson']._agent_search(query, related_terms, applies_to, limit)
        if scope == 'tasks':
            results += self.env['project.task']._texo_search(query, related_terms, limit)
        results += self._agent_search_extra(query, related_terms, scope, limit)
        return sorted(results, key=lambda r: (-r['score'], -r['id']))

    @api.model
    def _agent_search_extra(self, query, related_terms, scope, limit):
        """The entries of the scopes other modules add (texo_sources: the cards, scope sources and in
        all), ranked as the others: score and words of fulltext. None here."""
        return []

    # -- writing --------------------------------------------------------------
    @api.model
    def _agent_body(self, text):
        text = (text or '').strip() if isinstance(text, str) else ''
        if not text or len(text) > MAX_BODY:
            raise UserError(self.env._("The text is empty or longer than %s characters.", MAX_BODY))
        return text

    @api.model
    def _agent_keywords(self, keywords, current=None):
        """The keywords as one comma-separated text, merged with the current ones."""
        if isinstance(keywords, str):
            keywords = keywords.split(',')
        terms = [t.strip() for t in (current or '').split(',') + list(keywords or []) if t and t.strip()]
        return ", ".join(dict.fromkeys(terms)) or False

    @api.model
    def _agent_note(self, name, body, project_id=None, partner_id=None, state=None, expires=None,
                    source_ref=None, document_id=None, company_id=None, kind='rule', task_id=None, severity=None,
                    activities=None, generated_by=None, section=None, keywords=None, applies_to=None):
        """Write a rule, a fact or a procedure as the user, on a task (not a rule), a project,
        a customer or, with none, the organisation itself (the company).

        A rule: a lead's may be active at once, a member's waits for review; on the
        organisation it binds every session; severity and activities say how and where.
        A fact or a procedure: active and verified today by the person who said yes.
        A record taken from a document of the memory cites it: when the original changes,
        it is marked to re-check until it is verified again."""
        role = self.env.user._texo_check_role()
        kind = kind or 'rule'
        if kind not in dict(KINDS):
            raise UserError(self.env._(
                "A note is a rule, a fact or a procedure. What happened on a task goes in a note on the task; a "
                "finding without the customer goes in a lesson; the state of a project goes in a project update."))
        if not (name or '').strip():
            raise UserError(self.env._("A note needs a title."))
        vals = self._anchor_vals(task_id, project_id, partner_id, company_id)
        vals.update({'kind': kind, 'name': name.strip()[:200], 'body': self._agent_body(body),
                     'expires': expires or False, 'keywords': self._agent_keywords(keywords),
                     'applies_to': applies_to or False,
                     'section_id': self.env['memory.section']._from_code(section).id or False,
                     'rule_activity_ids': [Command.set(self.env['memory.note.activity']._from_codes(activities).ids)]})
        if kind == 'rule':
            if task_id:
                raise UserError(self.env._(
                    "A rule binds the organisation, a customer or a project, not a task: what concerns one task "
                    "goes in a note on the task."))
            state = state or 'draft'
            if state not in ('draft', 'active'):
                raise UserError(self.env._("A new rule is a draft or active."))
            if state == 'active' and role == 'member':
                raise AccessError(self.env._("A member writes drafts; a lead reviews them."))
            severity = severity or 'must'
            if severity not in dict(SEVERITIES):
                raise UserError(self.env._("The severity of a rule is never, must or prefer."))
            vals.update({'state': state, 'severity': severity})
            if state == 'active':
                vals.update({'verified': fields.Date.context_today(self), 'verified_by_id': self.env.uid})
        else:
            anchor = self.new(vals)._anchor()
            if not anchor.has_access('read'):
                raise UserError(self.env._("The record does not exist or is not visible to you."))
        vals.update(self._source_vals(document_id, source_ref, generated_by))
        note = self.create(vals)
        if kind == 'rule' and note.state == 'draft' and role == 'member':
            note._ask_review()
        return note._agent_summary()[0] if kind == 'rule' else note._agent_read()

    def _lock(self):
        """The row of the note, locked until the end of the transaction: two appends never
        overwrite each other."""
        # Raw SQL: the ORM has no row lock.
        self.env.cr.execute("SELECT id FROM memory_note WHERE id = %s FOR UPDATE", [self.id])
        self.invalidate_recordset()

    def _verified_vals(self):
        """Checked today by the user, against its source document too."""
        vals = {'verified': fields.Date.context_today(self), 'verified_by_id': self.env.uid}
        if self.document_id:
            vals['source_checked'] = fields.Datetime.now()
        return vals

    def _agent_append(self, text, keywords=None):
        """A dated, signed paragraph at the end of a fact or a procedure, keywords merged;
        it is verified today."""
        self.ensure_one()
        if self.kind == 'rule':
            raise UserError(self.env._("A rule is not appended to: a lead supersedes it with a new one."))
        self._lock()
        head = f"[{fields.Date.context_today(self)}, {self.env.user.name}]"
        self.write(dict(self._verified_vals(), body=f"{self.body.rstrip()}\n\n{head}\n{self._agent_body(text)}",
                        keywords=self._agent_keywords(keywords, self.keywords)))
        return self._agent_read()

    def _agent_update(self, expected_version=None, body=None, name=None, keywords=None, applies_to=None,
                      expires=None, verified=False, section=None):
        """Replace the text (with the version that was read), the title, the keywords, the
        section or the dates of a note; verified marks it checked today. A rule is changed by
        a lead or, while a draft, by its author."""
        self.ensure_one()
        self._lock()
        if body is not None and expected_version != self._version():
            raise UserError(self.env._(
                "Note %(id)s changed since it was read (version %(version)s): read it again before replacing its text.",
                id=self.id, version=self._version()))
        vals = {}
        if body is not None:
            vals['body'] = self._agent_body(body)
        if name:
            vals['name'] = name.strip()[:200]
        if keywords is not None:
            vals['keywords'] = self._agent_keywords(keywords)
        if section is not None:
            vals['section_id'] = self.env['memory.section']._from_code(section).id or False
        for key, value in (('applies_to', applies_to), ('expires', expires)):
            if value is not None:
                vals[key] = value or False
        if verified or (body is not None and self.kind != 'rule'):
            if self.kind == 'rule':
                self._check_lead()
            vals.update(self._verified_vals())
        if not vals:
            raise UserError(self.env._("Nothing to change in note %s.", self.id))
        self.write(vals)
        return self._agent_read()

    def _reviewers(self):
        """The project manager, else every hub lead."""
        self.ensure_one()
        anchor = self.task_id.sudo().project_id or self.project_id.sudo()
        if anchor and anchor.user_id:
            return anchor.user_id
        return self.env.ref('texo.group_texo_lead').sudo().all_user_ids.filtered('active')

    def _has_open_activity(self, summary):
        self.ensure_one()
        return bool(self.activity_ids.filtered(lambda a: a.summary == summary))

    def _ask_review(self, summary=None, note=None):
        """One activity per reviewer, never twice for the same reason."""
        summary = summary or self.env._("Review the rule")
        for record in self:
            if record._has_open_activity(summary):
                continue
            for user in record._reviewers():
                record.activity_schedule('mail.mail_activity_data_todo', user_id=user.id, summary=summary,
                                         note=note or self.env._("Proposed by %s.", record.create_uid.name))

    @api.model
    def _cron_housekeeping(self):
        """Weekly: every active rule expired or not verified for STALE_DAYS gets one
        activity to its reviewers; nothing changes state on its own."""
        today = fields.Date.context_today(self)
        stale = self.search([('kind', '=', 'rule'), ('state', '=', 'active')]).filtered(lambda n: n._is_stale(today))
        for note in stale:
            note._ask_review(summary=self.env._("Re-check the rule"),
                             note=self.env._("Expired or not verified for %s days: confirm, supersede or archive it.", STALE_DAYS))
        return len(stale)

    @api.model
    def _agent_review(self):
        """The review queue of the person, deterministic: draft rules to decide, active
        rules to re-check, draft lessons and near-duplicate lessons."""
        today = fields.Date.context_today(self)
        role = self.env.user._texo_check_role()
        Lesson = self.env['memory.lesson']

        def rows(notes):
            result = []
            for note, summary in zip(notes, notes._agent_summary(today), strict=True):
                anchor = note._anchor()
                result.append(dict(summary, anchor={'model': anchor._name, 'id': anchor.id,
                                                    'name': anchor.sudo().display_name},
                                   body=(note.body or '')[:PACK_BODY]))
            return result

        drafts = self.search([('kind', '=', 'rule'), ('state', '=', 'draft')], order='id', limit=REVIEW_LIMIT)
        active = self.search([('kind', '=', 'rule'), ('state', '=', 'active')], order='id')
        stale = active.filtered(lambda n: n._is_stale(today))[:REVIEW_LIMIT]
        review = {'role': role, 'drafts': rows(drafts), 'stale': rows(stale), 'draft_lessons': [], 'duplicates': [],
                  'projects_without_now': self._agent_review_projects(role)}
        if role in ('lead', 'admin'):
            review['draft_lessons'] = [lesson._agent_summary() for lesson in
                                       Lesson.search([('state', '=', 'draft')], order='id', limit=REVIEW_LIMIT)]
            review['duplicates'] = [{'lesson_id': first.id, 'other_id': second.id, 'ratio': ratio,
                                     'title': first.name, 'other_title': second.name}
                                    for first, second, ratio in Lesson._duplicate_pairs()[:REVIEW_LIMIT]]
        return review

    @api.model
    def _agent_review_projects(self, role):
        """The projects with open work whose present is missing or old: for a lead every
        project they can read, for a member the projects they manage."""
        Project = self.env['project.project']
        domain = [('is_template', '=', False)]
        if role not in ('lead', 'admin'):
            domain.append(('user_id', '=', self.env.uid))
        projects = Project.search(domain, order='id')
        busy = {project.id for project, in self.env['project.task']._read_group(
            [('project_id', 'in', projects.ids), ('is_closed', '=', False)], ['project_id'])}
        today = fields.Date.context_today(self)
        result = []
        for project in projects.filtered(lambda p: p.id in busy):
            warnings = project._texo_now_warnings(today)
            if warnings:
                result.append({'project_id': project.id, 'name': project.display_name, 'warning': warnings[0],
                               'last_update': fields.Date.to_string(project.last_update_id.date)
                               if project.last_update_id else None})
            if len(result) >= REVIEW_LIMIT:
                break
        return result

    def _agent_confirm(self, expires=None):
        """A note re-checked with the person: verified today, with an expiry if given. A rule
        by a lead, once active; a fact or a procedure by whoever may write it."""
        self.ensure_one()
        if self.kind == 'rule':
            self._check_lead()
            if self.state != 'active':
                raise UserError(self.env._("Only an active rule is confirmed; activate it first."))
        vals = self._verified_vals()
        if expires:
            vals['expires'] = fields.Date.to_date(expires)
        self.write(vals)
        self.activity_feedback(['mail.mail_activity_data_todo'])
        return self._agent_summary()[0]

    def _agent_set_state(self, state, superseded_by_id=None):
        """A lead activates, supersedes or archives a rule; its author or a lead supersedes
        or archives a fact or a procedure. Activating a rule is checking it: against its
        source document too."""
        self.ensure_one()
        if self.kind == 'rule':
            result = super()._agent_set_state(state, superseded_by_id)
            if state == 'active' and self.document_id:
                self.source_checked = fields.Datetime.now()
                result = self._agent_summary()[0]
            return result
        if not (self._is_lead() or self.create_uid == self.env.user):
            raise AccessError(self.env._("Only the author of a note or a lead supersedes or archives it."))
        if state not in ('superseded', 'archived', 'active'):
            raise UserError(self.env._("A note becomes active, superseded or archived."))
        vals = {'state': state}
        if state == 'superseded':
            later = self.browse(int(superseded_by_id or 0)).exists()
            if not later or not later.has_access('read'):
                raise UserError(self.env._("A superseded note needs the note that replaces it."))
            vals['superseded_by_id'] = later.id
            later.supersedes_id = self
        self.write(vals)
        return self._agent_summary()[0]

    def action_activate(self):
        for note in self:
            note._agent_set_state('active')

    def action_archive_note(self):
        for note in self:
            note._agent_set_state('archived')

    def action_verify(self):
        for note in self:
            note._agent_confirm()

