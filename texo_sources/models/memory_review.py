# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models

MEMBER = 'texo.group_texo_member'


class MemoryReview(models.TransientModel):
    """The external sources in the review: candidates to sort, cards to approve, cards due for
    their review, channels overdue."""
    _inherit = 'memory.review'

    source_candidates = fields.Integer(compute='_compute_counts')
    source_to_approve = fields.Integer(compute='_compute_counts')
    source_to_write = fields.Integer(compute='_compute_counts')
    source_due = fields.Integer(compute='_compute_counts')
    source_channels_overdue = fields.Integer(compute='_compute_counts')

    @api.model
    def _queues(self):
        today = fields.Date.context_today(self)
        return dict(super()._queues(), **{
            'source_candidates': {'title': self.env._("Candidates to Sort"), 'model': 'memory.source.item',
                                  'domain': [('state', '=', 'candidate')],
                                  'action': 'texo_sources.action_memory_source_triage'},
            'source_to_approve': {'title': self.env._("Cards to Approve"), 'model': 'memory.source.item',
                                  'domain': [('state', '=', 'to_approve')], 'lead': True,
                                  'action': 'texo_sources.action_memory_source_to_approve'},
            'source_to_write': {'title': self.env._("Cards to Write"), 'model': 'memory.source.item',
                                'domain': [('state', '=', 'todo')],
                                'action': 'texo_sources.action_memory_source_item'},
            'source_due': {'title': self.env._("Cards to Review"), 'model': 'memory.source.item',
                           'domain': [('state', '=', 'active'), ('review_date', '<=', today)],
                           'action': 'texo_sources.action_memory_source_item'},
            'source_channels_overdue': {'title': self.env._("Channels Overdue"), 'model': 'memory.source.channel',
                                        'domain': [('overdue', '=', True)],
                                        'action': 'texo_sources.action_memory_source_channel'},
        })


class ProjectProject(models.Model):
    _inherit = 'project.project'

    texo_source_count = fields.Integer(string="Source Cards", compute='_compute_texo_source_count',
                                                groups=MEMBER)

    def _compute_texo_source_count(self):
        counts = dict(self.env['memory.source.item']._read_group(
            [('project_id', 'in', self.ids), ('state', 'in', ('to_approve', 'active'))], ['project_id'], ['__count']))
        for project in self:
            project.texo_source_count = counts.get(project, 0)

    def action_texo_source_cards(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('texo_sources.action_memory_source_item')
        action.update(name=self.env._("Source Cards of %s", self.display_name),
                      domain=[('project_id', '=', self.id), ('state', 'not in', ('candidate', 'discarded'))],
                      context={})
        return action


class MemoryReviewArea(models.Model):
    """The external sources as an area of the dashboard of the review: the cards to approve first."""
    _inherit = 'memory.review.area'

    source_candidates = fields.Integer(compute='_compute_counts')
    source_to_approve = fields.Integer(compute='_compute_counts')
    source_to_write = fields.Integer(compute='_compute_counts')
    source_due = fields.Integer(compute='_compute_counts')
    source_channels_overdue = fields.Integer(compute='_compute_counts')

    @api.model
    def _area_queues(self):
        return dict(super()._area_queues(),
                    sources=['source_to_approve', 'source_candidates', 'source_to_write', 'source_due',
                             'source_channels_overdue'])
