# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""The memory of a work record, from its form: the people find the rules, facts, procedures,
documents and lessons of a project, a customer, the organisation or a task where they work,
with a button, counted and opened with their own access."""
from odoo import fields, models

MEMBER = 'texo.group_texo_member'
LIVE = ('draft', 'active')


class TexoMemoryLinks(models.AbstractModel):
    """The buttons of the memory on a record that anchors notes: _texo_anchor_field is
    the field of memory.note that points to it."""
    _name = 'texo.memory.links'
    _description = "Texo: Memory of a Record"
    _texo_anchor_field = None

    texo_note_count = fields.Integer(string="Memory", compute='_compute_texo_counts',
                                              groups=MEMBER)
    texo_document_count = fields.Integer(string="Memory Documents", compute='_compute_texo_counts',
                                                  groups=MEMBER)

    def _compute_texo_counts(self):
        anchor = self._texo_anchor_field
        notes = dict(self.env['memory.note']._read_group(
            [(anchor, 'in', self.ids), ('state', 'in', LIVE)], [anchor], ['__count']))
        documents = dict(self.env['ir.attachment']._read_group(
            [('texo_document', '=', True), ('res_model', '=', self._name), ('res_id', 'in', self.ids)],
            ['res_id'], ['__count']))
        for record in self:
            record.texo_note_count = notes.get(record, 0)
            record.texo_document_count = documents.get(record.id, 0)

    def action_texo_notes(self):
        self.ensure_one()
        anchor = self._texo_anchor_field
        return {'type': 'ir.actions.act_window', 'name': self.env._("Memory of %s", self.display_name),
                'res_model': 'memory.note', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')],
                'domain': [(anchor, '=', self.id)],
                'context': {'search_default_group_kind': 1, 'search_default_active': 1, f'default_{anchor}': self.id,
                            'default_kind': 'fact'}}

    def action_texo_documents(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('texo_memory.action_memory_document')
        action.update(name=self.env._("Documents of %s", self.display_name),
                      domain=[('texo_document', '=', True), ('res_model', '=', self._name),
                              ('res_id', '=', self.id)],
                      context={})
        return action


class ProjectProject(models.Model):
    _name = 'project.project'
    _inherit = ['project.project', 'texo.memory.links']
    _texo_anchor_field = 'project_id'

    texo_lesson_count = fields.Integer(string="Lessons", compute='_compute_texo_lesson_count',
                                                groups=MEMBER)

    def _compute_texo_lesson_count(self):
        Lesson = self.env['memory.lesson']
        for project in self:
            project.texo_lesson_count = Lesson.search_count(project._texo_lesson_domain())

    def _texo_lesson_domain(self):
        """The lessons of the pack of the project: live, sharing a tag with it."""
        return self.env['memory.lesson']._live_domain() + [('tag_ids', 'in', self.tag_ids.ids)]

    def action_texo_lessons(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._("Lessons for %s", self.display_name),
                'res_model': 'memory.lesson', 'view_mode': 'list,form', 'views': [(False, 'list'), (False, 'form')],
                'domain': self._texo_lesson_domain(), 'context': {}}


class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'texo.memory.links']
    _texo_anchor_field = 'partner_id'


class ResCompany(models.Model):
    _name = 'res.company'
    _inherit = ['res.company', 'texo.memory.links']
    _texo_anchor_field = 'company_id'


class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'texo.memory.links']
    _texo_anchor_field = 'task_id'

    texo_note_ids = fields.One2many('memory.note', 'task_id', string="Facts and Procedures of the Task",
                                             groups=MEMBER)
