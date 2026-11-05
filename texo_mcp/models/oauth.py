# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import base64
import hashlib
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from odoo import api, fields, models
from odoo.exceptions import UserError

SCOPE = 'texo'
CODE_MINUTES = 10
ACCESS_HOURS = 1
REFRESH_DAYS = 30
MAX_REDIRECTS = 10


def digest(secret):
    """What is stored of a code or a refresh token: its sha256, never the secret."""
    return hashlib.sha256(secret.encode()).hexdigest()


def pkce_challenge(verifier):
    """The S256 challenge of a PKCE verifier (RFC 7636)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()


class TexoOauthClient(models.Model):
    """An MCP client registered by itself (RFC 7591): a public client, with the addresses
    the person is sent back to after the consent. Registering gives no access: the person
    still logs in to Odoo and agrees."""
    _name = 'texo.oauth.client'
    _description = "Texo OAuth Client"
    _order = 'id desc'

    name = fields.Char(required=True)
    client_id = fields.Char(string="Client ID", required=True, readonly=True, index=True, copy=False)
    redirect_uris = fields.Text(required=True, help="One address per line.")
    grant_ids = fields.One2many('texo.oauth.grant', 'client_id', string="Grants")

    _client_id_unique = models.Constraint('UNIQUE(client_id)', "The client ID must be unique.")

    @api.model
    def _check_redirect_uri(self, uri):
        """A redirect is https, or http on this machine only (a local client)."""
        parts = urlsplit(uri or '')
        local = parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')
        if not (parts.scheme == 'https' or local) or not parts.netloc or parts.fragment:
            raise UserError(self.env._("A redirect URI is https, or http on localhost, without a fragment: %s", uri))
        return uri

    @api.model
    def _register_client(self, name, redirect_uris):
        if not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > MAX_REDIRECTS:
            raise UserError(self.env._("redirect_uris is a list of 1 to %s addresses.", MAX_REDIRECTS))
        uris = [self._check_redirect_uri(uri) for uri in redirect_uris]
        return self.create({'name': (name or 'MCP client').strip()[:100], 'client_id': secrets.token_urlsafe(24),
                            'redirect_uris': "\n".join(uris)})

    def _allows(self, uri):
        self.ensure_one()
        return uri in (self.redirect_uris or '').split("\n")


class TexoOauthCode(models.Model):
    """An authorization code: one use, ten minutes, bound to its client, its redirect, the
    person who agreed and the PKCE challenge of the client."""
    _name = 'texo.oauth.code'
    _description = "Texo OAuth Code"

    code_hash = fields.Char(required=True, index=True)
    client_id = fields.Many2one('texo.oauth.client', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade')
    redirect_uri = fields.Char(required=True)
    code_challenge = fields.Char(required=True)
    expires = fields.Datetime(required=True)
    used = fields.Boolean()

    @api.model
    def _issue(self, client, user, redirect_uri, code_challenge):
        code = secrets.token_urlsafe(32)
        self.create({'code_hash': digest(code), 'client_id': client.id, 'user_id': user.id,
                     'redirect_uri': redirect_uri, 'code_challenge': code_challenge,
                     'expires': fields.Datetime.now() + timedelta(minutes=CODE_MINUTES)})
        return code

    @api.model
    def _redeem(self, code, client, redirect_uri, verifier):
        """The code, once: the same client, the same redirect, the verifier of the challenge."""
        record = self.search([('code_hash', '=', digest(code or ''))], limit=1)
        if (not record or record.used or record.expires < fields.Datetime.now() or record.client_id != client
                or record.redirect_uri != redirect_uri or not verifier
                or pkce_challenge(verifier) != record.code_challenge):
            if record:
                record.used = True
            return None
        record.used = True
        return record.user_id


class TexoOauthGrant(models.Model):
    """What a person granted to a client: the current access token (an API key of the hub
    scope, one hour) and the refresh token that renews it (thirty days, a new one at every
    use). Revoking a grant removes its key."""
    _name = 'texo.oauth.grant'
    _description = "Texo OAuth Grant"
    _order = 'id desc'

    client_id = fields.Many2one('texo.oauth.client', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    refresh_hash = fields.Char(required=True, index=True)
    key_name = fields.Char(required=True, help="The name of the API key of the current access token.")
    expires = fields.Datetime(required=True)
    revoked = fields.Boolean()

    def _keys(self):
        # sudo: the API keys of the grant, which the person who agreed owns
        return self.env['res.users.apikeys'].sudo().search(
            [('user_id', 'in', self.user_id.ids), ('name', 'in', self.mapped('key_name')), ('scope', '=', SCOPE)])

    def _revoke(self):
        # _remove, not unlink: it also clears the cache of the keys Odoo checks
        self._keys()._remove()
        self.write({'revoked': True})

    def action_revoke(self):
        """An administrator cuts a client off: its key goes now, its refresh token no longer works."""
        self.filtered(lambda g: not g.revoked)._revoke()

    @api.model
    def _issue(self, client, user):
        """A new access token and a new refresh token for the person, as the person: the hub
        checks the role and the duration of the key."""
        refresh = secrets.token_urlsafe(32)
        key_name = f"MCP {client.name} ({secrets.token_hex(4)})"
        access = self.env['res.users.apikeys'].with_user(user)._generate(
            SCOPE, key_name, fields.Datetime.now() + timedelta(hours=ACCESS_HOURS))
        self.create({'client_id': client.id, 'user_id': user.id, 'refresh_hash': digest(refresh), 'key_name': key_name,
                     'expires': fields.Datetime.now() + timedelta(days=REFRESH_DAYS)})
        return {'access_token': access, 'token_type': 'Bearer', 'expires_in': ACCESS_HOURS * 3600,
                'refresh_token': refresh, 'scope': SCOPE}

    @api.model
    def _refresh(self, refresh, client):
        """A refresh token, once: the grant is revoked with its key and a new one is issued."""
        grant = self.search([('refresh_hash', '=', digest(refresh or ''))], limit=1)
        if not grant or grant.revoked or grant.expires < fields.Datetime.now() or grant.client_id != client:
            return None
        user = grant.user_id
        grant._revoke()
        if not user.active or not user._texo_role():
            return None
        return self._issue(client, user)

    @api.autovacuum
    def _gc_expired(self):
        """The codes and the grants no longer of use, with their keys."""
        now = fields.Datetime.now()
        self.env['texo.oauth.code'].search(['|', ('used', '=', True), ('expires', '<', now)]).unlink()
        expired = self.search(['|', ('revoked', '=', True), ('expires', '<', now)])
        expired.filtered(lambda g: not g.revoked)._revoke()
        expired.unlink()
