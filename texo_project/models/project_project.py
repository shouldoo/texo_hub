# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html

from odoo.addons.texo import okf
from odoo.addons.project.models.project_task import CLOSED_STATES

MAX_DESCRIPTION = 4000
MAX_NOW = 3000
MAX_MILESTONES = 20
MAX_UPDATE = 10000
MAX_LOG = 50
# After this many days the last update no longer tells the present of the project.
NOW_DAYS = 30


class ProjectProject(models.Model):
    _inherit = 'project.project'

    texo_home = fields.Boolean(
        string="Company Home", readonly=True, copy=False, index=True,
        help="The home of the company's own memory: what belongs to the organisation itself and to no "
             "customer (its documents, notes and internal work) is anchored here. One per company, created "
             "with the company.")

    @api.constrains('texo_home', 'company_id', 'partner_id')
    def _check_texo_home(self):
        for project in self.filtered('texo_home'):
            if not project.company_id:
                raise UserError(self.env._("The home of a company needs its company."))
            if project.partner_id:
                raise UserError(self.env._("The home of a company has no customer: the organisation is not one."))
            others = self.with_context(active_test=False).search_count(
                [('texo_home', '=', True), ('company_id', '=', project.company_id.id), ('id', '!=', project.id)])
            if others:
                raise UserError(self.env._("Company %s already has its home project.", project.company_id.name))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_home(self):
        if self.filtered('texo_home'):
            raise UserError(self.env._("The home of a company anchors its memory and cannot be deleted; archive it."))

    def _texo_is_own_partner(self, partner):
        """Whether a partner is one of our companies: the organisation is never a customer."""
        own = self.env['res.company'].sudo().with_context(active_test=False).search([]).partner_id
        return bool(partner) and partner.commercial_partner_id in own

    # -- context of a project for agents ------------------------------------
    # Every method runs as the calling user: record rules decide which projects,
    # milestones and updates exist.

    @staticmethod
    def _texo_text(html, limit):
        text = html2plaintext(html or '').strip()
        return (text[:limit] + " [...]" if len(text) > limit else text) or None

    def _texo_milestones(self):
        """The roadmap: the milestones not reached first, by deadline (the overdue ones
        lead), then the reached ones; with the tasks the user can see."""
        self.ensure_one()
        if not self.allow_milestones:
            return []
        milestones = self.env['project.milestone'].search([('project_id', '=', self.id)]).sorted(
            lambda m: (m.is_reached, m.deadline or fields.Date.to_date('9999-12-31'), m.sequence, m.id))
        milestones = milestones[:MAX_MILESTONES]
        counts = {}
        for milestone, state, count in self.env['project.task']._read_group(
                [('milestone_id', 'in', milestones.ids)], ['milestone_id', 'state'], ['__count']):
            key = (milestone.id, state in CLOSED_STATES)
            counts[key] = counts.get(key, 0) + count
        today = fields.Date.context_today(self)
        return [{
            'id': milestone.id, 'name': milestone.name,
            'deadline': fields.Date.to_string(milestone.deadline) if milestone.deadline else None,
            'reached': milestone.is_reached,
            'reached_date': fields.Date.to_string(milestone.reached_date) if milestone.reached_date else None,
            'overdue': bool(not milestone.is_reached and milestone.deadline and milestone.deadline < today),
            'open_tasks': counts.get((milestone.id, False), 0), 'closed_tasks': counts.get((milestone.id, True), 0),
        } for milestone in milestones]

    def _texo_now_warnings(self, today=None):
        """Why the last update may not tell the present: there is none, it is older than
        NOW_DAYS, or a milestone was reached or fell due after it."""
        self.ensure_one()
        today = today or fields.Date.context_today(self)
        update = self.last_update_id
        if not update:
            return ['now_missing']
        if update.date < today - timedelta(days=NOW_DAYS):
            return ['now_stale']
        if self.allow_milestones and self.env['project.milestone'].search_count([
                ('project_id', '=', self.id), '|',
                '&', ('is_reached', '=', True), ('reached_date', '>', update.date),
                '&', '&', ('is_reached', '=', False), ('deadline', '>=', update.date), ('deadline', '<', today)]):
            return ['now_stale']
        return []

    def _texo_update_summary(self, update):
        statuses = dict(update._fields['status']._description_selection(self.env))
        return {
            'id': update.id, 'title': update.name, 'date': fields.Date.to_string(update.date),
            'author': update.user_id.name, 'status': update.status, 'status_label': statuses.get(update.status),
            'progress': update.progress, 'description': self._texo_text(update.description, MAX_NOW),
        }

    def _texo_context(self):
        """The project as an agent needs it: what it is (the description), the roadmap
        (the milestones) and its present (the last update), with the warnings on it."""
        self.ensure_one()
        # sudo: the names of the customer and of the manager, as the project form shows them
        linked = self.sudo()
        update = self.last_update_id
        return {
            'id': self.id, 'name': self.name,
            'customer': linked.partner_id.commercial_partner_id.display_name or None,
            'manager': linked.user_id.name or None,
            'home': self.texo_home,
            'description': self._texo_text(self.description, MAX_DESCRIPTION),
            'milestones': self._texo_milestones(),
            'now': self._texo_update_summary(update) if update else None,
            'warnings': self._texo_now_warnings(),
        }

    # -- Open Knowledge Format ------------------------------------------------
    # The native fields keep their names; the agent reads them as an OKF concept (the
    # description, the milestones and the present) and a log (the updates, newest first).

    def _okf_concept(self):
        self.ensure_one()
        context = self._texo_context()
        base = self.get_base_url()
        now = context['now']
        meta = {
            'type': 'Project', 'title': self.name, 'description': okf.description(context['description']),
            'resource': f"{base}/mail/view?model={self._name}&res_id={self.id}",
            'tags': self.tag_ids.mapped('name'), 'status': 'stable' if self.active else 'deprecated',
            'generated': {'by': okf.human(self.write_uid), 'at': okf.timestamp(self.write_date)},
            'customer': context['customer'], 'manager': context['manager'], 'home': self.texo_home or None,
            'warnings': context['warnings'],
            'now': {'id': now['id'], 'date': now['date'], 'status': now['status']} if now else None,
        }
        body = [context['description'] or '']
        if context['milestones']:
            body.append("# Milestones\n\n" + "\n".join(
                f"* [{'x' if m['reached'] else ' '}] {m['name']}"
                + (f", due {m['deadline']}" if m['deadline'] else '') + (" (overdue)" if m['overdue'] else '')
                + f": {m['open_tasks']} open, {m['closed_tasks']} closed tasks" for m in context['milestones']))
        if now:
            body.append(f"# Now\n\n**{now['title']}** ({now['date']}, {now['status_label']}, {now['progress']}%, "
                        f"{now['author']})\n\n{now['description'] or ''}\n\nThe history: [log](/{okf.concept_id(self)}/log.md).")
        return okf.concept(meta, "\n\n".join(body))

    def _okf_log_entries(self, limit=20):
        """The updates of the project and the milestones reached, as log entries."""
        self.ensure_one()
        limit = max(1, min(int(limit or 20), MAX_LOG))
        updates = self.env['project.update'].search([('project_id', '=', self.id)], order='date desc, id desc', limit=limit)
        entries = []
        for update in updates:
            summary = self._texo_update_summary(update)
            entries.append((summary['date'], 'Update',
                            f"{summary['title']} ({summary['status_label']}, {summary['progress']}%, {summary['author']}): "
                            f"{summary['description'] or ''}"))
        if self.allow_milestones:
            reached = self.env['project.milestone'].search(
                [('project_id', '=', self.id), ('is_reached', '=', True), ('reached_date', '!=', False)],
                order='reached_date desc', limit=limit)
            entries += [(fields.Date.to_string(m.reached_date), 'Milestone', f"reached: {m.name}") for m in reached]
        return entries

    def _okf_log(self, limit=20):
        self.ensure_one()
        return okf.log(f"{self.name}: log", self._okf_log_entries(limit))

    def _texo_write_update(self, name, status, description, progress=None):
        """A new update as the calling user: it becomes the present of the project, the
        previous ones its history. The description is plain text, escaped."""
        self.ensure_one()
        statuses = dict(self.env['project.update']._fields['status']._description_selection(self.env))
        if status not in statuses:
            raise UserError(self.env._("The status is one of: %s.", ", ".join(statuses)))
        name = (name or '').strip() if isinstance(name, str) else ''
        description = (description or '').strip() if isinstance(description, str) else ''
        if not name or not description:
            raise UserError(self.env._("An update needs a title and a description."))
        if len(description) > MAX_UPDATE:
            raise UserError(self.env._("The description is longer than %(max)s characters.", max=MAX_UPDATE))
        if progress is None:
            progress = self.last_update_id.progress or 0
        if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= 100:
            raise UserError(self.env._("The progress is a whole number from 0 to 100."))
        update = self.env['project.update'].create({
            'project_id': self.id, 'name': name[:200], 'status': status, 'progress': progress,
            'description': plaintext2html(description),
        })
        return self._texo_update_summary(update)
