# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from werkzeug.exceptions import Forbidden

from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

# Every agent route: the user's Texo token as bearer, never a generic rpc key.
HUB_ROUTE = {'type': 'json2', 'auth': 'bearer', 'bearer_scope': 'texo',
             'methods': ['POST'], 'save_session': False}
# How a reading route answers: json, the hub's own fields, or okf, the files of an Open
# Knowledge Format bundle (texo/okf.py).
FORMATS = ('json', 'okf')


def as_okf(value):
    """Whether a route is asked in OKF; a format other than json or okf is refused."""
    value = value or 'json'
    if value not in FORMATS:
        raise UserError(request.env._("The format is json or okf."))
    return value == 'okf'


class TexoController(http.Controller):

    @http.route('/texo/v1/whoami', **HUB_ROUTE)
    def whoami(self):
        """Identity behind a Texo token, called by the hub gateway.

        Odoo validates the token itself (scope, expiry, active user): an invalid
        token never reaches this method and gets a 401.
        """
        user = request.env.user
        role = user._texo_check_role()
        # sudo: users cannot write this technical field on their own record
        user.sudo()._texo_touch()
        return {
            'uid': user.id,
            'login': user.login,
            'name': user.name,
            'role': role,
        }

    # -- the metrics of the hub, for a scraper ------------------------------------
    @http.route('/texo/metrics', type='http', auth='bearer', bearer_scope='texo', methods=['GET'],
                save_session=False, readonly=True)
    def metrics(self):
        """The gauges of the hub in the Prometheus exposition format, for an administrator's token:
        counts and timestamps, never a text of the memory."""
        if request.env.user._texo_role() != 'admin':
            raise Forbidden("Only a Texo administrator reads the metrics.")
        return request.make_response(request.env['texo.metrics']._render(),
                                     headers=[('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')])

    # -- the configuration of the organisation, for the texo CLI ----------------
    @http.route('/texo/v1/config', readonly=True, **HUB_ROUTE)
    def config(self, company_id=None):
        """The skill packs and the threads the organisation mounts, for every role."""
        return request.env['texo.config']._agent_config(company_id)

    @http.route('/texo/v1/admin/config', **HUB_ROUTE)
    def set_config(self, packs=None, threads=None, slug=None, company_id=None, apply=False):
        """Administrators: the configuration made to say what the payload says; a dry run without apply."""
        return request.env['texo.config']._agent_set_config(packs=packs, threads=threads, slug=slug,
                                                           company_id=company_id, apply=apply)

    # -- generic read-only access: the agent writes the query -----------------
    @http.route('/texo/v1/search_read', readonly=True, **HUB_ROUTE)
    def search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        request.env.user._texo_check_role()
        return request.env['texo.api']._agent_search_read(model, domain, fields, limit, offset, order)

    @http.route('/texo/v1/read_group', readonly=True, **HUB_ROUTE)
    def read_group(self, model, domain=None, groupby=None, aggregates=None, limit=None, order=None):
        request.env.user._texo_check_role()
        return request.env['texo.api']._agent_read_group(model, domain, groupby, aggregates, limit, order)

    @http.route('/texo/v1/fields', readonly=True, **HUB_ROUTE)
    def fields(self, model, query=None):
        request.env.user._texo_check_role()
        return request.env['texo.api']._agent_fields(model, query)

    @http.route('/texo/v1/models', readonly=True, **HUB_ROUTE)
    def models(self, query):
        request.env.user._texo_check_role()
        return request.env['texo.api']._agent_models(query)
