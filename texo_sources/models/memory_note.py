# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, models


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model
    def _agent_context_whole(self, task_id=None, project_id=None, messages=5, company_id=None, activity=None):
        """The pack, with the external sources when the organisation follows any: the channels
        overdue (of the organisation and of the project of the pack), the candidates to sort
        and the cards waiting for approval. So the agent knows what to read without remembering.
        Before the budget, which counts them."""
        pack = super()._agent_context_whole(task_id, project_id, messages, company_id, activity)
        Channel = self.env['memory.source.channel']
        if not Channel.search_count([]):
            return pack
        project = pack.get('project') or {}
        Item = self.env['memory.source.item']
        pack['sources'] = {
            'channels_due': Channel._agent_due(project.get('id')),
            'candidates': Item.search_count([('state', '=', 'candidate')]),
            'candidates_watched': Item.search_count([('state', '=', 'candidate'), ('watch_match', '=', True)]),
            'to_write': Item.search_count([('state', '=', 'todo')]),
            'to_approve': Item.search_count([('state', '=', 'to_approve')]),
        }
        return pack
