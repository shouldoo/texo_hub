# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The episodes: a lexical search over the tasks.

The description and the chatter of a task are the episodic memory of a project: what was
asked, what was found, what was done. Until now they were reachable by id only, in the
pack of the task. This module keeps a full-text vector of every task (title, search keywords,
description, human messages of the chatter) and searches it with the same helper as the notes, the
lessons and the documents (fulltext.py), as the user: the record rules of project.task
decide which episodes exist.

The vector is a plain column kept by this module, not a generated one: a generated column
cannot read mail_message. Raw SQL on purpose: tsvector has no ORM form (memory_note does
the same).
"""
from odoo import api, models
from odoo.tools import html2plaintext

from odoo.addons.texo import okf

from . import fulltext

SNIPPET = 160
# the messages that tell the episode: what people wrote, not what Odoo tracked
EPISODE_MESSAGE_TYPES = ('comment', 'email', 'email_outgoing')
# characters of description and chatter that enter the vector: a tsvector is limited to a megabyte
MAX_TSV_TEXT = 200000
REFRESH_BATCH = 500


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def init(self):
        self.env.cr.execute("ALTER TABLE project_task ADD COLUMN IF NOT EXISTS texo_tsv tsvector")
        self.env.cr.execute(
            "CREATE INDEX IF NOT EXISTS project_task_texo_tsv_idx ON project_task USING gin (texo_tsv)")
        # the tasks of before this column get their vector once, at install or update
        self.env.cr.execute("SELECT id FROM project_task WHERE texo_tsv IS NULL ORDER BY id")
        ids = [row[0] for row in self.env.cr.fetchall()]
        for start in range(0, len(ids), REFRESH_BATCH):
            self.sudo().with_context(active_test=False).browse(ids[start:start + REFRESH_BATCH])._texo_refresh_tsv()

    # -- the vector -----------------------------------------------------------
    def _texo_episode_text(self):
        """{task id: plain text} of the description and the human messages of the chatter."""
        texts = {task.id: html2plaintext(task.description or '') for task in self}
        if self.ids:
            self.env['mail.message'].flush_model()
            self.env.cr.execute(
                "SELECT res_id, string_agg(body, ' ' ORDER BY id) FROM mail_message "
                "WHERE model = 'project.task' AND res_id IN %s AND message_type IN %s GROUP BY res_id",
                (tuple(self.ids), EPISODE_MESSAGE_TYPES))
            for res_id, bodies in self.env.cr.fetchall():
                texts[res_id] += ' ' + html2plaintext(bodies or '')
        return texts

    def _texo_refresh_tsv(self):
        """Compute the vector of these tasks: the title with weight A, the search keywords with
        weight B (as the keywords of notes and lessons: a session note measured on the seed
        found its episode only when its keywords outweighed a long chatter), the description
        and the chatter in the three configurations of fulltext."""
        if not self:
            return
        self.flush_recordset(['name', 'description', 'texo_keywords'])
        texts = self._texo_episode_text()
        for task in self:
            text = " ".join(texts[task.id].split())[:MAX_TSV_TEXT]
            keywords = task.texo_keywords or ''
            self.env.cr.execute(
                "UPDATE project_task SET texo_tsv = setweight(to_tsvector('simple', %s), 'A') || "
                "setweight(to_tsvector('simple', %s) || to_tsvector('italian', %s) || to_tsvector('english', %s), 'B') || "
                "to_tsvector('simple', %s) || to_tsvector('italian', %s) || to_tsvector('english', %s) WHERE id = %s",
                (task.name or '', keywords, keywords, keywords, text, text, text, task.id))

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        tasks._texo_refresh_tsv()
        return tasks

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'description', 'texo_keywords'} & set(vals):
            self._texo_refresh_tsv()
        return result

    # -- the search -----------------------------------------------------------
    @api.model
    def _texo_search(self, query, related_terms=None, limit=5):
        """The tasks the user may read, ranked by full-text search over title, description and
        chatter: first those that hold every word (a long word also as a prefix), then, only
        to fill the limit, those that hold some (fulltext.rank). Archived tasks stay out, and
        so do the tasks without a project: personal to-dos are not episodes of the work."""
        limit = max(1, min(int(limit or 5), 20))
        tasks, ranked = fulltext.search(self, 'project_task', 'texo_tsv', fulltext.words(query, related_terms),
                                        limit, self._texo_search_domain(),
                                        where="texo_tsv IS NOT NULL AND project_id IS NOT NULL")
        return tasks._texo_search_entries(ranked)

    @api.model
    def _texo_search_domain(self):
        return [('project_id', '!=', False)]

    def _texo_search_entries(self, ranked):
        """The search results of these tasks, in this order: the summary, the title, the concept
        id, the score and the words (fulltext.fields of ranked) and the first words of the
        description, flagged as tasks."""
        return [dict(summary, title=task.name, task=True, concept=okf.concept_id(task), **fulltext.fields(ranked, task.id),
                     snippet=" ".join(html2plaintext(task.description or '').split())[:SNIPPET])
                for task, summary in zip(self, self._texo_summary(), strict=True)]
