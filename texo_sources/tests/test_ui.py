# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import SourcesCase


@tagged('post_install', '-at_install')
class TestSourcesUi(SourcesCase):
    """The external sources in the review of the people and on the form of the project."""

    def item(self, url, **vals):
        return self.env['memory.source.item'].create(dict(
            {'channel_id': self.channel.id, 'url': url, 'title': 'The council meets'}, **vals))

    def test_the_review_has_the_queues_of_the_sources(self):
        today = fields.Date.context_today(self.env['memory.source.item'])
        self.item('https://news.example.com/new')
        self.item('https://news.example.com/old', state='active', abstract='The council met.',
                  review_date=today - timedelta(days=1))
        review = self.env['memory.review'].with_user(self.lead).create({})
        self.assertEqual(review.source_candidates, 1)
        self.assertEqual(review.source_due, 1)
        self.assertEqual(review.source_channels_overdue, 1, "a channel never read is overdue")
        action = review.with_context(queue='source_candidates').action_open_queue()
        self.assertEqual(action['res_model'], 'memory.source.item')
        self.assertEqual(action['domain'], [('state', '=', 'candidate')])
        triage = self.env.ref('texo_sources.action_memory_source_triage')
        self.assertEqual(action['id'], triage.id, "the candidates open in the views of the triage")
        self.assertEqual(self.env['memory.review'].with_user(self.member).create({}).source_to_approve, 0)

    def test_the_dashboard_has_the_area_of_the_sources(self):
        """The area of the sources: the cards to approve as the big button (0 for a member, who does not
        approve), the other queues as lines."""
        self.item('https://news.example.com/new')
        self.item('https://news.example.com/named', state='to_approve', abstract='The mayor spoke.')
        Area = self.env['memory.review.area']
        lead = Area.with_user(self.lead).search([('code', '=', 'sources')])
        self.assertEqual((lead.main_count, lead.source_candidates, lead.source_channels_overdue), (1, 1, 1))
        self.assertEqual(lead.pending, 3)
        self.assertEqual(lead.action_open_main()['id'],
                         self.env.ref('texo_sources.action_memory_source_to_approve').id)
        self.item('https://news.example.com/kept', state='todo')
        lead.invalidate_recordset()
        self.assertEqual((lead.source_to_write, lead.pending), (1, 4), "a card kept and not written yet")
        member = Area.with_user(self.member).search([('code', '=', 'sources')])
        self.assertEqual((member.main_count, member.source_candidates), (0, 1), "the member sorts, the lead approves")

    def test_the_cards_are_approved_from_the_list(self):
        """Approve, in the actions of the list: the same check as the button of the card."""
        first = self.item('https://news.example.com/a', state='to_approve', abstract='The mayor spoke.')
        second = self.item('https://news.example.com/b', state='to_approve', abstract='The council voted.')
        candidate = self.item('https://news.example.com/c')
        approve = self.env.ref('texo_sources.action_server_memory_source_approve')
        self.assertEqual(approve.binding_model_id.model, 'memory.source.item')
        self.assertIn(self.env.ref('texo.group_texo_lead'), approve.group_ids)
        cards = first | second | candidate
        with self.assertRaises(AccessError):
            approve.with_user(self.member).with_context(active_model=cards._name, active_ids=cards.ids).run()
        self.assertEqual(set(cards.mapped('state')), {'to_approve', 'candidate'})
        approve.with_user(self.lead).with_context(active_model=cards._name, active_ids=cards.ids).run()
        self.assertEqual((first.state, second.state, candidate.state), ('active', 'active', 'candidate'),
                         "a candidate is sorted first, never approved")
        self.assertEqual(first.approved_by_id, self.lead)

    def test_the_project_counts_its_cards(self):
        self.channel.project_id = self.project
        self.item('https://news.example.com/card', state='active', abstract='The council met.')
        self.item('https://news.example.com/candidate')
        project = self.project.with_user(self.member)
        self.assertEqual(project.texo_source_count, 1, "the cards, not the candidates")
        action = project.action_texo_source_cards()
        self.assertEqual(self.env['memory.source.item'].with_user(self.member).search_count(action['domain']), 1)
