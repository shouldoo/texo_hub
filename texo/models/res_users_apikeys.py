# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import datetime, timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError, ValidationError

HUB_SCOPE = 'texo'
DEFAULT_MAX_DAYS = 90


class ResUsersApikeys(models.Model):
    _inherit = 'res.users.apikeys'

    user_texo_last_seen = fields.Datetime(
        related='user_id.texo_last_seen',
        string="Last Seen by the Hub",
    )

    def _texo_max_days(self):
        # sudo: system parameter read by any user generating a key
        value = self.env['ir.config_parameter'].sudo().get_int('texo.token_max_days')
        return value or DEFAULT_MAX_DAYS

    def _generate(self, scope, name, expiration_date):
        if scope == HUB_SCOPE:
            self._texo_check_generate(expiration_date)
        return super()._generate(scope, name, expiration_date)

    def _texo_check_generate(self, expiration_date):
        """Hub tokens always expire, within the configured maximum, even for administrators."""
        if not self.env.user._texo_role():
            raise UserError(_("Only Texo users can create a Texo token."))
        max_days = self._texo_max_days()
        if not expiration_date:
            raise ValidationError(_("A Texo token must have an expiration date."))
        if fields.Datetime.to_datetime(expiration_date) > datetime.now() + timedelta(days=max_days):
            raise ValidationError(
                _("A Texo token cannot last more than %(days)s days.", days=max_days))
