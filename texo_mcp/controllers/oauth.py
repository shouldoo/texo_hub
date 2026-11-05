# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from urllib.parse import urlencode, urlsplit

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from ..models.oauth import SCOPE

MCP_PATH = '/texo/mcp'
METADATA_RESOURCE = '/.well-known/oauth-protected-resource'


def base_url():
    """The address the client used to reach the hub: the issuer and the resource are on it."""
    return request.httprequest.host_url.rstrip('/')


def resource_metadata_url():
    return base_url() + METADATA_RESOURCE + MCP_PATH


class TexoOauthController(http.Controller):
    """The hub as the OAuth 2.1 authorization server of its own MCP endpoint, as the MCP
    authorization specification asks: discovery (RFC 9728, RFC 8414), dynamic registration
    of public clients (RFC 7591), the authorization code with PKCE S256 only, the consent of
    the person logged in to Odoo, refresh tokens that rotate. The access token is an API key
    of the hub scope, one hour: the endpoint and the routes accept it as any other token.

    sudo on the OAuth records: registration and token exchange are unauthenticated by
    design (the client has no account), and the records hold only hashes and ids."""

    def _json(self, body, status=200):
        response = request.make_json_response(body, status=status)
        response.headers['Cache-Control'] = 'no-store'
        return response

    def _error(self, error, description, status=400):
        return self._json({'error': error, 'error_description': description}, status=status)

    # -- discovery ---------------------------------------------------------------
    @http.route([METADATA_RESOURCE, METADATA_RESOURCE + MCP_PATH], type='http', auth='none', methods=['GET'],
                save_session=False)
    def protected_resource(self):
        return self._json({'resource': base_url() + MCP_PATH, 'authorization_servers': [base_url()],
                           'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header']})

    @http.route(['/.well-known/oauth-authorization-server', '/.well-known/oauth-authorization-server' + MCP_PATH],
                type='http', auth='none', methods=['GET'], save_session=False)
    def authorization_server(self):
        base = base_url()
        return self._json({
            'issuer': base,
            'authorization_endpoint': base + '/texo/oauth/authorize',
            'token_endpoint': base + '/texo/oauth/token',
            'registration_endpoint': base + '/texo/oauth/register',
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'code_challenge_methods_supported': ['S256'],
            'token_endpoint_auth_methods_supported': ['none'],
            'scopes_supported': [SCOPE],
        })

    # -- registration --------------------------------------------------------------
    @http.route('/texo/oauth/register', type='http', auth='none', methods=['POST'], csrf=False,
                save_session=False, readonly=False)
    def register(self):
        try:
            body = json.loads(request.httprequest.get_data() or b'{}')
            client = request.env['texo.oauth.client'].sudo()._register_client(
                body.get('client_name'), body.get('redirect_uris'))
        except (ValueError, AttributeError):
            return self._error('invalid_client_metadata', "The body is a JSON object.")
        except (UserError, ValidationError) as error:
            return self._error('invalid_redirect_uri', str(error.args[0]))
        return self._json({'client_id': client.client_id, 'client_name': client.name,
                           'redirect_uris': client.redirect_uris.split("\n"), 'token_endpoint_auth_method': 'none',
                           'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']},
                          status=201)

    # -- the consent of the person -------------------------------------------------------
    def _client(self, client_id):
        return request.env['texo.oauth.client'].sudo().search([('client_id', '=', client_id or '')], limit=1)

    def _no_frame(self, response):
        """The consent is never shown inside another site, where a click could be stolen."""
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
        return response

    def _redirect(self, uri, **params):
        separator = '&' if urlsplit(uri).query else '?'
        return request.redirect(uri + separator + urlencode({k: v for k, v in params.items() if v}), local=False)

    @http.route('/texo/oauth/authorize', type='http', auth='public', methods=['GET', 'POST'],
                save_session=True, readonly=False)
    def authorize(self, client_id=None, redirect_uri=None, response_type=None, code_challenge=None,
                  code_challenge_method=None, state=None, decision=None, **_kwargs):
        client = self._client(client_id)
        if not client or not client._allows(redirect_uri):
            # never redirect to an address the client did not register
            return request.render('texo_mcp.oauth_error', {
                'message': request.env._("Unknown client or redirect address.")}, status=400)
        if response_type != 'code' or code_challenge_method != 'S256' or not code_challenge:
            return self._redirect(redirect_uri, error='invalid_request', state=state,
                                  error_description="response_type code and a PKCE challenge S256 are required")
        user = request.env.user
        if request.env.user._is_public():
            return request.redirect('/web/login?' + urlencode({'redirect': request.httprequest.full_path}))
        if not user._texo_role():
            return request.render('texo_mcp.oauth_error', {
                'message': request.env._("You have no Texo role: ask an administrator.")}, status=403)
        if request.httprequest.method == 'GET':
            return self._no_frame(request.render('texo_mcp.oauth_consent', {
                'client': client, 'user': user, 'params': {
                    'client_id': client_id, 'redirect_uri': redirect_uri, 'response_type': response_type,
                    'code_challenge': code_challenge, 'code_challenge_method': code_challenge_method,
                    'state': state or ''}}))
        if decision != 'allow':
            return self._redirect(redirect_uri, error='access_denied', state=state)
        code = request.env['texo.oauth.code'].sudo()._issue(client, user, redirect_uri, code_challenge)
        return self._redirect(redirect_uri, code=code, state=state)

    # -- the tokens --------------------------------------------------------------------
    @http.route('/texo/oauth/token', type='http', auth='none', methods=['POST'], csrf=False,
                save_session=False, readonly=False)
    def token(self, grant_type=None, code=None, redirect_uri=None, client_id=None, code_verifier=None,
              refresh_token=None, **_kwargs):
        client = self._client(client_id)
        if not client:
            return self._error('invalid_client', "Unknown client.", status=401)
        Grant = request.env['texo.oauth.grant'].sudo()
        try:
            if grant_type == 'authorization_code':
                user = request.env['texo.oauth.code'].sudo()._redeem(code, client, redirect_uri, code_verifier)
                if not user:
                    return self._error('invalid_grant', "The code is unknown, used, expired or does not match.")
                tokens = Grant._issue(client, user)
            elif grant_type == 'refresh_token':
                tokens = Grant._refresh(refresh_token, client)
                if not tokens:
                    return self._error('invalid_grant', "The refresh token is unknown, used, expired or revoked.")
            else:
                return self._error('unsupported_grant_type', "authorization_code or refresh_token.")
        except (UserError, ValidationError) as error:
            # the hub refused the key: no role any more, a duration beyond the maximum
            return self._error('invalid_grant', str(error.args[0]))
        return self._json(tokens)
