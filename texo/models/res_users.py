# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import AccessError

# Highest privilege first: the first group the user has gives the role.
HUB_ROLE_GROUPS = (
    ('admin', 'texo.group_texo_admin'),
    ('lead', 'texo.group_texo_lead'),
    ('member', 'texo.group_texo_member'),
)
# Do not rewrite the user row on every gateway call.
LAST_SEEN_RESOLUTION = timedelta(minutes=1)


class ResUsers(models.Model):
    _inherit = 'res.users'

    texo_last_seen = fields.Datetime(
        string="Texo Last Seen",
        readonly=True,
        copy=False,
        help="Last time the Texo gateway verified a token of this user.",
    )

    def _texo_role(self):
        """Return 'admin', 'lead', 'member' or False for a single user."""
        self.ensure_one()
        for role, xmlid in HUB_ROLE_GROUPS:
            if self.has_group(xmlid):
                return role
        return False

    def _texo_check_role(self):
        """Raise AccessError (HTTP 403 on json2 routes) when the user has no hub role."""
        self.ensure_one()
        role = self._texo_role()
        if not role:
            raise AccessError(_("You have no Texo role."))
        return role

    def _texo_touch(self):
        now = fields.Datetime.now()
        for user in self:
            if not user.texo_last_seen or now - user.texo_last_seen > LAST_SEEN_RESOLUTION:
                user.texo_last_seen = now
