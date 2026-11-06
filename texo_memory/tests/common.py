# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import Command
from odoo.tests.common import TransactionCase

CLEAN_FINDING = ("Porting a purchase module from 18.0 to 20.0: the order line unit field is product_uom "
                 "on 18.0 and uom_id on 20.0, so views and domains built on the old name fail to load.")
CLEAN_SOLUTION = ("Rename the field to uom_id in Python, views, domains and tests, and convert quantities "
                  "with _compute_quantity between the move and the line unit.")


def sector_activities(env):
    """The activities a sector adds through the seed of its pack, as the tests use them:
    the module itself ships only analysis and communication."""
    Activity = env['memory.note.activity']
    for sequence, code in enumerate(('code', 'deploy', 'migration'), start=30):
        if not Activity.search_count([('code', '=', code)]):
            Activity.create({'name': code.capitalize(), 'code': code, 'sequence': sequence})


def clear_home(env):
    """The organisation without the notes and documents of the demo data: the tests write
    their own."""
    env['memory.note'].search([('company_id', '!=', False)]).unlink()
    env['ir.attachment'].search([('res_model', '=', 'res.company'), '|', ('texo_document', '=', True),
                                 ('texo_text_of_id', '!=', False)]).unlink()


class MemoryFixtures:
    """The people, the customer, the project and the task of the tests, for a transaction or
    an HTTP case."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        clear_home(cls.env)
        sector_activities(cls.env)
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        project_user = Command.link(cls.env.ref('project.group_project_user').id)
        cls.member = Users.create({
            'name': 'Member', 'login': 'chm_member',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id), project_user]})
        cls.lead = Users.create({
            'name': 'Lead', 'login': 'chm_lead',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_lead').id), project_user]})
        cls.outsider = Users.create({
            'name': 'Outsider', 'login': 'chm_outsider',
            'group_ids': [Command.link(cls.env.ref('texo.group_texo_member').id), project_user]})
        cls.customer = cls.env['res.partner'].create({'name': 'Rossi Meccanica', 'is_company': True})
        # A followers-only project is readable by its team (allowed_internal_user_ids), not by every employee.
        cls.project = cls.env['project.project'].create({
            'name': 'Warehouse flows', 'partner_id': cls.customer.id, 'privacy_visibility': 'followers',
            'user_id': cls.lead.id, 'allowed_internal_user_ids': [Command.link(cls.member.id), Command.link(cls.lead.id)],
        })
        cls.project.message_subscribe(partner_ids=(cls.member.partner_id | cls.lead.partner_id).ids)
        cls.task = cls.env['project.task'].create({
            'name': 'Returns route', 'project_id': cls.project.id, 'user_ids': [Command.link(cls.member.id)],
            'description': '<p>Handle customer returns with a dedicated route.</p>',
        })

    def note_as(self, user, **kwargs):
        """A rule written as user, on the project unless the call gives its own anchor."""
        vals = {'name': 'No production', 'body': 'Agents never upgrade a module on the production database.'}
        if not any(key in kwargs for key in ('task_id', 'project_id', 'partner_id')):
            vals['project_id'] = self.project.id
        vals.update(kwargs)
        return self.env['memory.note'].with_user(user)._agent_note(**vals)


class MemoryCase(MemoryFixtures, TransactionCase):
    pass
