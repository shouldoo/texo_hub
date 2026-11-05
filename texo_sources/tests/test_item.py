# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import SourcesCase


@tagged('post_install', '-at_install')
class TestItem(SourcesCase):
    """The life of a card: triage, writing, approval of the cards that name persons, the cards
    approved that only a lead changes, the quotes that stay short, who sees what."""

    def candidate(self, url='https://news.example.com/a', **vals):
        return self.env['memory.source.item'].create(dict(
            {'channel_id': self.channel.id, 'url': url, 'title': 'The council meets'}, **vals))

    def test_a_card_that_names_nobody_is_active_at_once(self):
        item = self.candidate().with_user(self.member)
        item.action_keep()
        self.assertEqual(item.state, 'todo')
        with self.assertRaises(UserError, msg="no abstract, no card"):
            item.action_submit()
        item.write({'abstract': 'The council meets on Monday on the budget.', 'theme_ids': [Command.link(self.theme.id)]})
        item.action_submit()
        self.assertEqual((item.state, item.needs_approval), ('active', False))

    def test_a_card_that_names_persons_waits_for_a_lead(self):
        item = self.candidate().with_user(self.member)
        item.action_keep()
        item.write({'abstract': 'The mayor answers the opposition.', 'person_ids': [Command.link(self.person.id)]})
        item.action_submit()
        self.assertEqual((item.state, item.needs_approval), ('to_approve', True))
        with self.assertRaises(AccessError):
            item.action_approve()
        with self.assertRaises(AccessError):
            item.write({'state': 'active'})
        item.with_user(self.lead).action_approve()
        self.assertEqual((item.state, item.approved_by_id), ('active', self.lead))
        with self.assertRaises(AccessError, msg="an approved card is changed by a lead"):
            item.write({'abstract': 'Something else.'})
        item.write({'triage_note': 'still relevant'})  # not the content
        item.with_user(self.lead).action_send_back()
        self.assertEqual((item.state, item.approved_on), ('todo', False))
        item.write({'abstract': 'The mayor answers the opposition on the budget.'})

    def test_triage(self):
        kept, dropped = self.candidate(), self.candidate('https://news.example.com/b')
        (kept | dropped).with_user(self.member).action_keep()
        dropped.with_user(self.member).action_discard()
        self.assertEqual((kept.state, dropped.state), ('todo', 'discarded'))
        dropped.with_user(self.member).action_keep()
        self.assertEqual(dropped.state, 'todo', "a discarded candidate can be kept after all")

    def test_quotes_stay_short_and_a_link_is_there_once(self):
        with self.assertRaises(UserError):
            self.candidate(quotes='«' + 'x' * 700 + '»')
        self.candidate(quotes='«We will not get there», the mayor')
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            self.candidate()

    def test_a_pasted_link_finds_its_channel(self):
        Item = self.env['memory.source.item'].with_user(self.member)
        item = Item._from_link('https://www.news.example.com/2026/11/ospedale', 'The new hospital')
        self.assertEqual((item.channel_id, item.state, item.title), (self.channel, 'candidate', 'The new hospital'))
        self.assertEqual(Item._from_link('https://www.news.example.com/2026/11/ospedale'), item, "once")
        with self.assertRaises(UserError, msg="a site that is no channel: add the channel first"):
            Item._from_link('https://elsewhere.example.org/x')

    def test_who_sees_the_channels_and_cards_of_a_project(self):
        channel = self.env['memory.source.channel'].create({
            'name': 'Warehouse suppliers news', 'project_id': self.project.id, 'website': 'https://suppliers.example.com'})
        item = self.env['memory.source.item'].create({
            'channel_id': channel.id, 'url': 'https://suppliers.example.com/x', 'title': 'A supplier closes'})
        Channel = self.env['memory.source.channel']
        self.assertIn(channel, Channel.with_user(self.member).search([]))
        self.assertNotIn(channel, Channel.with_user(self.outsider).search([]),
                         "a followers-only project: its channels do not exist for who is not on it")
        self.assertFalse(self.env['memory.source.item'].with_user(self.outsider).search([('id', '=', item.id)]))
        self.assertIn(self.channel, Channel.with_user(self.outsider).search([]), "the organisation's are for everyone")
        with self.assertRaises(AccessError, msg="the channels are a lead's decision"):
            Channel.with_user(self.member).create({'name': 'Mine'})
