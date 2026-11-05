# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus, urlparse

import requests
from lxml import etree

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

KINDS = [('rss', "RSS or Atom Feed"), ('video', "Video Channel Feed"), ('search', "Search Feed"),
         ('search_template', "Search Feed with Placeholder"), ('manual', "Page to Check by Hand")]
# where the subject of a search goes in the address of a search feed with placeholder
PLACEHOLDER = '{q}'
OUTCOMES = [('ok', "Read"), ('error', "Error"), ('refused', "Refused")]
# seconds to wait for a feed, bytes of a feed at most: a feed is a list of links, not a page
TIMEOUT = 20
MAX_BYTES = 5 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; Texo-Sources/1.0)"
ATOM = '{http://www.w3.org/2005/Atom}'
MEDIA = '{http://search.yahoo.com/mrss/}'


def _text(node):
    return " ".join((node.text or '').split()) if node is not None else ''


def _date(value):
    """A date of a feed (RFC 822 in RSS, ISO 8601 in Atom) as a naive UTC datetime, or None."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if parsed.tzinfo:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def parse_feed(content):
    """[{'url', 'title', 'published', 'summary'}] of an RSS 2.0 or an Atom feed (the feed of a
    video channel is Atom). The summary is read only to match the words to look for: it is
    never stored. Entities are not resolved and nothing is fetched while parsing."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)
    root = etree.fromstring(content, parser=parser)
    if root is None:
        return []
    entries = []
    for item in root.iter('item'):  # RSS
        entries.append({'url': _text(item.find('link')), 'title': _text(item.find('title')),
                        'published': _date(_text(item.find('pubDate'))), 'summary': _text(item.find('description'))})
    for entry in root.iter(f'{ATOM}entry'):  # Atom
        links = entry.findall(f'{ATOM}link')
        link = next((li for li in links if li.get('rel', 'alternate') == 'alternate'), links[0] if links else None)
        summary = entry.find(f'{ATOM}summary')
        if summary is None:
            summary = entry.find(f'{MEDIA}group/{MEDIA}description')
        entries.append({'url': (link.get('href') or '').strip() if link is not None else '',
                        'title': _text(entry.find(f'{ATOM}title')),
                        'published': _date(_text(entry.find(f'{ATOM}published')) or _text(entry.find(f'{ATOM}updated'))),
                        'summary': _text(summary)})
    return [e for e in entries if e['url'].startswith(('http://', 'https://'))]


def watch_terms(*values):
    """The words to look for, from comma-separated texts, lower case, without duplicates."""
    terms = []
    for value in values:
        terms += [t.strip().lower() for t in (value or '').split(',') if t.strip()]
    return list(dict.fromkeys(terms))


class MemorySourceFeed(models.Model):
    """How a channel is read: an RSS or Atom feed, the feed of a video channel, a search feed
    (a feed of the results of a search on the site), or a page to check by hand when the
    channel has no feed or refuses automatic reading."""
    _name = 'memory.source.feed'
    _description = "External Source Feed"
    _order = 'channel_id, id'

    channel_id = fields.Many2one('memory.source.channel', string="Channel", required=True, ondelete='cascade',
                                 index=True)
    kind = fields.Selection(KINDS, required=True, default='rss')
    url = fields.Char(string="Address", required=True)
    watch_terms = fields.Char(string="Look For", help="Words that matter in this feed, besides those of the channel.")
    active = fields.Boolean(default=True)
    last_read = fields.Datetime(readonly=True)
    last_outcome = fields.Selection(OUTCOMES, readonly=True)
    last_message = fields.Char(readonly=True)
    company_id = fields.Many2one(related='channel_id.company_id', store=True, index=True)

    @api.constrains('url', 'kind')
    def _check_url(self):
        for feed in self:
            if urlparse(feed.url or '').scheme not in ('http', 'https'):
                raise UserError(self.env._("A feed is read over http or https: %s", feed.url))
            if (feed.kind == 'search_template') != (PLACEHOLDER in (feed.url or '')):
                raise UserError(self.env._(
                    "A search feed with placeholder has %(q)s in its address, where the subject goes; the other "
                    "feeds have none: %(url)s", q=PLACEHOLDER, url=feed.url))

    def _record(self, outcome, message=False):
        """Record a reading: when, how it went. A member reads the channels without deciding them;
        sudo writes the reading and nothing else."""
        self.sudo().write({'last_read': fields.Datetime.now(), 'last_outcome': outcome,
                           'last_message': message[:250] if message else False})

    def _address(self, query=None):
        """The address to read: a search feed with placeholder gets the subject, URL-encoded."""
        self.ensure_one()
        if self.kind != 'search_template':
            return self.url
        if not (query or '').strip():
            raise UserError(self.env._("A search feed needs a subject to search."))
        return self.url.replace(PLACEHOLDER, quote_plus(query.strip()))

    def _fetch(self, query=None):
        """The bytes of the feed, within MAX_BYTES; raises requests.RequestException."""
        self.ensure_one()
        with requests.get(self._address(query), timeout=TIMEOUT, stream=True,
                          headers={'User-Agent': USER_AGENT}) as answer:
            answer.raise_for_status()
            content = answer.raw.read(MAX_BYTES + 1, decode_content=True)
        if len(content) > MAX_BYTES:
            raise requests.RequestException(self.env._("the feed is larger than %s MB", MAX_BYTES // (1024 * 1024)))
        return content

    def _entries(self, query=None):
        """The entries of the feed (a search feed with placeholder: on the subject), or None
        when it could not be read; a failure is recorded on the feed."""
        self.ensure_one()
        try:
            return parse_feed(self._fetch(query))
        except requests.HTTPError as error:
            refused = error.response is not None and error.response.status_code in (401, 403, 429)
            self._record('refused' if refused else 'error', str(error))
        except (requests.RequestException, etree.LxmlError, ValueError) as error:
            _logger.info("feed %s not read: %s", self.url, error)
            self._record('error', str(error))
        return None

    def _read(self, query=None):
        """Read the feed and create a candidate for every new link; the record of the reading
        says how it went. The candidates created, or None when the feed could not be read."""
        self.ensure_one()
        entries = self._entries(query)
        if entries is None:
            return None
        created = self.env['memory.source.item']._from_entries(self, entries)
        self._record('ok', self.env._("%(new)s new of %(all)s", new=len(created), all=len(entries)))
        return created
