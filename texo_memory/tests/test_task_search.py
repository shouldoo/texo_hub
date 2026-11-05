# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.tests import tagged

from .common import MemoryCase


@tagged('post_install', '-at_install')
class TestTaskSearch(MemoryCase):
    """The episodes: the title, the description and the chatter of a task, searched with the
    scope tasks by whoever may read the task."""

    def search(self, user, query, **kwargs):
        return self.env['memory.note'].with_user(user)._agent_search(query, scope='tasks', **kwargs)

    def test_found_by_description_and_by_the_chatter(self):
        found = self.search(self.member, 'dedicated route')
        self.assertEqual([r['id'] for r in found], [self.task.id])
        self.assertEqual((found[0]['task'], found[0]['concept'], found[0]['title']),
                         (True, f"tasks/{self.task.id}", 'Returns route'))
        self.assertEqual(found[0]['snippet'], "Handle customer returns with a dedicated route.")
        self.task.with_user(self.member)._texo_post_note(
            "Il reso finiva nello stock libero: la regola push della sotto-ubicazione era ereditata.")
        self.assertEqual([r['id'] for r in self.search(self.member, 'regola push ereditata')], [self.task.id],
                         "a word of the chatter finds the episode")
        self.assertEqual([r['id'] for r in self.search(self.member, 'sotto-ubicaz')], [self.task.id], "a prefix too")
        self.assertEqual(self.env['memory.note'].with_user(self.member)._agent_search('regola push ereditata'), [],
                         "the episodes are not part of all: the memory is one thing, the work another")
        self.assertEqual(self.search(self.member, ''), [])

    def test_every_word_first_then_some(self):
        other = self.env['project.task'].create({
            'name': 'Batch imports', 'project_id': self.project.id,
            'description': '<p>Importing the returns file in batch blocks the worker.</p>'})
        self.assertEqual([r['id'] for r in self.search(self.member, 'returns batch')], [other.id, self.task.id],
                         "every word first, then the tasks with some to fill the limit")
        self.assertEqual([r['id'] for r in self.search(self.member, 'returns batch', limit=1)], [other.id])

    def test_the_keywords_weigh_above_the_chatter(self):
        """A session note measured on the seed: the words of a paraphrase match only some of the
        words of a long episode, and the keywords of the note must lift it above the others."""
        chatty = self.env['project.task'].create({
            'name': 'Inventory sync', 'project_id': self.project.id,
            'description': '<p>' + ' '.join(['Stock snapshot export for the warehouse.'] * 20) + '</p>'})
        self.assertEqual([r['id'] for r in self.search(self.member, 'snapshot mensile')], [chatty.id])
        self.task.with_user(self.member)._texo_post_note(
            "Il cliente non trovava la fotografia di fine mese del magazzino.", keywords=['snapshot mensile', 'giacenze'])
        found = self.search(self.member, 'snapshot mensile')
        self.assertEqual([r['id'] for r in found], [self.task.id, chatty.id],
                         "every word in the keywords of the note, before a task with some of them many times")
        self.assertEqual([r['id'] for r in self.search(self.member, 'giacenze')], [self.task.id])
        self.task.sudo().write({'texo_keywords': False})
        self.assertEqual(self.search(self.member, 'giacenze'), [], "the vector follows the keywords")

    def test_only_the_tasks_the_user_may_read(self):
        self.assertEqual(self.search(self.outsider, 'dedicated route'), [],
                         "a followers-only project: its tasks do not exist for who is not on it")
        self.project.write({'allowed_internal_user_ids': [Command.link(self.outsider.id)]})
        self.assertEqual([r['id'] for r in self.search(self.outsider, 'dedicated route')], [self.task.id])

    def test_the_vector_follows_the_text(self):
        self.task.write({'description': '<p>Handle supplier complaints with a dedicated inbox.</p>'})
        self.assertEqual([r['id'] for r in self.search(self.member, 'complaints inbox')], [self.task.id])
        self.assertEqual(self.search(self.member, 'customer'), [], "the old words are gone")
        self.assertEqual([r['id'] for r in self.search(self.member, 'returns route')], [self.task.id], "the title stays")
        message = self.env['mail.message'].browse(
            self.task.with_user(self.member)._texo_post_note("Visto in call con il referente: ok.")['message_id'])
        self.assertEqual([r['id'] for r in self.search(self.member, 'referente')], [self.task.id])
        message.sudo().unlink()
        self.assertEqual(self.search(self.member, 'referente'), [], "a deleted message leaves the episode")
        self.task.action_archive()
        self.assertEqual(self.search(self.member, 'complaints inbox'), [], "an archived task is not an episode")

    def test_a_personal_todo_is_not_an_episode(self):
        self.env['project.task'].with_user(self.member).create({
            'name': 'Welcome to-do', 'description': '<p>A dedicated route for my own notes.</p>'})
        self.assertEqual([r['id'] for r in self.search(self.member, 'dedicated route')], [self.task.id],
                         "a task without a project is a personal to-do, not an episode of the work")

    def test_tracking_messages_are_not_the_episode(self):
        self.task.message_post(body="stage changed to Done", message_type='notification')
        self.assertEqual(self.search(self.member, 'Done'), [], "what Odoo tracks is not what people wrote")

    def test_init_indexes_the_tasks_of_before(self):
        self.env.cr.execute("UPDATE project_task SET texo_tsv = NULL WHERE id = %s", (self.task.id,))
        self.assertEqual(self.search(self.member, 'dedicated route'), [])
        self.env['project.task'].init()
        self.assertEqual([r['id'] for r in self.search(self.member, 'dedicated route')], [self.task.id])
