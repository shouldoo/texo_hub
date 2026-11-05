# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models
from odoo.exceptions import UserError


class MemoryReview(models.TransientModel):
    """The weekly review of the memory for the people: each queue of the review (what the
    agent reads with memory/review) with how many records wait in it, and a button that
    opens them. Counted with the access of the user: a member sees what they may act on."""
    _name = 'memory.review'
    _description = "Memory: To Review"

    draft_rules = fields.Integer(compute='_compute_counts')
    stale_notes = fields.Integer(compute='_compute_counts')
    changed_documents = fields.Integer(compute='_compute_counts')
    draft_lessons = fields.Integer(compute='_compute_counts')
    duplicate_lessons = fields.Integer(compute='_compute_counts')
    projects_without_now = fields.Integer(compute='_compute_counts')

    @api.model
    def _queues(self):
        """{queue: {title, model, domain (a list, or a method giving one), action (the xml id of the action
        whose views open it; the default views without), lead (only the leads act on it)}} of the review;
        each queue is also a field holding its count."""
        return {
            'draft_rules': {'title': self.env._("Draft Rules"), 'model': 'memory.note',
                            'domain': [('kind', '=', 'rule'), ('state', '=', 'draft')]},
            'stale_notes': {'title': self.env._("To Check"), 'model': 'memory.note', 'domain': [('stale', '=', True)]},
            'changed_documents': {'title': self.env._("Changed Documents"), 'model': 'ir.attachment',
                                  'domain': [('texo_document', '=', True),
                                             ('texo_changed_on', '!=', False)],
                                  'action': 'texo_memory.action_memory_document'},
            'draft_lessons': {'title': self.env._("Draft Lessons"), 'model': 'memory.lesson',
                              'domain': [('state', '=', 'draft')], 'lead': True},
            'duplicate_lessons': {'title': self.env._("Near-duplicate Lessons"), 'model': 'memory.lesson',
                                  'domain': self._duplicate_domain, 'lead': True},
            'projects_without_now': {'title': self.env._("Projects Without a Recent Update"),
                                     'model': 'project.project', 'domain': self._projects_domain},
        }

    def _compute_display_name(self):
        self.display_name = self.env._("To Review")

    def _is_lead(self):
        return self.env.user.has_group('texo.group_texo_lead')

    def _duplicate_domain(self):
        ids = {lesson.id for pair in self.env['memory.lesson']._duplicate_pairs() for lesson in pair[:2]}
        return [('id', 'in', list(ids))]

    def _projects_domain(self):
        role = self.env.user._texo_check_role()
        return [('id', 'in', [row['project_id'] for row in self.env['memory.note']._agent_review_projects(role)])]

    @api.model
    def _domain(self, queue):
        domain = queue['domain']
        return domain() if callable(domain) else domain

    @api.model
    def _queue_counts(self):
        """{queue: how many records wait in it} with the access of the user; 0 for a queue of the leads when
        the user is not one. The review and the areas of its dashboard (memory.review.area) count with it."""
        lead = self._is_lead()
        return {name: 0 if queue.get('lead') and not lead else self.env[queue['model']].search_count(self._domain(queue))
                for name, queue in self._queues().items()}

    def _compute_counts(self):
        counts = {name: value for name, value in self._queue_counts().items() if name in self._fields}
        for review in self:
            review.update(counts)

    def action_open_queue(self):
        queue = self._queues().get(self.env.context.get('queue'))
        if not queue:
            raise UserError(self.env._("Unknown queue: %s", self.env.context.get('queue')))
        if queue.get('action'):
            action = self.env['ir.actions.act_window']._for_xml_id(queue['action'])
        else:
            action = {'type': 'ir.actions.act_window', 'res_model': queue['model'], 'view_mode': 'list,form',
                      'views': [(False, 'list'), (False, 'form')]}
        action.update(name=queue['title'], domain=self._domain(queue), context={}, target='current')
        return action
