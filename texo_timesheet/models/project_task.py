# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import fields, models
from odoo.exceptions import UserError

MAX_HOURS = 24
MAX_DESCRIPTION = 500
WORKLOG_LINES = 10


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def _texo_log_time(self, hours, description, date=None):
        """One timesheet line on the task, as the calling user. The hours are the
        person's, never the agent's estimate; the description is the worklog line."""
        self.ensure_one()
        try:
            hours = float(hours)
        except (TypeError, ValueError) as error:
            raise UserError(self.env._("Hours must be a number.")) from error
        if not 0 < hours <= MAX_HOURS:
            raise UserError(self.env._("Hours must be between 0 and %s.", MAX_HOURS))
        description = (description or '').strip() if isinstance(description, str) else ''
        if not description or len(description) > MAX_DESCRIPTION:
            raise UserError(self.env._("The description is empty or longer than %s characters.", MAX_DESCRIPTION))
        if not self.env.user.employee_id:
            raise UserError(self.env._("You have no employee record: hours cannot be logged."))
        line = self.env['account.analytic.line'].create({
            'task_id': self.id, 'project_id': self.project_id.id, 'name': description,
            'unit_amount': hours, 'date': fields.Date.to_date(date) if date else fields.Date.context_today(self),
        })
        return {'timesheet_id': line.id, 'task_id': self.id, 'hours': hours,
                'date': fields.Date.to_string(line.date), 'task_hours': self.effective_hours}

    def _texo_context(self, messages=10):
        context = super()._texo_context(messages)
        lines = self.timesheet_ids.sorted(key=lambda l: (l.date, l.id), reverse=True)[:WORKLOG_LINES]
        context['worklog'] = [{
            'date': fields.Date.to_string(line.date), 'hours': line.unit_amount,
            'who': line.employee_id.name or line.user_id.name or None, 'what': line.name,
        } for line in lines]
        context['hours'] = {'spent': self.effective_hours, 'allocated': self.allocated_hours}
        return context
