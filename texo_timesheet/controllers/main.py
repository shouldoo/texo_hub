# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import http
from odoo.http import request

from odoo.addons.texo.controllers.main import HUB_ROUTE
from odoo.addons.texo_project.controllers.main import TexoProjectController


class TexoTimesheetController(http.Controller):

    @http.route('/texo/v1/project/log_time', **HUB_ROUTE)
    def log_time(self, task_id, hours, description, date=None):
        request.env.user._texo_check_role()
        task = TexoProjectController._task(self, task_id)
        return task._texo_log_time(hours, description, date)
