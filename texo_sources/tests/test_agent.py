# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from unittest.mock import patch

import requests

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.texo import okf

from ..models import memory_source_agent, quotes
from ..models.memory_source_feed import MemorySourceFeed
from .common import RSS, SourcesCase

PAGE = ("<html><head><script>var x = 'hidden';</script></head><body><h1>Council</h1>"
        "<p>The mayor said: “We will not get there”, before the vote.</p></body></html>")


@tagged('post_install', '-at_install')
class TestAgent(SourcesCase):
    """The triage in the session of the agent: the same candidates, states and cards as in Odoo."""

    def setUp(self):
        super().setUp()
        self.Item = self.env['memory.source.item'].with_user(self.member)
        self.search_feed = self.env['memory.source.feed'].create({
            'channel_id': self.channel.id, 'kind': 'search_template',
            'url': 'https://news.example.com/?s={q}&feed=rss2'})

    def test_a_search_feed_has_its_placeholder(self):
        with self.assertRaises(UserError):
            self.env['memory.source.feed'].create({'channel_id': self.channel.id, 'kind': 'search_template',
                                                   'url': 'https://news.example.com/?s=x'})
        with self.assertRaises(UserError):
            self.env['memory.source.feed'].create({'channel_id': self.channel.id, 'kind': 'rss',
                                                   'url': 'https://news.example.com/?s={q}'})
        self.assertEqual(self.search_feed._address('consiglio comunale'),
                         'https://news.example.com/?s=consiglio+comunale&feed=rss2')
        with self.assertRaises(UserError):
            self.search_feed._address(' ')

    def test_search_news_about_a_subject(self):
        addresses = []

        def fetch(feed_self, query=None):
            addresses.append(feed_self._address(query))
            return RSS

        with patch.object(MemorySourceFeed, '_fetch', fetch):
            first = self.Item._agent_search('mozione')
        self.assertEqual(addresses, ['https://news.example.com/?s=mozione&feed=rss2'],
                         "only the search feeds, on the subject; the plain feed is not read")
        self.assertEqual((first['new'], len(first['found']), first['known']), (2, 2, []))
        with patch.object(MemorySourceFeed, '_fetch', fetch):
            again = self.Item._agent_search('motion')
        self.assertEqual((again['new'], len(again['found'])), (0, 2), "the links already known come back, none twice")
        self.assertEqual([k['title'] for k in again['known']], ['City council: the motion of no confidence is filed'],
                         "what the memory already had, by every word of the subject")
        other = self.env['memory.source.channel'].create({'name': 'Radio', 'kind': 'broadcaster'})
        with patch.object(MemorySourceFeed, '_fetch', fetch):
            outcome = self.Item._agent_search('motion', channel_ids=[other.id])
        self.assertEqual(outcome['without_search'], ['Radio'], "a channel that cannot be asked is named")

    def test_a_search_since_a_day_and_brief_entries(self):
        """A press review asks only for what is new: since a day, the older entries of a search feed are neither
        candidates nor found; the lists are brief, a card is read in full by its concept."""
        card = self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/old-motion',
                                 'title': 'The motion of no confidence, a year ago', 'state': 'active',
                                 'abstract': 'A long abstract of the card. ' * 40, 'event_date': '2025-10-01'})
        with patch.object(MemorySourceFeed, '_fetch', return_value=RSS):
            outcome = self.Item._agent_search('motion', since='2026-10-29')
        self.assertEqual(outcome['new'], 1, "the article of the 28th is older than since: not a candidate")
        self.assertEqual([f['title'] for f in outcome['found']], ['Theatre reopens in June'])
        self.assertEqual(outcome['found_total'], 1)
        self.assertEqual(outcome['known'], [], "the card of 2025 is older than since")
        self.assertFalse(self.Item.search([('url', '=', 'https://news.example.com/council-motion')]))
        with patch.object(MemorySourceFeed, '_fetch', return_value=RSS):
            everything = self.Item._agent_search('motion')
        known = everything['known'][0]
        self.assertEqual((known['id'], known['concept']), (card.id, f'sources/{card.id}'))
        self.assertNotIn('abstract', known, "a list is brief: the card is read with memory/read")
        self.assertTrue(all('abstract' not in f for f in everything['found']))
        self.assertEqual(okf.parse(f'sources/{card.id}'), ('memory.source.item', card.id))
        other = self.Item.search([('url', '=', 'https://news.example.com/council-motion')])
        card.related_ids = other
        full = card._agent_read()
        self.assertTrue(full['abstract'].startswith('A long abstract'))
        self.assertEqual([r['id'] for r in full['related']], [other.id])
        self.assertLessEqual(len(card._agent_read(max_chars=200)['abstract']), 200)

    def test_find_by_words_labels_and_dates(self):
        a = self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/a', 'title': 'Housing plan',
                              'abstract': 'Public housing of the city', 'event_date': '2026-10-20', 'state': 'todo'})
        a.write({'person_ids': [(4, self.person.id)]})
        self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/b', 'title': 'Theatre',
                          'event_date': '2026-09-01'})
        self.assertEqual([e['id'] for e in self.Item._agent_find('housing city')], [a.id])
        self.assertEqual([e['id'] for e in self.Item._agent_find(persons=['mayor'])], [a.id])
        self.assertEqual(len(self.Item._agent_find(date_from='2026-10-01')), 1)
        self.assertEqual(len(self.Item._agent_find(states=['candidate'])), 1)

    def test_the_period_reads_the_day_of_publication_when_the_event_date_is_not_known(self):
        undated = self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/c', 'title': 'Undated',
                                    'published_on': '2026-10-28 12:00:00'})
        dated = self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/d', 'title': 'Dated',
                                  'published_on': '2026-10-30 12:00:00', 'event_date': '2026-10-27'})
        self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/e', 'title': 'No date'})
        self.assertEqual(undated.period_date.isoformat(), '2026-10-28')
        self.assertEqual(dated.period_date.isoformat(), '2026-10-27', "the event date wins over the publication")
        found = self.Item._agent_find(date_from='2026-10-27', date_to='2026-10-28', states=['candidate'])
        self.assertEqual([e['id'] for e in found], [undated.id, dated.id], "the newest first, both in the period")

    def test_propose_then_decide_in_odoo_or_in_the_session(self):
        with patch.object(MemorySourceFeed, '_fetch', return_value=RSS):
            self.channel._read_feeds()
        inbox = self.Item._agent_inbox()
        self.assertEqual((inbox['total'], inbox['watched']), (2, 1))
        motion, theatre = (self.Item.browse(c['id']) for c in inbox['candidates'])
        self.assertTrue(motion.watch_match, "the watched first")
        with self.assertRaises(UserError):
            self.Item._agent_propose(motion.id, 'maybe')
        with self.assertRaises(UserError, msg="the doubts come from the fixed list"):
            self.Item._agent_propose(motion.id, 'keep', doubts=['gossip'])
        entry = self.Item._agent_propose(motion.id, 'keep', themes=['Crisis in the council'], card='The motion is filed.',
                                         doubts=['event_date', 'partisan'], questions='Filed on the 28th or the 29th?',
                                         generated_by='claude-code/2.1')
        self.assertEqual(entry['proposal']['doubts'], ['event_date', 'partisan'])
        self.assertEqual(entry['proposal']['by'], 'claude-code/2.1')
        self.assertEqual(motion.state, 'candidate', "a proposal decides nothing")
        motion.with_user(self.member).action_keep_as_proposed()  # the person, in Odoo
        self.assertEqual((motion.state, motion.abstract, motion.theme_ids.mapped('name')),
                         ('todo', 'The motion is filed.', ['Crisis in the council']))
        self.Item._agent_triage([theatre.id], 'discard')  # the person, in the session
        self.assertEqual(theatre.state, 'discarded')
        with self.assertRaises(UserError):
            self.Item._agent_triage([theatre.id], 'maybe')

    def test_the_inbox_gives_the_cards_to_write_and_those_sent_back(self):
        """The press review works off the candidates and the cards to write: a card kept and not written, and a
        card a lead sent back, with the notes of the chatter that say what to change."""
        kept = self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/kept',
                                 'title': 'Kept in Odoo', 'state': 'todo'})
        card = self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/card',
                                 'title': 'The mayor spoke', 'state': 'todo', 'abstract': 'The mayor spoke.'})
        card.with_user(self.lead).action_submit()
        card.with_user(self.lead).action_approve()
        card.with_user(self.lead).action_send_back()
        card.with_user(self.lead).message_post(body="La data dell'evento è il 27, non il 28.", message_type='comment')
        inbox = self.Item._agent_inbox()
        self.assertEqual(inbox['to_write_total'], 2)
        entries = {e['id']: e for e in inbox['to_write']}
        self.assertFalse(entries[kept.id]['sent_back'])
        self.assertNotIn('notes', entries[kept.id])
        self.assertTrue(entries[card.id]['sent_back'])
        self.assertEqual(entries[card.id]['notes'], ["La data dell'evento è il 27, non il 28."])
        # written again, it is no longer sent back
        card.with_user(self.member).write({'abstract': 'The mayor spoke on the 27th.'})
        card.with_user(self.member).action_submit()
        self.assertFalse(card.sent_back)
        self.assertEqual([e['id'] for e in self.Item._agent_inbox()['to_write']], [kept.id])

    def test_a_card_and_its_quotes_checked_on_the_page(self):
        item = self.Item._agent_link('https://news.example.com/council', 'Council')
        card = {'item_id': item['id'], 'abstract': 'The mayor answers on the motion.', 'themes': ['Council'],
                'persons': ['The mayor'], 'event_date': '2026-10-29', 'stance': 'neutral'}
        with patch.object(memory_source_agent, 'page_text', return_value="The mayor said: “We will not get there”."):
            with self.assertRaises(UserError, msg="not in the page, word for word"):
                self.Item._agent_card(quotes='«We will win», the mayor', **card)
            entry = self.Item._agent_card(quotes='«We will not get there», the mayor', **card)
        self.assertEqual((entry['state'], entry['needs_approval'], entry['persons']), ('to_approve', True, ['The mayor']))
        self.assertEqual(self.person.search_count([('name', '=', 'The mayor'), ('kind', '=', 'person')]), 1,
                         "an existing label is reused, case aside")
        down = patch.object(memory_source_agent, 'page_text', side_effect=requests.ConnectionError('down'))
        other = self.Item._agent_link('https://news.example.com/other')
        with down, self.assertRaises(UserError, msg="a page that cannot be read: no quote can be checked"):
            self.Item._agent_card(other['id'], 'Something', quotes='«anything»')
        entry = self.Item._agent_card(other['id'], 'Something happened, no person named.', themes='Council')
        self.assertEqual(entry['state'], 'active')

    def test_the_page_text_without_scripts(self):
        answer = requests.Response()
        answer.status_code = 200

        class Raw:
            def read(self, size, decode_content=False):
                return PAGE.encode()

            def close(self):
                pass

        answer.raw = Raw()
        with patch.object(quotes.requests, 'get', return_value=answer):
            text = quotes.page_text('https://news.example.com/x')
        self.assertIn('We will not get there', text)
        self.assertNotIn('hidden', text)

    def test_the_pack_says_what_to_read_and_to_sort(self):
        self.Item.create({'channel_id': self.channel.id, 'url': 'https://news.example.com/z', 'title': 'Z',
                          'watch_match': True})
        pack = self.env['memory.note'].with_user(self.member)._agent_context(project_id=self.project.id)
        sources = pack['sources']
        self.assertEqual([c['name'] for c in sources['channels_due']], ['Local news'], "never read: overdue")
        self.assertEqual((sources['candidates'], sources['candidates_watched']), (1, 1))

    def test_the_optional_cron_reads_the_overdue_channels(self):
        cron = self.env.ref('texo_sources.ir_cron_memory_source_collect')
        self.assertFalse(cron.active, "off by default: the channels are read on request")
        with patch.object(MemorySourceFeed, '_fetch', return_value=RSS):
            self.env['memory.source.channel']._cron_collect()
        self.assertEqual(len(self.channel.item_ids), 2)
        self.assertFalse(self.channel.overdue)
