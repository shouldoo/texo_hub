# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.texo import okf
from odoo.addons.texo.models.secrets import check_no_credential

MAX_DESCRIPTION = 4000
MAX_MESSAGE = 1500
MAX_MESSAGES = 30
MAX_NOTE = 10000


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Every method runs as the calling user: record rules decide which tasks exist.

    texo_keywords = fields.Char(
        string="Search keywords", copy=False,
        help="Synonyms and other names of what this task is about, comma-separated: the words someone will "
             "search it by months later (the symptom as the reporter said it, the technical name, an acronym "
             "and its expansion). The agent adds them with the session note; the search weighs them above the "
             "description and the chatter.")

    def _texo_summary(self):
        states = dict(self._fields['state']._description_selection(self.env))
        result = []
        for task in self:
            # sudo: names of the records linked to a task the user can read, as Odoo
            # shows them on the task form even when the project itself is restricted.
            linked = task.sudo()
            result.append({
                'id': task.id,
                'name': task.name,
                'project': linked.project_id.display_name or None,
                'customer': linked.partner_id.commercial_partner_id.display_name or None,
                'stage': linked.stage_id.name or None,
                'state': states.get(task.state),
                'priority': 'high' if task.priority == '1' else 'normal',
                'deadline': fields.Datetime.to_string(task.date_deadline) if task.date_deadline else None,
                'assignees': linked.user_ids.mapped('name'),
                'updated': fields.Datetime.to_string(task.write_date),
            })
        return result

    @api.model
    def _texo_my_work(self, limit=50):
        # sudo: which projects are templates is configuration, read whatever the rules on the projects say
        templates = self.env['project.project'].sudo()._search([('is_template', '=', True)])
        tasks = self.search(
            # Project tasks only: tasks without a project are personal to-dos, the tasks of a template are no one's work.
            [('user_ids', 'in', self.env.uid), ('is_closed', '=', False), ('project_id', '!=', False),
             ('project_id', 'not in', templates), ('is_template', '=', False)],
            order='priority desc, date_deadline asc, id desc',
            limit=max(1, min(int(limit or 50), 200)),
        )
        return {'tasks': tasks._texo_summary()}

    def _texo_context(self, messages=10):
        self.ensure_one()
        context = self._texo_summary()[0]
        description = html2plaintext(self.description or '').strip()
        if len(description) > MAX_DESCRIPTION:
            description = description[:MAX_DESCRIPTION] + " [...]"
        context.update({
            'description': description or None,
            'tags': self.tag_ids.mapped('name'),
            'keywords': self.texo_keywords or None,
            'parent': self.parent_id.display_name or None,
            'subtasks': [{'id': child.id, 'name': child.name, 'closed': child.is_closed} for child in self.child_ids],
            'milestone': {
                'id': self.milestone_id.id, 'name': self.milestone_id.name, 'reached': self.milestone_id.is_reached,
                'deadline': fields.Date.to_string(self.milestone_id.deadline) if self.milestone_id.deadline else None,
            } if self.milestone_id else None,
            'messages': self._texo_messages(messages),
        })
        return context

    # -- Open Knowledge Format ------------------------------------------------
    def _okf_concept(self):
        """The task as an OKF concept: its description as the body, its subtasks, its place
        in the project; the chatter is its log."""
        self.ensure_one()
        context = self._texo_context(messages=0)
        base = self.get_base_url()
        # sudo: the project and the parent of a task the user reads, as the task form shows them
        linked = self.sudo()
        meta = {
            'type': 'Task', 'title': self.name, 'description': okf.description(context['description']),
            'resource': f"{base}/mail/view?model={self._name}&res_id={self.id}", 'tags': context['tags'],
            'status': 'deprecated' if self.is_closed else 'stable',
            'generated': {'by': okf.human(self.write_uid), 'at': okf.timestamp(self.write_date)},
            'project': okf.link(linked.project_id) if linked.project_id else None,
            'parent': okf.link(linked.parent_id) if linked.parent_id else None,
            'customer': context['customer'], 'stage': context['stage'], 'state': context['state'],
            'priority': context['priority'], 'deadline': context['deadline'], 'assignees': context['assignees'],
            'milestone': {'id': context['milestone']['id'], 'name': context['milestone']['name']}
            if context['milestone'] else None,
        }
        body = [context['description'] or '']
        if self.child_ids:
            body.append("# Subtasks\n\n" + "\n".join(
                okf.entry(child.name, okf.link(child), 'closed' if child.is_closed else 'open') for child in self.child_ids))
        body.append(f"The chatter: [log](/{okf.concept_id(self)}/log.md).")
        return okf.concept(meta, "\n\n".join(body))

    def _okf_log_entries(self, limit=20):
        """The latest human messages of the chatter, as log entries."""
        self.ensure_one()
        return [(message['date'], 'Note' if message['internal_note'] else 'Message',
                 f"{message['author'] or ''}: {message['body']}") for message in self._texo_messages(limit)]

    def _okf_log(self, limit=20):
        self.ensure_one()
        return okf.log(f"{self.name}: log", self._okf_log_entries(limit))

    def _texo_messages(self, limit):
        """Latest human messages of the chatter, newest first, as plain text."""
        self.ensure_one()
        limit = max(0, min(int(limit or 0), MAX_MESSAGES))
        if not limit:
            return []
        messages = self.env['mail.message'].search([
            ('model', '=', self._name), ('res_id', '=', self.id),
            ('message_type', 'in', ('comment', 'email', 'email_outgoing')),
        ], order='date desc, id desc', limit=limit)
        result = []
        for message in messages:
            body = html2plaintext(message.body or '').strip()
            if len(body) > MAX_MESSAGE:
                body = body[:MAX_MESSAGE] + " [...]"
            result.append({
                'date': fields.Datetime.to_string(message.date),
                'author': message.author_id.display_name or None,
                'internal_note': bool(message.subtype_id.internal),
                'body': body,
            })
        return result

    @api.model
    def _texo_merge_keywords(self, keywords, current=None):
        """The keywords as one comma-separated text, merged with the current ones, or False."""
        if isinstance(keywords, str):
            keywords = keywords.split(',')
        terms = [t.strip() for t in (current or '').split(',') + list(keywords or []) if t and t.strip()]
        return ", ".join(dict.fromkeys(terms)) or False

    def _texo_post_note(self, body, keywords=None):
        """Post an internal note as the calling user; the body is plain text. The keywords,
        if any, are merged into the search keywords of the task."""
        self.ensure_one()
        body = (body or '').strip() if isinstance(body, str) else ''
        if not body:
            raise UserError(_("The note is empty."))
        if len(body) > MAX_NOTE:
            raise UserError(_("The note is longer than %(max)s characters.", max=MAX_NOTE))
        check_no_credential(self.env, body, keywords if isinstance(keywords, str) else " ".join(keywords or []))
        merged = self._texo_merge_keywords(keywords, self.texo_keywords)
        # idempotent: the last internal note of the task with the same text (a call retried, a session
        # that proposes it twice) is given back, with existing true, and nothing is posted
        last = self.env['mail.message'].search(
            [('model', '=', 'project.task'), ('res_id', '=', self.id), ('message_type', '=', 'comment'),
             ('subtype_id', '=', self.env.ref('mail.mt_note').id)], order='id desc', limit=1)
        existing = bool(last) and " ".join(html2plaintext(last.body or '').split()) == " ".join(body.split())
        if existing:
            message = last
        else:
            # A str body is escaped by message_post: agents cannot inject HTML.
            message = self.message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_note')
        if merged != (self.texo_keywords or False):
            # sudo: the keywords belong to the note, which the user could post (read access to the
            # task is enough for a note); they change nothing else on the task
            self.sudo().write({'texo_keywords': merged})
        result = {'message_id': message.id, 'task_id': self.id, 'keywords': merged or None}
        if existing:
            result['existing'] = True
        return result
