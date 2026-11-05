# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import http
from odoo.exceptions import MissingError, UserError
from odoo.http import request

from odoo.addons.texo import okf
from odoo.addons.texo.controllers.main import HUB_ROUTE, as_okf


class TexoProjectController(http.Controller):

    def _task(self, task_id):
        """The task if the user may read it; the same 404 otherwise, so ids are not enumerable."""
        task = request.env['project.task'].browse(int(task_id)).exists()
        if not task or not task.has_access('read'):
            raise MissingError(request.env._("Task %(id)s does not exist or is not visible to you.", id=task_id))
        return task

    def _project(self, project_id):
        project = request.env['project.project'].browse(int(project_id)).exists()
        if not project or not project.has_access('read'):
            raise MissingError(request.env._("Project %(id)s does not exist or is not visible to you.", id=project_id))
        return project

    @http.route('/texo/v1/project/my_work', readonly=True, **HUB_ROUTE)
    def my_work(self, limit=50):
        request.env.user._texo_check_role()
        return request.env['project.task']._texo_my_work(limit)

    @http.route('/texo/v1/project/task', readonly=True, **HUB_ROUTE)
    def task(self, task_id, messages=10, format='json'):
        request.env.user._texo_check_role()
        task = self._task(task_id)
        if as_okf(format):
            path = okf.concept_id(task)
            return okf.bundle([(f"{path}.md", task._okf_concept()), (f"{path}/log.md", task._okf_log(messages))])
        return task._texo_context(messages)

    @http.route('/texo/v1/project/task_note', **HUB_ROUTE)
    def task_note(self, task_id, body, keywords=None):
        request.env.user._texo_check_role()
        return self._task(task_id)._texo_post_note(body, keywords)

    @http.route('/texo/v1/project/project', readonly=True, **HUB_ROUTE)
    def project(self, project_id, format='json'):
        request.env.user._texo_check_role()
        project = self._project(project_id)
        if as_okf(format):
            return okf.bundle([(f"{okf.concept_id(project)}.md", project._okf_concept())])
        return project._texo_context()

    @http.route('/texo/v1/project/log', readonly=True, **HUB_ROUTE)
    def log(self, project_id=None, task_id=None, limit=20):
        """The history of a project (its updates, the milestones reached) or of a task (its
        chatter), newest first, as an OKF log.md."""
        request.env.user._texo_check_role()
        if task_id:
            record = self._task(task_id)
        elif project_id:
            record = self._project(project_id)
        else:
            raise UserError(request.env._("The log of a project or of a task."))
        return okf.bundle([(f"{okf.concept_id(record)}/log.md", record._okf_log(limit))])

    @http.route('/texo/v1/project/update', **HUB_ROUTE)
    def update(self, project_id, name, status, description, progress=None):
        request.env.user._texo_check_role()
        return self._project(project_id)._texo_write_update(name, status, description, progress)
