# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The routes of the external sources, behind the Texo token, as the person: the same
triage the person does in Odoo. The MCP
server of texo_mcp exposes them as tools when this module is installed."""
from odoo import http
from odoo.http import request

from odoo.addons.texo.controllers.main import HUB_ROUTE


class TexoSourcesController(http.Controller):

    @http.route('/texo/v1/sources/due', readonly=True, **HUB_ROUTE)
    def due(self, project_id=None):
        request.env.user._texo_check_role()
        return request.env['memory.source.channel']._agent_due(project_id)

    @http.route('/texo/v1/sources/find', readonly=True, **HUB_ROUTE)
    def find(self, query=None, persons=None, themes=None, channel=None, date_from=None, date_to=None, states=None,
             limit=20):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_find(query, persons, themes, channel, date_from, date_to,
                                                             states, limit)

    @http.route('/texo/v1/sources/inbox', readonly=True, **HUB_ROUTE)
    def inbox(self, watched_only=False, limit=20):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_inbox(watched_only, limit)

    @http.route('/texo/v1/sources/collect', **HUB_ROUTE)
    def collect(self, channel_ids=None, overdue_only=True):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_collect(channel_ids, overdue_only)

    @http.route('/texo/v1/sources/search', **HUB_ROUTE)
    def search(self, query, channel_ids=None, limit=20, since=None):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_search(query, channel_ids, limit, since)

    @http.route('/texo/v1/sources/link', **HUB_ROUTE)
    def link(self, url, title=None):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_link(url, title)

    @http.route('/texo/v1/sources/propose', **HUB_ROUTE)
    def propose(self, item_id, action, themes=None, card=None, doubts=None, questions=None, generated_by=None):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_propose(item_id, action, themes, card, doubts, questions,
                                                                generated_by)

    @http.route('/texo/v1/sources/triage', **HUB_ROUTE)
    def triage(self, item_ids, decision, themes=None, note=None):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_triage(item_ids, decision, themes, note)

    @http.route('/texo/v1/sources/card', **HUB_ROUTE)
    def card(self, item_id, abstract, quotes=None, persons=None, bodies=None, places=None, themes=None, acts=None,
             event_date=None, stance=None, relevance=None, keywords=None, related_ids=None, submit=True):
        request.env.user._texo_check_role()
        return request.env['memory.source.item']._agent_card(
            item_id, abstract, quotes=quotes, persons=persons, bodies=bodies, places=places, themes=themes, acts=acts,
            event_date=event_date, stance=stance, relevance=relevance, keywords=keywords, related_ids=related_ids,
            submit=submit)

    @http.route('/texo/v1/sources/channel', **HUB_ROUTE)
    def channel(self, name, website=None, kind='press', look_for=None, every_days=1, project_id=None, feeds=None):
        request.env.user._texo_check_role()
        return request.env['memory.source.channel']._agent_channel(name, website, kind, look_for, every_days,
                                                                   project_id, feeds)
