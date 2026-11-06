# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models


class TexoMetrics(models.AbstractModel):
    _inherit = 'texo.metrics'

    @api.model
    def _collect(self):
        """What the memory holds: the notes by kind and state, the rules to re-check, the lessons by
        state, the documents of the memory (with a text kept or not), the episodes with their vector."""
        metrics = super()._collect()
        Note = self.env['memory.note'].sudo()
        for kind, state, count in Note._read_group([], ['kind', 'state'], ['__count']):
            metrics.append(self._metric('texo_memory_notes', "Notes of the memory by kind and state.", count,
                                        {'kind': kind, 'state': state}))
        today = fields.Date.context_today(self)
        stale = Note.search([('kind', '=', 'rule'), ('state', '=', 'active')]).filtered(lambda n: n._is_stale(today))
        metrics.append(self._metric('texo_memory_rules_stale', "Active rules to re-check: expired, not verified "
                                                               "for 180 days, or their source document changed.", len(stale)))
        for state, count in self.env['memory.lesson'].sudo()._read_group([], ['state'], ['__count']):
            metrics.append(self._metric('texo_memory_lessons', "Lessons by state.", count, {'state': state}))
        Attachment = self.env['ir.attachment'].sudo()
        for keep_text, count in Attachment._read_group([('texo_document', '=', True)], ['texo_keep_text'], ['__count']):
            metrics.append(self._metric('texo_memory_documents', "Documents of the memory, by whether a text is kept.",
                                        count, {'text': 'kept' if keep_text else 'none'}))
        metrics.append(self._metric('texo_memory_passages', "Passages of the converted texts, cut by structure.",
                                    self.env['memory.document.passage'].sudo().search_count([])))
        self.env.cr.execute("SELECT count(*) FROM project_task WHERE texo_tsv IS NOT NULL AND project_id IS NOT NULL")
        metrics.append(self._metric('texo_memory_episodes', "Tasks of a project with their full-text vector.",
                                    self.env.cr.fetchone()[0]))
        return metrics
