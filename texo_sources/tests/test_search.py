# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.tests import tagged

from .common import SourcesCase


@tagged('post_install', '-at_install')
class TestSourcesSearch(SourcesCase):
    """The active cards in the search of the memory, by their words and their labels."""

    def card(self, url, **vals):
        return self.env['memory.source.item'].create(dict(
            {'channel_id': self.channel.id, 'url': url, 'title': 'The council meets', 'state': 'active',
             'abstract': 'The council discussed the new hospital and the budget.'}, **vals))

    def search(self, query, scope='sources', user=None):
        return self.env['memory.note'].with_user(user or self.member)._agent_search(query, scope=scope, mode='lexical')

    def test_a_card_is_found_by_its_words_and_labels(self):
        card = self.card('https://news.example.com/hospital', person_ids=[Command.link(self.person.id)],
                         theme_ids=[Command.link(self.theme.id)], keywords='ospedale, sanità', event_date='2026-10-26')
        found = self.search('hospital budget')
        self.assertEqual([r['id'] for r in found], [card.id])
        entry = found[0]
        self.assertEqual((entry['source'], entry['concept'], entry['words']), (True, f'sources/{card.id}', 'all'))
        self.assertEqual((entry['channel'], entry['event_date'], entry['persons']), ('Local news', '2026-10-26',
                                                                                     ['The mayor']))
        self.assertIn('hospital', entry['snippet'])
        self.assertEqual([r['id'] for r in self.search('mayor')], [card.id], "a public person, by its label")
        self.assertEqual([r['id'] for r in self.search('sanità')], [card.id], "a keyword")
        self.assertIn(card.id, [r['id'] for r in self.search('hospital', scope='all') if r.get('source')])
        self.assertFalse([r for r in self.search('hospital', scope='facts') if r.get('source')])
        # a label renamed: the card is found by the new name
        self.person.name = 'The deputy mayor'
        self.assertEqual([r['id'] for r in self.search('deputy')], [card.id])

    def test_only_the_active_cards(self):
        candidate = self.card('https://news.example.com/candidate', state='candidate', title='Hospital candidate')
        waiting = self.card('https://news.example.com/waiting', state='to_approve', title='Hospital waiting')
        self.assertEqual(self.search('hospital'), [])
        waiting.state = 'active'
        self.assertEqual([r['id'] for r in self.search('hospital')], [waiting.id])
        waiting.state = 'archived'
        self.assertEqual(self.search('hospital'), [])
        self.assertTrue(candidate.exists())

    def test_a_card_of_a_project_only_for_who_reads_it(self):
        self.channel.project_id = self.project
        card = self.card('https://news.example.com/project')
        self.assertEqual([r['id'] for r in self.search('hospital')], [card.id])
        self.assertEqual(self.search('hospital', user=self.outsider), [])

    def test_the_search_page_has_the_cards(self):
        card = self.card('https://news.example.com/page', event_date='2026-10-26')
        search = self.env['memory.search'].with_user(self.member).create({'query': 'hospital', 'scope': 'sources',
                                                                          'mode': 'lexical'})
        search.action_search()
        line = search.line_ids
        self.assertEqual((line.res_model, line.res_id), ('memory.source.item', card.id))
        self.assertEqual(line.path, 'Local news · 2026-10-26')
        self.assertEqual(line.action_open()['res_model'], 'memory.source.item')
