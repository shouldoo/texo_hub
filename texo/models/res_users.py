# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import collections
import threading
import time
from datetime import timedelta

from werkzeug.exceptions import TooManyRequests

from odoo import _, fields, models
from odoo.exceptions import AccessError
from odoo.http import request

# Highest privilege first: the first group the user has gives the role.
HUB_ROLE_GROUPS = (
    ('admin', 'texo.group_texo_admin'),
    ('lead', 'texo.group_texo_lead'),
    ('member', 'texo.group_texo_member'),
)
# Do not rewrite the user row on every gateway call.
LAST_SEEN_RESOLUTION = timedelta(minutes=1)
# the requests a person may make per minute, per Odoo process (texo.rate_limit_per_minute; 0: no limit)
PARAM_RATE_LIMIT = 'texo.rate_limit_per_minute'
DEFAULT_RATE_LIMIT = 240
_requests = collections.defaultdict(collections.deque)
_requests_lock = threading.Lock()


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
        """Raise AccessError (HTTP 403 on json2 routes) when the user has no hub role; in a request, also
        the limit of requests per minute (429) and the refusal of a write with a read-only token."""
        self.ensure_one()
        role = self._texo_role()
        if not role:
            raise AccessError(_("You have no Texo role."))
        if request and request.httprequest:
            self._texo_check_rate()
            self._texo_check_write()
        return role

    def _texo_check_write(self):
        """A read-only token writes nothing: refused on a route that is not read-only (its cursor writes) or
        on a write tool of the MCP server (which says so in the context)."""
        writes = request.env.context.get('texo_write_tool')
        if writes is None:
            writes = not request.env.cr.readonly
        if writes and self.env['res.users.apikeys']._texo_request_read_only():
            raise AccessError(_("This token is read-only: it reads the memory and never writes."))

    def _texo_check_rate(self):
        """At most texo.rate_limit_per_minute requests per minute per person, counted in this process: a
        runaway agent, not a measure of fairness between processes."""
        limit = self.env['ir.config_parameter'].sudo().get_int(PARAM_RATE_LIMIT, DEFAULT_RATE_LIMIT)
        if limit <= 0:
            return
        now = time.monotonic()
        with _requests_lock:
            window = _requests[self.id]
            while window and window[0] < now - 60:
                window.popleft()
            if len(window) >= limit:
                raise TooManyRequests(_("More than %s requests in a minute: wait, then go on.", limit))
            window.append(now)

    def _texo_touch(self):
        now = fields.Datetime.now()
        for user in self:
            if not user.texo_last_seen or now - user.texo_last_seen > LAST_SEEN_RESOLUTION:
                user.texo_last_seen = now
