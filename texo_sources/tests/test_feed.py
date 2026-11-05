# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import datetime, timedelta
from unittest.mock import patch

import requests

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models import memory_source_feed
from ..models.memory_source_feed import MemorySourceFeed, parse_feed
from .common import ATOM, RSS, SourcesCase


class RawBody:
    """The raw stream of an HTTP answer, as requests hands it to the reader."""

    def __init__(self, content):
        self.content = content

    def read(self, size, decode_content=False):
        return self.content[:size]

    def close(self):
        pass


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


@tagged('post_install', '-at_install')
class TestFeed(SourcesCase):
    """Reading the channels on request: feeds to candidates, never a duplicate, never the text."""

    def test_parse_rss_and_atom(self):
        entries = parse_feed(RSS)
        self.assertEqual([e['url'] for e in entries],
                         ['https://news.example.com/council-motion', 'https://news.example.com/theatre'])
        self.assertEqual(entries[0]['published'], datetime(2026, 10, 28, 9, 15), "RFC 822 to naive UTC")
        video = parse_feed(ATOM)
        self.assertEqual((video[0]['url'], video[0]['title'], video[0]['summary']),
                         ('https://www.youtube.com/watch?v=abc123', 'The mayor on the majority', 'Interview after the council.'))
        self.assertEqual(video[0]['published'], datetime(2026, 10, 27, 18, 30))
        hostile = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
                   b'<rss><channel><item><title>&x;</title><link>https://a.example.com/x</link></item></channel></rss>')
        self.assertNotIn('root:', parse_feed(hostile)[0]['title'], "external entities are never resolved")
        self.assertEqual(parse_feed(b'<rss><channel><item><link>javascript:alert(1)</link></item></channel></rss>'), [],
                         "only http and https links")

    def test_read_now_creates_candidates_once(self):
        with patch.object(MemorySourceFeed, '_fetch', return_value=RSS):
            self.channel.action_read_now()
        items = self.channel.item_ids
        self.assertEqual(len(items), 2)
        self.assertEqual(set(items.mapped('state')), {'candidate'})
        motion = items.filtered(lambda i: 'motion' in i.url)
        self.assertTrue(motion.watch_match, "it holds a watched word of the channel, case aside")
        self.assertFalse((items - motion).watch_match)
        self.assertEqual((self.feed.last_outcome, self.feed.last_message), ('ok', '2 new of 2'))
        self.assertTrue(self.channel.last_read)
        self.assertFalse(self.channel.overdue)
        # a card written meanwhile is never touched by a new reading
        motion.write({'title': 'The motion, as we wrote it', 'state': 'todo'})
        with patch.object(MemorySourceFeed, '_fetch', return_value=RSS):
            outcome = self.channel._read_feeds()
        self.assertEqual(outcome['new'], 0)
        self.assertEqual((motion.title, motion.state), ('The motion, as we wrote it', 'todo'))
        self.assertEqual(len(self.channel.item_ids), 2)

    def test_a_feed_that_fails_or_a_page_by_hand(self):
        with patch.object(MemorySourceFeed, '_fetch', side_effect=http_error(403)):
            outcome = self.channel._read_feeds()
        self.assertEqual((self.feed.last_outcome, outcome['read'], len(outcome['errors'])), ('refused', 0, 1))
        with patch.object(MemorySourceFeed, '_fetch', side_effect=requests.ConnectionError('down')):
            self.channel._read_feeds()
        self.assertEqual(self.feed.last_outcome, 'error')
        self.feed.active = False
        self.env['memory.source.feed'].create({'channel_id': self.channel.id, 'kind': 'manual',
                                               'url': 'https://news.example.com/politics'})
        outcome = self.channel._read_feeds()
        self.assertEqual(outcome['manual'], ['Local news: https://news.example.com/politics'])
        self.assertTrue(self.channel.last_read, "a channel checked by hand is read too")

    def test_the_size_and_the_scheme_of_a_feed(self):
        with self.assertRaises(UserError):
            self.env['memory.source.feed'].create({'channel_id': self.channel.id, 'url': 'file:///etc/passwd'})
        big = patch.object(memory_source_feed, 'MAX_BYTES', 10)
        answer = requests.Response()
        answer.status_code = 200
        answer.raw = RawBody(RSS)
        with big, patch.object(memory_source_feed.requests, 'get', return_value=answer):
            self.assertIsNone(self.feed._read())
        self.assertIn('larger', self.feed.last_message)

    def test_overdue_by_frequency(self):
        Channel = self.env['memory.source.channel']
        self.assertTrue(self.channel.overdue, "never read")
        self.assertIn(self.channel, Channel.search([('overdue', '=', True)]))
        self.channel.write({'last_read': fields.Datetime.now() - timedelta(days=2), 'frequency_days': 7})
        self.assertFalse(self.channel.overdue)
        self.assertNotIn(self.channel, Channel.search([('overdue', '=', True)]))
        self.channel.frequency_days = 1
        self.assertTrue(self.channel.overdue)
