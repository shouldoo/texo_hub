# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models


class ResUsersApikeysDescription(models.TransientModel):
    _inherit = 'res.users.apikeys.description'

    # A key with this scope only opens routes with bearer_scope='texo':
    # it is refused by /json/2 and XML-RPC, which require the 'rpc' scope.
    scope = fields.Selection(
        selection_add=[('texo', 'Texo')],
        ondelete={'texo': 'set default'},
    )
    texo_read_only = fields.Boolean(
        string="Read Only",
        help="A Texo token that reads the memory and never writes: for an assistant that only consults, or a "
             "scraper of the metrics.")

    def make_key(self):
        if self.scope == 'texo' and self.texo_read_only:
            return super(ResUsersApikeysDescription, self.with_context(texo_read_only=True)).make_key()
        return super().make_key()
