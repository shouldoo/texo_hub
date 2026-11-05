# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, fields, models


class MemorySearch(models.TransientModel):
    _inherit = 'memory.search'

    scope = fields.Selection(selection_add=[('sources', "Source Cards")], ondelete={'sources': 'set default'})


class MemorySearchLine(models.TransientModel):
    _inherit = 'memory.search.line'

    @api.model
    def _from_entry(self, entry):
        """A card of the external sources: its channel and event date in the excerpt."""
        if not entry.get('source'):
            return super()._from_entry(entry)
        line = super()._from_entry(dict(entry, kind=None))
        where = " · ".join(filter(None, [entry.get('channel'), entry.get('event_date')]))
        line.update(res_model='memory.source.item', kind=self.env._("Source Card"),
                    path=where or False)
        return line
