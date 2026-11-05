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
