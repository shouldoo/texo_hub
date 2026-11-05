# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, models


class MemorySearch(models.TransientModel):
    _inherit = 'memory.search'

    @api.model
    def _default_mode(self):
        return self.env['memory.embedding']._mode()

    def _compute_vectors(self):
        self.vectors = self.env['memory.embedding']._available()
