# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import datetime, timedelta

from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestHubTokens(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.member = Users.create({
            'name': 'Hub Member', 'login': 'hub_member',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id)],
        })
        cls.lead = Users.create({
            'name': 'Hub Lead', 'login': 'hub_lead',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id)],
        })
        cls.outsider = Users.create({
            'name': 'No Hub', 'login': 'no_hub',
            'group_ids': [Command.link(cls.env.ref('base.group_user').id)],
        })

    def _generate(self, user, days, scope='texo'):
        expiration = datetime.now() + timedelta(days=days) if days is not None else None
        return self.env['res.users.apikeys'].with_user(user)._generate(scope, 'test', expiration)

    def test_scope_offered_in_key_wizard(self):
        scopes = self.env['res.users.apikeys.description']._fields['scope'].get_values(self.env)
        self.assertIn('texo', scopes)

    def test_roles(self):
        self.assertEqual(self.member._texo_role(), 'member')
        self.assertEqual(self.lead._texo_role(), 'lead')
        self.assertEqual(self.env.ref('base.user_admin')._texo_role(), 'admin')
        self.assertFalse(self.outsider._texo_role())

    def test_hub_roles_make_regular_users(self):
        # Hub groups are not light groups: Odoo makes them imply the regular-user
        # marker, whose API key duration (90 days) allows the hub token maximum.
        regular = self.env.ref('base.group_user_regular')
        for user in (self.member, self.lead):
            self.assertIn(regular, user.all_group_ids)
        self.assertNotIn(regular, self.outsider.all_group_ids)

    def test_hub_key_only_valid_for_its_scope(self):
        key = self._generate(self.member, 30)
        Apikeys = self.env['res.users.apikeys']
        self.assertEqual(Apikeys._check_credentials(scope='texo', key=key), self.member.id)
        self.assertFalse(Apikeys._check_credentials(scope='rpc', key=key))

    def test_hub_key_requires_expiration_within_max(self):
        with self.assertRaises(ValidationError):
            self._generate(self.member, 365)
        with self.assertRaises(ValidationError):
            self._generate(self.member, None)
        self.env['ir.config_parameter'].sudo().set_int('texo.token_max_days', 7)
        with self.assertRaises(ValidationError):
            self._generate(self.member, 30)

    def test_admin_cannot_create_persistent_hub_key(self):
        with self.assertRaises(ValidationError):
            self._generate(self.env.ref('base.user_admin'), None)

    def test_user_without_role_cannot_create_hub_key(self):
        with self.assertRaises(UserError):
            self._generate(self.outsider, 30)

    def test_rpc_keys_unaffected(self):
        # A plain internal user may create keys of one day at most (base group durations)
        key = self._generate(self.outsider, 1, scope='rpc')
        self.assertEqual(self.env['res.users.apikeys']._check_credentials(scope='rpc', key=key), self.outsider.id)


@tagged('post_install', '-at_install')
class TestReadOnlyTokensAndSecrets(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Hub Member RO', 'login': 'hub_member_ro',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id)]})

    def test_a_read_only_token_is_a_flag_of_the_key(self):
        Keys = self.env['res.users.apikeys'].with_user(self.member)
        expiration = datetime.now() + timedelta(days=1)
        Keys._generate('texo', 'reads and writes', expiration)
        Keys.with_context(texo_read_only=True)._generate('texo', 'reads', expiration)
        keys = self.env['res.users.apikeys'].sudo().search([('user_id', '=', self.member.id)], order='id')
        self.assertEqual([(k.name, k.texo_read_only) for k in keys], [('reads and writes', False), ('reads', True)])
        self.assertFalse(self.env['res.users.apikeys']._texo_request_read_only(), "no request: no token")

    def test_what_looks_like_a_credential(self):
        from ..models.secrets import credential_reason
        for text, what in (("TEXO_HUB_TOKEN=4f2a9c1b8d7e6f5a", "a named key, token or password"),
                           ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz", "a bearer token"),
                           ("use sk-ABCDEFGHIJKLMNOPQRST here", "an API key"),
                           ("AKIAABCDEFGHIJKLMNOP", "an AWS access key"),
                           ("-----BEGIN RSA PRIVATE KEY-----", "a private key"),
                           ("the token expires in 90 days", None),
                           ("password policy: twelve characters", None)):
            found = credential_reason(text)
            self.assertEqual(str(found) if found is not None else None, what, text)
