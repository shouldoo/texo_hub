# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models
from odoo.exceptions import UserError


class MemoryReviewArea(models.Model):
    """An area of the review of the memory as a card of a dashboard, as the overview of the inventory: its
    main queue as a big button, the other queues of the area as lines with their counts. The queues stay
    those of memory.review (_queues, the same the agent reads): an area only names which of them it shows,
    and a module that adds queues adds its area and its part of the card. Counted with the access of the
    user, as the review; an area of a group (the lessons for the leads) is shown only to that group."""
    _name = 'memory.review.area'
    _description = "Memory: Area of the Review"
    _order = 'sequence, id'

    code = fields.Char(required=True, readonly=True)
    name = fields.Char(required=True, translate=True)
    description = fields.Char(translate=True)
    sequence = fields.Integer(default=10)
    main_queue = fields.Char(required=True, help="The queue of memory.review opened by the big button.")
    group_id = fields.Many2one('res.groups', ondelete='cascade', help="Only this group sees the area.")
    # the counts of the queues, with the names of the queues of memory.review: a module adds the fields of its own
    main_count = fields.Integer(compute='_compute_counts')
    main_title = fields.Char(compute='_compute_counts')
    pending = fields.Integer(compute='_compute_counts', help="Everything waiting in the queues of the area.")
    draft_rules = fields.Integer(compute='_compute_counts')
    stale_notes = fields.Integer(compute='_compute_counts')
    changed_documents = fields.Integer(compute='_compute_counts')
    draft_lessons = fields.Integer(compute='_compute_counts')
    duplicate_lessons = fields.Integer(compute='_compute_counts')
    projects_without_now = fields.Integer(compute='_compute_counts')

    _unique_code = models.Constraint('UNIQUE(code)', "An area with this code already exists.")

    @api.model
    def _area_queues(self):
        """{area code: [queue codes]}: which queues of memory.review each area shows, the main one first."""
        return {
            'knowledge': ['stale_notes', 'draft_rules', 'changed_documents'],
            'lessons': ['draft_lessons', 'duplicate_lessons'],
            'projects': ['projects_without_now'],
        }

    @api.depends_context('uid')
    def _compute_counts(self):
        counts = self.env['memory.review']._queue_counts()
        titles = {code: queue['title'] for code, queue in self.env['memory.review']._queues().items()}
        queue_fields = [name for name in counts if name in self._fields]
        for area in self:
            mine = self._area_queues().get(area.code, [])
            values = {name: counts.get(name, 0) for name in queue_fields}
            values.update(main_count=counts.get(area.main_queue, 0), main_title=titles.get(area.main_queue, ''),
                          pending=sum(counts.get(code, 0) for code in mine))
            area.update(values)

    def action_open_main(self):
        self.ensure_one()
        return self.with_context(queue=self.main_queue).action_open_queue()

    def action_open_queue(self):
        """Open a queue of the area (the queue in the context) as the review does."""
        queue = self.env.context.get('queue')
        if queue not in self.env['memory.review']._queues():
            raise UserError(self.env._("Unknown queue: %s", queue))
        return self.env['memory.review'].with_context(queue=queue).action_open_queue()
