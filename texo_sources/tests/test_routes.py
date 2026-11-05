# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import json
from datetime import datetime, timedelta

from odoo import Command
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSourcesRoutes(HttpCase):
    """A card is a concept of the memory: memory/read gives it by sources/<id>, as the search names it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Member', 'login': 'chs_http_member', 'lang': 'en_US',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id)]})
        channel = cls.env['memory.source.channel'].create({
            'name': 'Local news', 'kind': 'press', 'website': 'https://news.example.com'})
        cls.card = cls.env['memory.source.item'].create({
            'channel_id': channel.id, 'url': 'https://news.example.com/card', 'title': 'The council votes',
            'state': 'active', 'abstract': 'The council approved the concession by 18 votes to 12.'})

    def _read(self, concept):
        key = self.env['res.users.apikeys'].with_user(self.member)._generate(
            'texo', 'test', datetime.now() + timedelta(days=30))
        return self.url_open('/texo/v1/memory/read', data=json.dumps({'concept': concept}), headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})

    def test_a_card_is_read_by_its_concept(self):
        answer = self._read(f'sources/{self.card.id}')
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()['abstract'], 'The council approved the concession by 18 votes to 12.')
        self.assertEqual(answer.json()['concept'], f'sources/{self.card.id}')
        with mute_logger('odoo.http'):
            missing = self._read('sources/999999')
        self.assertEqual(missing.status_code, 404)
