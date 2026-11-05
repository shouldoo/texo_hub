# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo.tests.common import TransactionCase

from odoo.addons.texo_memory.tests.common import MemoryFixtures

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Local news</title>
<item><title>City council: the motion of no confidence is filed</title>
<link>https://news.example.com/council-motion</link>
<pubDate>Wed, 28 Oct 2026 10:15:00 +0100</pubDate>
<description>The opposition groups sign the motion.</description></item>
<item><title>Theatre reopens in June</title>
<link>https://news.example.com/theatre</link>
<pubDate>Thu, 29 Oct 2026 08:00:00 +0100</pubDate>
<description>Four more millions are needed.</description></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
<title>Local TV</title>
<entry><title>The mayor on the majority</title>
<link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
<published>2026-10-27T18:30:00+00:00</published>
<media:group><media:description>Interview after the council.</media:description></media:group></entry>
</feed>"""


class SourcesCase(MemoryFixtures, TransactionCase):
    """The people, customer, project and task of the memory tests, plus a channel of the
    organisation read through an RSS feed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.channel = cls.env['memory.source.channel'].create({
            'name': 'Local news', 'kind': 'press', 'website': 'https://www.news.example.com',
            'watch_terms': 'council, Hospital'})
        cls.feed = cls.env['memory.source.feed'].create({
            'channel_id': cls.channel.id, 'kind': 'rss', 'url': 'https://news.example.com/feed'})
        cls.person = cls.env['memory.source.tag'].create({'name': 'The mayor', 'kind': 'person'})
        cls.theme = cls.env['memory.source.tag'].create({'name': 'Council', 'kind': 'theme'})
