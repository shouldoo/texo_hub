# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The external sources for the agent: the same candidates, states and cards as in Odoo, so the
triage can be done in either place.

Every method runs as the person: Odoo's access rules decide what exists. The routes of
controllers/main.py and the tools of the MCP server call these methods."""
import requests

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.texo import okf

from .memory_source_item import PROPOSALS, RELEVANCE, STANCES
from .quotes import missing_quotes, page_text

LIMIT = 20
# notes of the chatter given with a card to write: what to change, newest first
NOTES = 3
# a card is a concept of the memory: sources/12, read with memory/read
okf.register('memory.source.item', 'sources')
LABEL_FIELDS = {'persons': ('person_ids', 'person'), 'bodies': ('body_ids', 'body'), 'places': ('place_ids', 'place'),
                'themes': ('theme_ids', 'theme')}


def _names(value):
    """A list of names from a list or a comma-separated text, stripped, without duplicates."""
    if isinstance(value, str):
        value = value.split(',')
    return list(dict.fromkeys(v.strip() for v in value or [] if v and v.strip()))


class MemorySourceItem(models.Model):
    _inherit = 'memory.source.item'

    # -- what the agent reads -----------------------------------------------------------
    def _okf_kind(self):
        """sources/12: the kind of a card in an Open Knowledge Format bundle."""
        return 'sources'

    def _agent_entry(self):
        """A card or a candidate as the agent reads it."""
        self.ensure_one()
        entry = {'id': self.id, 'concept': okf.concept_id(self), 'title': self.title, 'url': self.url,
                 'channel': self.channel_id.name, 'kind': self.kind, 'state': self.state,
                 'published_on': fields.Datetime.to_string(self.published_on) if self.published_on else None,
                 'event_date': fields.Date.to_string(self.event_date) if self.event_date else None,
                 'watched': self.watch_match}
        for key, (field, _kind) in LABEL_FIELDS.items():
            if self[field]:
                entry[key] = self[field].mapped('name')
        for key in ('triage_note', 'abstract', 'quotes', 'acts', 'keywords', 'stance'):
            if self[key]:
                entry[key] = self[key]
        if self.needs_approval:
            entry['needs_approval'] = True
        if self.approved_on:
            entry['approved_by'] = self.approved_by_id.name
        if self.proposal_on:
            entry['proposal'] = {
                'action': self.proposal_action, 'themes': self.proposal_theme_ids.mapped('name'),
                'card': self.proposal_abstract or None, 'doubts': self.proposal_flag_ids.mapped('code'),
                'questions': self.proposal_questions or None, 'by': self.proposal_by or None}
        return entry

    @api.model
    def _agent_find(self, query=None, persons=None, themes=None, channel=None, date_from=None, date_to=None,
                    states=None, limit=LIMIT):
        """The cards and candidates that match: every word of the query in the title, the
        abstract, the keywords, the acts or the triage note; the labels named; the channel;
        the period of the event (its date, or the day of publication when the date of the event is
        not known). The newest first."""
        domain = [('state', 'in', states or ['candidate', 'todo', 'to_approve', 'active'])]
        for word in (query or '').split():
            domain += ['|', '|', '|', '|', ('title', 'ilike', word), ('abstract', 'ilike', word),
                       ('keywords', 'ilike', word), ('acts', 'ilike', word), ('triage_note', 'ilike', word)]
        for name in _names(persons):
            domain.append(('person_ids.name', 'ilike', name))
        for name in _names(themes):
            domain.append(('theme_ids.name', 'ilike', name))
        if channel:
            domain.append(('channel_id.name', 'ilike', channel))
        # the period reads the date of the event, or the day of publication when the event date is not known
        if date_from:
            domain.append(('period_date', '>=', date_from))
        if date_to:
            domain.append(('period_date', '<=', date_to))
        limit = max(1, min(int(limit or LIMIT), 100))
        items = self.search(domain, order='period_date desc nulls last, published_on desc, id desc', limit=limit)
        return [item._agent_entry() for item in items]

    @api.model
    def _agent_inbox(self, watched_only=False, limit=LIMIT):
        """The candidates to sort, the watched first, with the agent's proposals; then the cards to write: kept in
        the triage (in a session or in Odoo, also a candidate added there by hand) and not written yet, or sent
        back by a lead, with the notes of the chatter that say what to change (the press review of the skill
        memoria-fonti works off both)."""
        domain = [('state', '=', 'candidate')] + ([('watch_match', '=', True)] if watched_only else [])
        limit = max(1, min(int(limit or LIMIT), 100))
        items = self.search(domain, limit=limit)
        to_write = self.search([('state', '=', 'todo')], order='write_date desc, id desc', limit=limit)
        return {'total': self.search_count([('state', '=', 'candidate')]),
                'watched': self.search_count([('state', '=', 'candidate'), ('watch_match', '=', True)]),
                'candidates': [item._agent_entry() for item in items],
                'to_write_total': self.search_count([('state', '=', 'todo')]),
                'to_write': [item._agent_to_write_entry() for item in to_write]}

    def _agent_to_write_entry(self):
        """A card to write as the agent reads it: sent_back when a lead sent it back, and the latest notes of its
        chatter, newest first (what to change, or what the person asked)."""
        self.ensure_one()
        entry = self._agent_entry()
        entry['sent_back'] = self.sent_back
        notes = self.env['mail.message'].search([
            ('model', '=', self._name), ('res_id', '=', self.id), ('message_type', '=', 'comment'),
            ('body', '!=', False)], order='id desc', limit=NOTES)
        texts = [" ".join(html2plaintext(note.body).split()) for note in notes]
        if any(texts):
            entry['notes'] = [text for text in texts if text]
        return entry

    # -- what the agent does, on request --------------------------------------------------
    @api.model
    def _agent_collect(self, channel_ids=None, overdue_only=True):
        """Read the channels now (by default the overdue ones): new links become candidates."""
        Channel = self.env['memory.source.channel']
        channels = Channel.browse([int(c) for c in channel_ids]).exists() if channel_ids else Channel.search(
            [('overdue', '=', True)] if overdue_only else [])
        if not channels:
            return {'read': 0, 'new': 0, 'errors': [], 'manual': [], 'message': "No channel to read."}
        return channels._read_feeds()

    @api.model
    def _agent_search(self, query, channel_ids=None, limit=LIMIT, since=None):
        """«Search news about X»: what the memory already has, then the channels asked now through
        their search feeds; the links found become candidates (none twice). since (a date): what was
        published before it is neither a candidate nor found (a press review asks only for what is new;
        a search feed gives years of articles). Both lists are brief (title, dates, link, state): a card
        is read in full with memory/read and its concept."""
        if not (query or '').strip():
            raise UserError(self.env._("Say what to search."))
        since = fields.Date.to_date(since) if since else None
        limit = max(1, min(int(limit or LIMIT), 100))
        Channel = self.env['memory.source.channel']
        channels = Channel.browse([int(c) for c in channel_ids]).exists() if channel_ids else Channel.search([])
        known = self._agent_find(query, limit=limit, date_from=since)
        outcome = channels._search_feeds(query, since=since)
        found = outcome['items'].sorted(lambda i: i.published_on or fields.Datetime.now(), reverse=True)
        return {'known': [brief for brief in self.browse([k['id'] for k in known])._agent_briefs()],
                'found': found[:limit]._agent_briefs(), 'found_total': len(found), 'new': outcome['new'],
                'errors': outcome['errors'], 'without_search': outcome['without_search']}

    def _agent_briefs(self):
        """The cards and candidates in a line each: what a list needs, not the card (memory/read gives it)."""
        return [{'id': item.id, 'concept': okf.concept_id(item), 'title': item.title, 'url': item.url,
                 'channel': item.channel_id.name, 'state': item.state, 'watched': item.watch_match,
                 'published_on': fields.Datetime.to_string(item.published_on) if item.published_on else None,
                 'event_date': fields.Date.to_string(item.event_date) if item.event_date else None}
                for item in self]

    def _agent_read(self, max_chars=6000):
        """A card in full, as memory/read gives a note: the entry with its abstract, quotes and labels, and
        the cards it is linked to."""
        self.ensure_one()
        entry = self._agent_entry()
        if entry.get('abstract'):
            entry['abstract'] = entry['abstract'][:max_chars]
        if self.related_ids:
            entry['related'] = self.related_ids._agent_briefs()
        return entry

    @api.model
    def _agent_link(self, url, title=None):
        """A link pasted by hand becomes a candidate, on the channel of its domain."""
        return self._from_link(url, title)._agent_entry()

    @api.model
    def _agent_propose(self, item_id, action, themes=None, card=None, doubts=None, questions=None, generated_by=None):
        """The agent's proposal for a candidate, kept on it so the person can decide in Odoo too."""
        item = self._agent_item(item_id)
        if action not in dict(PROPOSALS):
            raise UserError(self.env._("The proposed action is one of: %s.", ", ".join(dict(PROPOSALS))))
        Flag = self.env['memory.source.flag']
        codes = _names(doubts)
        flags = Flag.search([('code', 'in', codes)])
        unknown = sorted(set(codes) - set(flags.mapped('code')))
        if unknown:
            raise UserError(self.env._("Unknown doubts: %(unknown)s. The doubts are: %(all)s.",
                                       unknown=", ".join(unknown), all=", ".join(Flag.search([]).mapped('code'))))
        item.write({'proposal_action': action, 'proposal_theme_ids': [(6, 0, self._labels(themes, 'theme').ids)],
                    'proposal_abstract': card or False, 'proposal_flag_ids': [(6, 0, flags.ids)],
                    'proposal_questions': questions or False, 'proposal_on': fields.Datetime.now(),
                    'proposal_by': okf.actor(generated_by) or self.env.user.name})
        return item._agent_entry()

    @api.model
    def _agent_triage(self, item_ids, decision, themes=None, note=None):
        """Keep (as proposed, or with the themes and note given) or discard candidates."""
        items = self.browse([int(i) for i in item_ids or []]).exists()
        if not items:
            raise UserError(self.env._("No candidate to sort."))
        if decision == 'discard':
            items.action_discard()
        elif decision in ('keep', 'keep_as_proposed'):
            if decision == 'keep_as_proposed':
                items.action_keep_as_proposed()
            else:
                items.action_keep()
            vals = {}
            if themes:
                vals['theme_ids'] = [(4, tag.id) for tag in self._labels(themes, 'theme')]
            if note:
                vals['triage_note'] = note
            if vals:
                items.write(vals)
        else:
            raise UserError(self.env._("The decision is keep, keep_as_proposed or discard."))
        return [item._agent_entry() for item in items]

    @api.model
    def _agent_card(self, item_id, abstract, quotes=None, persons=None, bodies=None, places=None, themes=None,
                    acts=None, event_date=None, stance=None, relevance=None, keywords=None, related_ids=None,
                    submit=True):
        """Write the card of a kept candidate (a candidate is kept by writing its card), after the
        person's yes. Every quote must be in the page, word for word: the page is read now and
        not kept. A card that names persons goes to approval; the others are active."""
        item = self._agent_item(item_id)
        if item.state in ('active', 'to_approve') and item.approved_on:
            raise UserError(self.env._("«%s» is approved: a lead changes it, or sends it back.", item.title))
        if not (abstract or '').strip():
            raise UserError(self.env._("A card needs its abstract."))
        if stance and stance not in dict(STANCES):
            raise UserError(self.env._("The stance is one of: %s.", ", ".join(dict(STANCES))))
        if relevance and str(relevance) not in dict(RELEVANCE):
            raise UserError(self.env._("The relevance is 1, 2 or 3."))
        if quotes:
            item._check_quotes_in_page(quotes)
        vals = {'abstract': abstract.strip(), 'quotes': quotes or False, 'acts': acts or False,
                'keywords': ", ".join(_names(keywords)) or False}
        for key, value in (('persons', persons), ('bodies', bodies), ('places', places), ('themes', themes)):
            if value:
                field, kind = LABEL_FIELDS[key]
                vals[field] = [(6, 0, self._labels(value, kind).ids)]
        if event_date:
            vals['event_date'] = fields.Date.to_date(event_date)
        if stance:
            vals['stance'] = stance
        if relevance:
            vals['relevance'] = str(relevance)
        if related_ids:
            vals['related_ids'] = [(6, 0, self.browse([int(i) for i in related_ids]).exists().ids)]
        if item.state in ('candidate', 'discarded'):
            item.action_keep()
        item.write(vals)
        if submit:
            item.action_submit()
        return item._agent_entry()

    # -- helpers ------------------------------------------------------------------------
    @api.model
    def _agent_item(self, item_id):
        item = self.browse(int(item_id or 0)).exists()
        if not item or not item.has_access('read'):
            raise UserError(self.env._("Card %s does not exist or is not visible to you.", item_id))
        return item

    @api.model
    def _labels(self, names, kind):
        """The labels of these names and kind in the organisation, created when new."""
        Tag = self.env['memory.source.tag'].with_context(active_test=False)
        tags = Tag.browse()
        for name in _names(names):
            tag = Tag.search([('kind', '=', kind), ('name', '=ilike', name)], limit=1) or Tag.create(
                {'name': name, 'kind': kind})
            tags |= tag
        return tags

    def _check_quotes_in_page(self, quotes):
        """Refuse quotes that are not in the page of the card, word for word; a video has no text
        to check: its quotes come from the segments of whoever watched it."""
        self.ensure_one()
        if self.kind == 'video':
            return
        try:
            text = page_text(self.url)
        except (requests.RequestException, ValueError) as error:
            raise UserError(self.env._(
                "The page could not be read to check the quotes (%(error)s): write the card without quotes, or "
                "mark the doubt «quote».", error=str(error)[:200])) from error
        missing = missing_quotes(quotes, text)
        if missing:
            raise UserError(self.env._("Not in the page, word for word: %s. Correct the quotes or leave them out.",
                                       "; ".join(f"«{q}»" for q in missing)))


class MemorySourceChannel(models.Model):
    _inherit = 'memory.source.channel'

    def _agent_summary(self):
        return [{'id': c.id, 'name': c.name, 'kind': c.kind, 'website': c.website or None,
                 'look_for': c.watch_terms or None, 'every_days': c.frequency_days,
                 'last_read': fields.Datetime.to_string(c.last_read) if c.last_read else None,
                 'overdue': c.overdue, 'project': c.project_id.name or None,
                 'feeds': [{'kind': f.kind, 'url': f.url, 'outcome': f.last_outcome or None}
                           for f in c.feed_ids.filtered('active')]} for c in self]

    @api.model
    def _agent_due(self, project_id=None):
        """The channels overdue, of the organisation and of the project when given."""
        domain = [('overdue', '=', True)]
        if project_id:
            domain += ['|', ('project_id', '=', False), ('project_id', '=', int(project_id))]
        return self.search(domain)._agent_summary()

    @api.model
    def _agent_channel(self, name, website=None, kind='press', look_for=None, every_days=1, project_id=None,
                       feeds=None):
        """A new channel the person agreed to follow, with its feeds ({kind, url})."""
        channel = self.create({'name': name, 'website': website or False, 'kind': kind, 'watch_terms': look_for or False,
                               'frequency_days': int(every_days or 1),
                               'project_id': int(project_id) if project_id else False})
        for feed in feeds or []:
            self.env['memory.source.feed'].create({'channel_id': channel.id, 'kind': feed.get('kind') or 'rss',
                                                   'url': feed['url']})
        return channel._agent_summary()[0]
