# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
import re

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from odoo.addons.texo import okf
from odoo.addons.texo.controllers.main import TexoController
from odoo.addons.texo_memory.controllers.main import TexoMemoryController
from odoo.addons.texo_project.controllers.main import TexoProjectController

from .oauth import resource_metadata_url
from .tools import TOOLS

PROTOCOL_VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')
# JSON-RPC error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
NO_ROLE = -32001
NEEDS_CONFIRMATION = ("Needs confirmation: show the person what you are about to write and call again with "
                      "confirm: true after their yes. Nothing was written.")
# What a route raises for the person: the message goes back to the agent as the result of the tool.
TOOL_ERRORS = (AccessError, MissingError, UserError, ValidationError, NotFound, ValueError)


class TexoMcpController(http.Controller):
    """The memory of the hub as a remote MCP server (Streamable HTTP, JSON answers).

    One POST per JSON-RPC message, with the person's Texo token as bearer, the same
    as the routes: Odoo checks the token, the tools run as the person, with Odoo's access
    rules. The instructions of the server are the rules of the session; every tool calls the
    controller method of its route; a write needs confirm true, after the person's yes.
    """

    def _controllers(self):
        controllers = {'hub': TexoController(), 'project': TexoProjectController(),
                       'memory': TexoMemoryController()}
        if self._has_timesheet():
            from odoo.addons.texo_timesheet.controllers.main import (  # noqa: PLC0415
                TexoTimesheetController,
            )
            controllers['timesheet'] = TexoTimesheetController()
        if self._has_sources():
            from odoo.addons.texo_sources.controllers.main import (  # noqa: PLC0415
                TexoSourcesController,
            )
            controllers['sources'] = TexoSourcesController()
        return controllers

    def _has_timesheet(self):
        """The hours come from texo_timesheet, which is optional."""
        return hasattr(request.env['project.task'], '_texo_log_time')

    def _has_sources(self):
        """The external sources come from texo_sources, which is optional."""
        return 'memory.source.item' in request.env

    def _tools(self):
        """The tools of the modules installed; a read-only token sees the read tools only."""
        optional = {'timesheet': self._has_timesheet(), 'sources': self._has_sources()}
        read_only = request.env['res.users.apikeys']._texo_request_read_only()
        return [t for t in TOOLS if optional.get(t['route'][0], True) and not (read_only and t['write'])]

    def _authenticate(self):
        """The person behind the bearer token (an API key of the hub scope: a personal one, or
        the access token of OAuth), or None. auth='bearer' of Odoo would do the same, but its
        401 cannot say where the OAuth metadata is, which an MCP client needs to log in."""
        header = request.httprequest.headers.get('Authorization') or ''
        match = re.match(r'^bearer\s+(.+)$', header, re.IGNORECASE)
        uid = match and request.env['res.users.apikeys']._check_credentials(scope='texo', key=match.group(1))
        if uid:
            request.update_env(user=uid)
        return uid

    def _unauthorized(self):
        response = request.make_json_response(
            {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32000, 'message': "Unauthorized: a Texo token is needed"}},
            status=401)
        response.headers['WWW-Authenticate'] = f'Bearer resource_metadata="{resource_metadata_url()}"'
        return response

    # readonly=False: a route of auth none gets a read-only cursor by default, and a tool writes
    @http.route('/texo/mcp', type='http', auth='none', methods=['POST'], csrf=False, save_session=False,
                readonly=False)
    def mcp(self):
        if not self._authenticate():
            return self._unauthorized()
        try:
            message = json.loads(request.httprequest.get_data() or b'')
        except ValueError:
            return self._answer(None, error=(PARSE_ERROR, "Parse error"))
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not message.get('method'):
            return self._answer(message.get('id') if isinstance(message, dict) else None,
                                error=(INVALID_REQUEST, "One JSON-RPC 2.0 message per request"))
        if 'id' not in message:
            # a notification (initialized, cancelled): nothing to answer
            return request.make_response('', status=202)
        rid, method, params = message['id'], message['method'], message.get('params') or {}
        # this endpoint writes (readonly=False): the role check of a route called here learns from the context
        # whether the tool writes; the handshake and the listing never do
        request.update_context(texo_write_tool=False)
        role = request.env.user._texo_role()
        if not role:
            return self._answer(rid, error=(NO_ROLE, "You have no Texo role."))
        if method == 'initialize':
            return self._answer(rid, self._initialize(params))
        if method == 'ping':
            return self._answer(rid, {})
        if method == 'tools/list':
            return self._answer(rid, {'tools': [{k: t[k] for k in ('name', 'description', 'inputSchema')}
                                                for t in self._tools()]})
        if method == 'tools/call':
            return self._answer(rid, self._call(params.get('name'), params.get('arguments') or {}))
        return self._answer(rid, error=(METHOD_NOT_FOUND, f"Method not found: {method}"))

    def _answer(self, rid, result=None, error=None):
        body = {'jsonrpc': '2.0', 'id': rid}
        if error:
            body['error'] = {'code': error[0], 'message': error[1]}
        else:
            body['result'] = result
        return request.make_json_response(body)

    def _initialize(self, params):
        """The rules of the session are the instructions of the server: every session starts with them."""
        asked = params.get('protocolVersion')
        rules = self._controllers()['memory'].rules()
        text = f"{rules['rules']}\n\nMy role in the hub: {rules['role']}."
        if rules.get('activities'):
            text += "\n\nActivities of the organisation (the activity of context): " + "; ".join(
                f"{a['code']} ({a['description'] or a['name']})" for a in rules['activities']) + "."
        if rules.get('sections'):
            text += "\n\nSections of the organisation (the section of a note): " + "; ".join(
                f"{s['code']} ({s['description'] or s['name']})" for s in rules['sections']) + "."
        # sudo: the version of an installed module, which a hub user may not read
        version = request.env['ir.module.module'].sudo().search([('name', '=', 'texo_mcp')], limit=1).latest_version
        return {'protocolVersion': asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                'capabilities': {'tools': {}}, 'serverInfo': {'name': 'texo', 'version': version or ''},
                'instructions': text}

    def _call(self, name, arguments):
        """Run one tool as the person; a refusal of the route comes back as an error result,
        and what the tool wrote before it is rolled back."""
        spec = next((t for t in self._tools() if t['name'] == name), None)
        if not spec:
            if any(t['name'] == name for t in TOOLS):
                return self._result(f"The tool {name} writes, and this token is read-only.", error=True)
            return self._result(f"Unknown tool {name}.", error=True)
        if not isinstance(arguments, dict):
            return self._result("The arguments of a tool are an object.", error=True)
        if spec['write'] and arguments.get('confirm') is not True:
            return self._result(NEEDS_CONFIRMATION)
        schema = spec['inputSchema']
        missing = [key for key in schema.get('required', []) if key != 'confirm' and arguments.get(key) in (None, '')]
        if missing:
            return self._result(f"Missing arguments: {', '.join(missing)}.", error=True)
        # only the arguments the tool declares reach the route
        values = {key: value for key, value in arguments.items()
                  if key in schema['properties'] and key != 'confirm' and value is not None}
        controller, method = spec['route']
        # the route runs on the writable cursor of this endpoint: the role check learns from the context
        # whether the tool writes, so a read-only token is refused on a write tool only
        request.update_context(texo_write_tool=spec['write'])
        try:
            with request.env.cr.savepoint():
                data = getattr(self._controllers()[controller], method)(**values)
        except TOOL_ERRORS as error:
            message = error.args[0] if error.args else str(error)
            return self._result(str(message), error=True)
        if isinstance(data, dict) and data.get('format') == 'okf':
            # an OKF bundle is markdown: the agent reads its files as they are, not escaped in JSON
            return self._result(okf.render(data))
        return self._result(json.dumps(data, ensure_ascii=False, default=str))

    def _result(self, text, error=False):
        return {'content': [{'type': 'text', 'text': text}], 'isError': error}
