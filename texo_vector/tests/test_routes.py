# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from odoo.addons.texo_memory.tests.common import clear_home


@tagged('post_install', '-at_install')
class TestVectorRoutes(HttpCase):
    """The search route takes the mode; a wrong one is refused as the other arguments are."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        clear_home(cls.env)
        cls.lead = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Lead', 'login': 'chv_http_lead', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id),
                          Command.link(cls.env.ref('project.group_project_user').id)]})
        cls.env['memory.note'].create({'name': 'Resi', 'body': 'I resi dei clienti tornano con una rotta dedicata.',
                                       'kind': 'fact', 'state': 'active'})

    def _post(self, route, payload):
        key = self.env['res.users.apikeys'].with_user(self.lead)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open(f'/texo/v1/memory/{route}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    def test_search_takes_the_mode(self):
        answer = self._post('search', {'query': 'resi', 'scope': 'facts', 'mode': 'lexical'})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual([r['title'] for r in answer.json()['results']], ['Resi'])
        with mute_logger('odoo.http'):
            self.assertEqual(self._post('search', {'query': 'resi', 'mode': 'magic'}).status_code, 422)
