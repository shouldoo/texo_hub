# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
import re
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from ..models.oauth import pkce_challenge

REDIRECT = 'http://localhost:3333/callback'


@tagged('post_install', '-at_install')
class TestOauth(HttpCase):
    """The MCP endpoint behind OAuth 2.1: discovery, registration, the consent of the person,
    the code with PKCE, tokens that are API keys of the hub and refresh tokens that rotate."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        project_user = Command.link(cls.env.ref('project.group_project_user').id)
        cls.lead = Users.create({
            'name': 'OAuth Lead', 'login': 'choauth_lead', 'password': 'choauth_lead', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id), project_user]})
        cls.norole = Users.create({'name': 'No role', 'login': 'choauth_norole', 'password': 'choauth_norole',
                                   'lang': 'en_US', 'group_ids': [project_user]})

    def post_json(self, url, body, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = f'Bearer {token}'
        return self.url_open(url, data=json.dumps(body), headers=headers)

    def mcp(self, token):
        return self.post_json('/texo/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}, token)

    def register(self):
        answer = self.post_json('/texo/oauth/register', {'client_name': 'Test client', 'redirect_uris': [REDIRECT]})
        self.assertEqual(answer.status_code, 201)
        return answer.json()['client_id']

    def authorize(self, client_id, challenge, decision='allow', login='choauth_lead'):
        self.authenticate(login, login)
        params = {'client_id': client_id, 'redirect_uri': REDIRECT, 'response_type': 'code', 'state': 'xyz',
                  'code_challenge': challenge, 'code_challenge_method': 'S256'}
        page = self.url_open('/texo/oauth/authorize?' + urlencode(params))
        if page.status_code != 200:
            return page
        self.assertIn('Test client', page.text)
        self.assertEqual(page.headers['X-Frame-Options'], 'DENY')
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        return self.url_open('/texo/oauth/authorize', data=dict(params, csrf_token=csrf, decision=decision),
                             allow_redirects=False)

    def token(self, **form):
        return self.url_open('/texo/oauth/token', data=form)

    def test_discovery_and_the_401_that_points_to_it(self):
        resource = self.url_open('/.well-known/oauth-protected-resource/texo/mcp').json()
        self.assertTrue(resource['resource'].endswith('/texo/mcp'))
        server = self.url_open('/.well-known/oauth-authorization-server').json()
        self.assertEqual(server['issuer'], resource['authorization_servers'][0])
        self.assertEqual(server['code_challenge_methods_supported'], ['S256'])
        unauthorized = self.mcp(None)
        self.assertEqual(unauthorized.status_code, 401)
        self.assertIn('resource_metadata="', unauthorized.headers['WWW-Authenticate'])
        self.assertIn('/.well-known/oauth-protected-resource/texo/mcp', unauthorized.headers['WWW-Authenticate'])
        bad = self.post_json('/texo/oauth/register', {'client_name': 'Evil', 'redirect_uris': ['http://evil.example/cb']})
        self.assertEqual((bad.status_code, bad.json()['error']), (400, 'invalid_redirect_uri'))

    def test_the_whole_flow(self):
        client_id = self.register()
        verifier = secrets.token_urlsafe(48)
        answer = self.authorize(client_id, pkce_challenge(verifier))
        self.assertEqual(answer.status_code, 303)
        location = urlsplit(answer.headers['Location'])
        self.assertEqual(f'{location.scheme}://{location.netloc}{location.path}', REDIRECT)
        query = parse_qs(location.query)
        self.assertEqual(query['state'], ['xyz'])
        code = query['code'][0]
        form = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': REDIRECT, 'client_id': client_id}
        self.assertEqual(self.token(**form, code_verifier='wrong').json()['error'], 'invalid_grant',
                         "a wrong verifier burns the code")
        verifier = secrets.token_urlsafe(48)
        code = parse_qs(urlsplit(self.authorize(client_id, pkce_challenge(verifier)).headers['Location']).query)['code'][0]
        tokens = self.token(**dict(form, code=code), code_verifier=verifier).json()
        self.assertEqual((tokens['token_type'], tokens['expires_in'], tokens['scope']), ('Bearer', 3600, 'texo'))
        self.assertEqual(self.token(**dict(form, code=code), code_verifier=verifier).json()['error'], 'invalid_grant',
                         "a code works once")
        tools = self.mcp(tokens['access_token']).json()['result']['tools']
        self.assertIn('context', [t['name'] for t in tools])
        renewed = self.token(grant_type='refresh_token', refresh_token=tokens['refresh_token'], client_id=client_id).json()
        self.assertEqual(self.mcp(renewed['access_token']).status_code, 200)
        self.assertEqual(self.mcp(tokens['access_token']).status_code, 401, "the old access token is revoked")
        self.assertEqual(self.token(grant_type='refresh_token', refresh_token=tokens['refresh_token'],
                                    client_id=client_id).json()['error'], 'invalid_grant', "a refresh token works once")
        # an administrator cuts the client off
        grant = self.env['texo.oauth.grant'].search([('user_id', '=', self.lead.id), ('revoked', '=', False)])
        grant.action_revoke()
        self.assertEqual(self.mcp(renewed['access_token']).status_code, 401)
        self.assertEqual(self.token(grant_type='refresh_token', refresh_token=renewed['refresh_token'],
                                    client_id=client_id).json()['error'], 'invalid_grant')

    def test_the_person_decides(self):
        client_id = self.register()
        denied = self.authorize(client_id, pkce_challenge('v' * 50), decision='deny')
        self.assertEqual(parse_qs(urlsplit(denied.headers['Location']).query)['error'], ['access_denied'])
        self.assertEqual(self.authorize(client_id, pkce_challenge('v' * 50), login='choauth_norole').status_code, 403)
        self.authenticate('choauth_lead', 'choauth_lead')
        unknown = self.url_open('/texo/oauth/authorize?' + urlencode(
            {'client_id': client_id, 'redirect_uri': 'https://other.example/cb', 'response_type': 'code',
             'code_challenge': 'x', 'code_challenge_method': 'S256'}))
        self.assertEqual(unknown.status_code, 400, "never sent to an address the client did not register")
        no_pkce = self.url_open('/texo/oauth/authorize?' + urlencode(
            {'client_id': client_id, 'redirect_uri': REDIRECT, 'response_type': 'code'}), allow_redirects=False)
        self.assertEqual(parse_qs(urlsplit(no_pkce.headers['Location']).query)['error'], ['invalid_request'])
