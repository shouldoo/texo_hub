# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The hooks of the models of the scope: a write that changes a text, or moves a record in or out of
the scope, marks the record pending (memory.embedding.pending), and the cron of the vectors reads the
pending records only. The fields that matter are those the texts are made of and those the scope is
decided by (memory_embedding._sources); a deletion marks the record too, so its rows go."""
from odoo import api, models

from odoo.addons.texo_memory.models.project_task import EPISODE_MESSAGE_TYPES

TASK_FIELDS = {'name', 'description', 'texo_keywords', 'active', 'project_id', 'is_template'}
NOTE_FIELDS = {'name', 'body', 'keywords', 'kind', 'state'}
LESSON_FIELDS = {'name', 'keywords', 'finding', 'solution', 'state'}


def touch(records, res_model=None):
    records.env['memory.embedding.pending']._touch(res_model or records._name, records.ids)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        touch(tasks)
        return tasks

    def write(self, vals):
        result = super().write(vals)
        if TASK_FIELDS & set(vals):
            touch(self)
        return result

    def unlink(self):
        touch(self)
        return super().unlink()


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        touch(messages._texo_tasks(), 'project.task')
        return messages

    def write(self, vals):
        before = self._texo_tasks() if 'res_id' in vals or 'model' in vals else self.env['project.task']
        result = super().write(vals)
        if 'body' in vals or 'res_id' in vals or 'model' in vals:
            touch(before | self._texo_tasks(), 'project.task')
        return result

    def unlink(self):
        tasks = self._texo_tasks()
        result = super().unlink()
        touch(tasks, 'project.task')
        return result

    def _texo_tasks(self):
        """The tasks these messages tell about, whoever wrote them (texo_memory defines it: here for the
        message types the vectors index, the same)."""
        ids = {message.res_id for message in self
               if message.model == 'project.task' and message.message_type in EPISODE_MESSAGE_TYPES}
        return self.env['project.task'].sudo().with_context(active_test=False).browse(list(ids)).exists()


class MemoryNote(models.Model):
    _inherit = 'memory.note'

    @api.model_create_multi
    def create(self, vals_list):
        notes = super().create(vals_list)
        touch(notes)
        return notes

    def write(self, vals):
        result = super().write(vals)
        if NOTE_FIELDS & set(vals):
            touch(self)
        return result

    def unlink(self):
        touch(self)
        return super().unlink()


class MemoryLesson(models.Model):
    _inherit = 'memory.lesson'

    @api.model_create_multi
    def create(self, vals_list):
        lessons = super().create(vals_list)
        touch(lessons)
        return lessons

    def write(self, vals):
        result = super().write(vals)
        if LESSON_FIELDS & set(vals):
            touch(self)
        return result

    def unlink(self):
        touch(self)
        return super().unlink()


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _texo_refresh_tsv(self):
        """The search vector of a document follows its title, summary, keywords, text and state (texo_memory):
        so do its vectors, and those of its passages, cut again there."""
        super()._texo_refresh_tsv()
        touch(self)

    def unlink(self):
        documents = self.filtered('texo_document')
        touch(documents)
        return super().unlink()
