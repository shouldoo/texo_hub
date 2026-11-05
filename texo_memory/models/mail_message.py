# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import api, models

from .project_task import EPISODE_MESSAGE_TYPES


class MailMessage(models.Model):
    """A message in the chatter of a task is part of its episode: the vector of the task
    follows it."""
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        messages = super().create(vals_list)
        messages._texo_tasks()._texo_refresh_tsv()
        return messages

    def write(self, vals):
        before = self._texo_tasks() if 'res_id' in vals or 'model' in vals else self.env['project.task']
        result = super().write(vals)
        if 'body' in vals or 'res_id' in vals or 'model' in vals:
            (before | self._texo_tasks())._texo_refresh_tsv()
        return result

    def unlink(self):
        tasks = self._texo_tasks()
        result = super().unlink()
        tasks._texo_refresh_tsv()
        return result

    def _texo_tasks(self):
        """The tasks these messages tell about, whoever wrote them."""
        ids = {message.res_id for message in self
               if message.model == 'project.task' and message.message_type in EPISODE_MESSAGE_TYPES}
        # sudo: the vector of a task is kept whoever writes in its chatter, a portal user too
        return self.env['project.task'].sudo().with_context(active_test=False).browse(list(ids)).exists()
