# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import re
from datetime import datetime, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools import SQL

from odoo.addons.base.models.res_users import INDEX_SIZE, KEY_CRYPT_CONTEXT

HUB_SCOPE = 'texo'
DEFAULT_MAX_DAYS = 90
BEARER = re.compile(r'^bearer\s+(.+)$', re.IGNORECASE)


class ResUsersApikeys(models.Model):
    _inherit = 'res.users.apikeys'

    user_texo_last_seen = fields.Datetime(
        related='user_id.texo_last_seen',
        string="Last Seen by the Hub",
    )
    # the table is not the ORM's (_auto = False): the column is added by init()
    texo_read_only = fields.Boolean(
        string="Read Only", readonly=True,
        help="A Texo token that reads the memory and never writes: every write route refuses it, the MCP server "
             "hides the write tools. For an assistant that only consults, or a scraper.")

    def init(self):
        super().init()
        self.env.cr.execute("ALTER TABLE res_users_apikeys ADD COLUMN IF NOT EXISTS texo_read_only boolean "
                            "DEFAULT false")

    def _texo_max_days(self):
        # sudo: system parameter read by any user generating a key
        value = self.env['ir.config_parameter'].sudo().get_int('texo.token_max_days')
        return value or DEFAULT_MAX_DAYS

    def _generate(self, scope, name, expiration_date):
        if scope == HUB_SCOPE:
            self._texo_check_generate(expiration_date)
        key = super()._generate(scope, name, expiration_date)
        if scope == HUB_SCOPE and self.env.context.get('texo_read_only'):
            # the row just written, by its index: the base model gives the key, not the record
            self.env.cr.execute("UPDATE res_users_apikeys SET texo_read_only = true WHERE user_id = %s AND scope = %s "
                                "AND index = %s", (self.env.uid, scope, key[:INDEX_SIZE]))
            self.invalidate_model(['texo_read_only'])
        return key

    @api.model
    def _texo_request_key(self):
        """The hub key the request came with, or an empty recordset: the bearer of the request, verified
        as Odoo verifies it (the index, then the hash). Read once per request."""
        if not request or not request.httprequest:
            return self.browse()
        if getattr(request, 'texo_key', None) is not None:
            return request.texo_key
        found = self.browse()
        match = BEARER.match(request.httprequest.headers.get('Authorization') or '')
        if match:
            key = match.group(1)
            self.env.cr.execute(SQL("SELECT id, key FROM res_users_apikeys WHERE index = %s AND scope = %s AND user_id = %s",
                                    key[:INDEX_SIZE], HUB_SCOPE, self.env.uid))
            for key_id, stored in self.env.cr.fetchall():
                if KEY_CRYPT_CONTEXT.verify(key, stored):
                    found = self.sudo().browse(key_id)
                    break
        request.texo_key = found
        return found

    @api.model
    def _texo_request_read_only(self):
        """Whether the request came with a read-only hub token."""
        key = self._texo_request_key()
        return bool(key and key.texo_read_only)

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
