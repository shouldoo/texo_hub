# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta
from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import UserError

KINDS = [('press', "Newspaper"), ('broadcaster', "Broadcaster"), ('video', "Video Channel"),
         ('public_body', "Public Body"), ('calls', "Calls Portal"), ('legislation', "Legislation"),
         ('other', "Other")]


def domain_of(url):
    """The host of a link without its www., lower case: what ties a pasted link to its channel."""
    host = urlparse((url or '').strip()).hostname or ''
    return host[4:] if host.startswith('www.') else host


class MemorySourceChannel(models.Model):
    """Who publishes something the organisation follows: a newspaper, a broadcaster, a video
    channel, a public body, a portal of calls, a source of legislation.

    The organisation decides its channels; the agent proposes new ones and adds them after
    the person's yes. A channel says what to look for in it and how often: the context pack
    lists the channels overdue, so the agent knows what to read without remembering it. How
    a channel is read is its feeds; a channel without a feed is checked by hand. Nothing is
    read on a schedule: a person, or the agent on request, reads the channels."""
    _name = 'memory.source.channel'
    _description = "External Source Channel"
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    kind = fields.Selection(KINDS, required=True, default='press', tracking=True)
    website = fields.Char(help="The site of the channel: a link pasted by hand is tied to the channel of its domain.")
    domain = fields.Char(compute='_compute_domain', store=True, index=True)
    territory = fields.Char(help="Where it reports from or about (a city, a region).")
    note = fields.Text(string="Notes", help="What the organisation knows of it: its orientation, how reliable it is. "
                                            "An internal note, never quoted.")
    terms_of_use = fields.Char(string="Terms of Use",
                               help="What may be kept of it: reserved reproduction, paywall, licence.")
    watch_terms = fields.Char(string="Look For",
                              help="Comma-separated words that matter in this channel: the candidates that hold "
                                   "them come first in the triage.")
    frequency_days = fields.Integer(string="Read Every (Days)", default=1, tracking=True,
                                    help="How often the channel should be read; later than this it is overdue.")
    project_id = fields.Many2one('project.project', string="Project", index=True, ondelete='cascade',
                                 help="The project the channel serves; empty, the whole organisation.")
    company_id = fields.Many2one('res.company', string="Organisation", required=True, index=True,
                                 default=lambda self: self.env.company)
    active = fields.Boolean(default=True, tracking=True)
    feed_ids = fields.One2many('memory.source.feed', 'channel_id', string="Feeds")
    item_ids = fields.One2many('memory.source.item', 'channel_id', string="Cards")
    item_count = fields.Integer(compute='_compute_item_count')
    last_read = fields.Datetime(readonly=True, tracking=True)
    overdue = fields.Boolean(compute='_compute_overdue', search='_search_overdue',
                             help="Not read for longer than its frequency.")

    @api.depends('website')
    def _compute_domain(self):
        for channel in self:
            channel.domain = domain_of(channel.website) or False

    def _compute_item_count(self):
        counts = dict(self.env['memory.source.item']._read_group(
            [('channel_id', 'in', self.ids)], ['channel_id'], ['__count']))
        for channel in self:
            channel.item_count = counts.get(channel, 0)

    @api.depends('last_read', 'frequency_days')
    def _compute_overdue(self):
        now = fields.Datetime.now()
        for channel in self:
            channel.overdue = not channel.last_read or (
                channel.last_read + timedelta(days=max(channel.frequency_days, 1)) < now)

    def _search_overdue(self, operator, value):
        if operator not in ('in', 'not in'):
            return NotImplemented
        overdue = self.search([]).filtered('overdue')
        return [('id', operator, overdue.ids)]

    @api.model
    def _for_url(self, url):
        """The channel of a link, by the domain of its host, among the channels the user may read."""
        domain = domain_of(url)
        return self.search([('domain', '=', domain)], limit=1) if domain else self.browse()

    # -- reading ------------------------------------------------------------------
    def action_read_now(self):
        """Read the feeds of these channels now: new links become candidates of the triage.
        The pages checked by hand are listed for the person; the reading is recorded."""
        outcome = self._read_feeds()
        message = self.env._("%(new)s new candidates from %(read)s feeds.", new=outcome['new'], read=outcome['read'])
        if outcome['errors']:
            message += " " + self.env._("Not read: %s.", ", ".join(outcome['errors']))
        if outcome['manual']:
            message += " " + self.env._("To check by hand: %s.", ", ".join(outcome['manual']))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': self.env._("Channels read"), 'message': message, 'sticky': bool(outcome['manual']),
                           'type': 'warning' if outcome['errors'] else 'success',
                           'next': {'type': 'ir.actions.act_window_close'}}}

    def _read_feeds(self):
        """{'read', 'new', 'errors', 'manual'} of reading every active feed of these channels."""
        if not self:
            raise UserError(self.env._("Choose the channels to read."))
        outcome = {'read': 0, 'new': 0, 'errors': [], 'manual': []}
        for channel in self:
            for feed in channel.feed_ids.filtered(lambda f: f.active and f.kind != 'search_template'):
                if feed.kind == 'manual':
                    outcome['manual'].append(f"{channel.name}: {feed.url}")
                    feed._record('ok')
                    continue
                created = feed._read()
                if created is None:
                    outcome['errors'].append(f"{channel.name} ({feed.last_message})")
                else:
                    outcome['read'] += 1
                    outcome['new'] += len(created)
        # sudo: a member reads the channels without deciding them; only the date of the reading is written
        self.sudo().write({'last_read': fields.Datetime.now()})
        return outcome

    def _search_feeds(self, query, since=None):
        """Ask these channels about a subject now, through their search feeds with placeholder;
        with since (a date), the entries published before it are left out (an entry without a date
        stays). {'items': the candidates and cards of the links found, new or already known, 'new',
        'errors', 'without_search': the channels that have no such feed}."""
        Item = self.env['memory.source.item']
        outcome = {'items': Item, 'new': 0, 'errors': [], 'without_search': []}
        for channel in self:
            feeds = channel.feed_ids.filtered(lambda f: f.active and f.kind == 'search_template')
            if not feeds:
                outcome['without_search'].append(channel.name)
                continue
            for feed in feeds:
                entries = feed._entries(query)
                if entries is None:
                    outcome['errors'].append(f"{channel.name} ({feed.last_message})")
                    continue
                if since:
                    entries = [e for e in entries if not e['published'] or e['published'].date() >= since]
                created = Item._from_entries(feed, entries)
                feed._record('ok', self.env._("%(new)s new of %(all)s", new=len(created), all=len(entries)))
                outcome['new'] += len(created)
                outcome['items'] |= created | Item.search([('url', 'in', [e['url'] for e in entries])])
        return outcome

    @api.model
    def _cron_collect(self):
        """The optional scheduled reading (its cron is off by default): the overdue channels."""
        channels = self.search([('overdue', '=', True), ('feed_ids', '!=', False)])
        if channels:
            channels._read_feeds()
