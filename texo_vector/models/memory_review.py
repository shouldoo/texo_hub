# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models

ADMIN = 'texo.group_texo_admin'


class MemoryReview(models.TransientModel):
    """The texts waiting for a vector in the review of the administrators: a number that does not
    go down is a service that does not answer, a cron that does not run, or Odoo processes still
    running the code of before an update (the fault of 2026-11-01)."""
    _inherit = 'memory.review'

    vectors_pending = fields.Integer(compute='_compute_vectors_pending', groups=ADMIN)

    def _compute_vectors_pending(self):
        pending = self.env['memory.embedding']._pending()['pending'] if self.env.user.has_group(ADMIN) else 0
        for review in self:
            review.vectors_pending = pending

    def action_open_vector_status(self):
        return self.env['ir.actions.act_window']._for_xml_id('texo_vector.action_memory_vector_status')


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model
    def _agent_review(self):
        """The review of the agent says it too, to the administrators: texts waiting for a vector and the model."""
        review = super()._agent_review()
        if self.env.user.has_group(ADMIN):
            review['vectors'] = self.env['memory.embedding']._pending()
        return review


class MemoryReviewArea(models.Model):
    """The search as an area of the dashboard of the review, for the administrators: the texts waiting for a
    vector, and the button opens the state of the search."""
    _inherit = 'memory.review.area'

    def _compute_counts(self):
        super()._compute_counts()
        search = self.filtered(lambda area: area.code == 'search')
        if search:
            pending = self.env['memory.embedding']._pending()['pending'] if self.env.user.has_group(ADMIN) else 0
            search.update({'main_count': pending, 'pending': pending,
                           'main_title': self.env._("Texts Waiting for a Vector")})

    def action_open_main(self):
        self.ensure_one()
        if self.code == 'search':
            return self.env['ir.actions.act_window']._for_xml_id('texo_vector.action_memory_vector_status')
        return super().action_open_main()
