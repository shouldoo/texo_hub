# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .memory_source_feed import watch_terms

STATES = [('candidate', "Candidate"), ('discarded', "Discarded"), ('todo', "To Write"),
          ('to_approve', "To Approve"), ('active', "Active"), ('archived', "Archived")]
KINDS = [('article', "Article"), ('video', "Video"), ('statement', "Statement"), ('act', "Act"),
         ('call', "Call for Proposals"), ('other', "Other")]
STANCES = [('positive', "Positive"), ('neutral', "Neutral"), ('negative', "Negative"), ('none', "Not Relevant")]
RELEVANCE = [('1', "Low"), ('2', "Medium"), ('3', "High")]
PROPOSALS = [('keep', "Keep"), ('discard', "Discard"), ('check', "Check First")]
# characters of all the quotes of a card together: a card quotes, it does not copy
MAX_QUOTES = 600
# days before a card is reviewed, unless its channel or the person says otherwise
REVIEW_DAYS = 365
# what a reading of the feeds never changes, and what only a lead changes on an approved card
CONTENT_FIELDS = {'title', 'abstract', 'quotes', 'person_ids', 'body_ids', 'place_ids', 'theme_ids', 'event_date',
                  'stance', 'keywords', 'related_ids', 'segment_ids'}


class MemorySourceItem(models.Model):
    """A thing published by a channel: first a candidate from a feed (or a link pasted by hand),
    then, if kept, a card of the memory.

    The card holds what the organisation needs to find it again and to use it: an abstract
    written by whoever fills it in, the public persons, bodies, places and acts it names, the
    date of the event (not only of publication), short quotes, themes, the stance towards the
    organisation, the cards it relates to. Never the text of the article: the quotes are short
    by construction. A card that names persons waits for a lead's approval; an approved card is
    changed only by a lead, and a new reading of the feeds never touches an existing card."""
    _name = 'memory.source.item'
    _description = "External Source Card"
    _inherit = ['mail.thread']
    _order = 'watch_match desc, published_on desc, id desc'
    _rec_name = 'title'

    channel_id = fields.Many2one('memory.source.channel', string="Channel", required=True, index=True,
                                 ondelete='restrict', tracking=True)
    feed_id = fields.Many2one('memory.source.feed', string="Feed", ondelete='set null')
    url = fields.Char(string="Link", required=True, index=True)
    title = fields.Char(required=True, tracking=True)
    kind = fields.Selection(KINDS, required=True, default='article')
    published_on = fields.Datetime(string="Published On", index=True)
    event_date = fields.Date(string="Event Date", index=True, tracking=True,
                             help="When what the card tells happened: often earlier than the publication.")
    period_date = fields.Date(string="Date", compute='_compute_period_date', store=True, index=True,
                              help="The date of the event, or the day it was published when the event date is not "
                                   "known: what a search by period reads.")
    state = fields.Selection(STATES, required=True, default='candidate', index=True, tracking=True)
    watch_match = fields.Boolean(string="Watched Words", readonly=True,
                                 help="The candidate holds words the channel or the feed looks for.")
    triage_note = fields.Char(string="Triage Note", help="Why it was kept, in a line.")
    abstract = fields.Text(help="What it says, in words of whoever fills the card in (60-120 words): who, what, "
                                "where, which acts.")
    quotes = fields.Text(help="At most a couple of short quotes, each between quotation marks and attributed.")
    person_ids = fields.Many2many('memory.source.tag', 'memory_source_item_person_rel', 'item_id', 'tag_id',
                                  string="Public Persons", domain=[('kind', '=', 'person')])
    body_ids = fields.Many2many('memory.source.tag', 'memory_source_item_body_rel', 'item_id', 'tag_id',
                                string="Bodies", domain=[('kind', '=', 'body')])
    place_ids = fields.Many2many('memory.source.tag', 'memory_source_item_place_rel', 'item_id', 'tag_id',
                                 string="Places", domain=[('kind', '=', 'place')])
    theme_ids = fields.Many2many('memory.source.tag', 'memory_source_item_theme_rel', 'item_id', 'tag_id',
                                 string="Themes", domain=[('kind', '=', 'theme')])
    acts = fields.Char(help="Acts named: resolutions, motions, laws, articles.")
    keywords = fields.Char(help="Synonyms and other names, comma-separated, to find the card by other words.")
    stance = fields.Selection(STANCES, string="Stance", help="Towards the organisation: an internal judgement.")
    relevance = fields.Selection(RELEVANCE, default='2')
    related_ids = fields.Many2many('memory.source.item', 'memory_source_item_related_rel', 'item_id', 'related_id',
                                   string="Related Cards")
    segment_ids = fields.One2many('memory.source.segment', 'item_id', string="Video Segments")
    # what the agent proposes when asked to prepare the triage: the person decides, in Odoo or in the session
    proposal_action = fields.Selection(PROPOSALS, string="Proposed Action")
    proposal_theme_ids = fields.Many2many('memory.source.tag', 'memory_source_item_proposal_theme_rel', 'item_id',
                                          'tag_id', string="Proposed Themes", domain=[('kind', '=', 'theme')])
    proposal_abstract = fields.Text(string="Proposed Card", help="The card as the agent would write it, in short.")
    proposal_flag_ids = fields.Many2many('memory.source.flag', string="Doubts")
    proposal_questions = fields.Text(string="Questions", help="What the agent needs to know to write the card.")
    proposal_by = fields.Char(string="Proposed By", readonly=True)
    proposal_on = fields.Datetime(string="Proposed On", readonly=True)
    needs_approval = fields.Boolean(compute='_compute_needs_approval', store=True,
                                    help="The card names public persons: a lead approves it.")
    approved_by_id = fields.Many2one('res.users', string="Approved By", readonly=True)
    approved_on = fields.Datetime(string="Approved On", readonly=True)
    sent_back = fields.Boolean(string="Sent Back", readonly=True, copy=False,
                               help="A lead sent the card back: the chatter says what to change; written again, it "
                                    "is cleared.")
    review_date = fields.Date(string="Review On", index=True,
                              default=lambda self: fields.Date.context_today(self) + timedelta(days=REVIEW_DAYS),
                              help="When the card is reviewed: confirmed or archived.")
    project_id = fields.Many2one(related='channel_id.project_id', store=True, index=True)
    company_id = fields.Many2one(related='channel_id.company_id', store=True, index=True)

    _unique_url = models.Constraint('UNIQUE(company_id, url)', "This link is already in the external sources.")

    @api.depends('event_date', 'published_on')
    def _compute_period_date(self):
        for item in self:
            item.period_date = item.event_date or (item.published_on and item.published_on.date()) or False

    @api.depends('person_ids')
    def _compute_needs_approval(self):
        for item in self:
            item.needs_approval = bool(item.person_ids)

    @api.constrains('quotes')
    def _check_quotes(self):
        for item in self:
            if item.quotes and len(item.quotes) > MAX_QUOTES:
                raise UserError(self.env._(
                    "Quotes are short: at most %(max)s characters together, not %(len)s. A card quotes, it does not copy.",
                    max=MAX_QUOTES, len=len(item.quotes)))

    # -- guards -------------------------------------------------------------------
    def _is_lead(self):
        return self.env.su or self.env.user._texo_role() in ('lead', 'admin')

    def write(self, vals):
        if not self._is_lead():
            approval = 'approved_by_id' in vals or 'approved_on' in vals
            decides = vals.get('state') in ('active', 'archived') and any(
                item.needs_approval or item.state == 'active' for item in self)
            if approval or decides:
                raise AccessError(self.env._("Only a Texo lead approves or archives a card that names persons."))
            if CONTENT_FIELDS & set(vals) and any(item.approved_on for item in self):
                raise AccessError(self.env._("An approved card is changed by a lead: ask for it, or send it back."))
        return super().write(vals)

    # -- the reading of the feeds -----------------------------------------------------
    @api.model
    def _from_entries(self, feed, entries):
        """The candidates of the entries of a feed that are not yet in the external sources of
        the organisation (by link): an existing card is never touched."""
        channel = feed.channel_id
        urls = list(dict.fromkeys(e['url'] for e in entries))
        # sudo: a link already kept by a project the reader cannot see is still not new
        known = set(self.sudo().with_context(active_test=False).search(
            [('company_id', '=', channel.company_id.id), ('url', 'in', urls)]).mapped('url'))
        terms = watch_terms(channel.watch_terms, feed.watch_terms)
        kind = 'video' if feed.kind == 'video' or channel.kind == 'video' else 'article'
        vals_list, seen = [], set()
        for entry in entries:
            if entry['url'] in known or entry['url'] in seen:
                continue
            seen.add(entry['url'])
            haystack = f"{entry['title']} {entry['summary']}".lower()
            vals_list.append({
                'channel_id': channel.id, 'feed_id': feed.id, 'url': entry['url'],
                'title': (entry['title'] or entry['url'])[:500], 'kind': kind,
                'published_on': entry['published'] or fields.Datetime.now(),
                'watch_match': any(term in haystack for term in terms),
            })
        return self.create(vals_list)

    @api.model
    def _from_link(self, url, title=None):
        """A candidate for a link pasted by hand, on the channel of its domain."""
        channel = self.env['memory.source.channel']._for_url(url)
        if not channel:
            raise UserError(self.env._("No channel has the site of %s: add the channel first.", url))
        existing = self.search([('company_id', '=', channel.company_id.id), ('url', '=', url.strip())], limit=1)
        return existing or self.create({'channel_id': channel.id, 'url': url.strip(), 'title': title or url.strip(),
                                        'published_on': fields.Datetime.now()})

    # -- the life of a card -------------------------------------------------------------
    def action_keep(self):
        """Triage: keep the candidates, to be written as cards."""
        self.filtered(lambda i: i.state in ('candidate', 'discarded')).write({'state': 'todo'})

    def action_keep_as_proposed(self):
        """Triage as the agent proposed: kept with its themes, its draft as the abstract to finish."""
        for item in self.filtered(lambda i: i.state in ('candidate', 'discarded')):
            vals = {'state': 'todo', 'theme_ids': [(4, tag.id) for tag in item.proposal_theme_ids]}
            if item.proposal_abstract and not item.abstract:
                vals['abstract'] = item.proposal_abstract
            item.write(vals)

    def action_discard(self):
        self.filtered(lambda i: i.state in ('candidate', 'todo')).write({'state': 'discarded'})

    def action_submit(self):
        """A written card: active at once, or to approve when it names persons."""
        for item in self:
            if item.state != 'todo':
                continue
            if not (item.abstract or '').strip():
                raise UserError(self.env._("Write the abstract of «%s» first.", item.title))
            if item.needs_approval:
                item.write({'state': 'to_approve', 'sent_back': False})
            else:
                # sudo: an active card that names nobody needs no lead; the state alone is written
                item.sudo().write({'state': 'active', 'sent_back': False})

    def action_approve(self):
        if not self._is_lead():
            raise AccessError(self.env._("Only a Texo lead approves a card that names persons."))
        self.filtered(lambda i: i.state in ('to_approve', 'todo')).write(
            {'state': 'active', 'approved_by_id': self.env.uid, 'approved_on': fields.Datetime.now()})

    def action_send_back(self):
        """Back to whoever writes it, with what to change in the chatter."""
        if not self._is_lead():
            raise AccessError(self.env._("Only a Texo lead sends a card back."))
        self.filtered(lambda i: i.state in ('to_approve', 'active')).write(
            {'state': 'todo', 'approved_by_id': False, 'approved_on': False, 'sent_back': True})

    def action_archive_card(self):
        self.write({'state': 'archived'})

    def action_review_later(self):
        """Confirmed at its review: reviewed again in a year."""
        self.write({'review_date': fields.Date.context_today(self) + timedelta(days=REVIEW_DAYS)})
