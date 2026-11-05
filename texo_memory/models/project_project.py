# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from odoo import models


class ProjectProject(models.Model):
    """A project template can come from the seed of an industry."""
    _name = 'project.project'
    _inherit = ['project.project', 'memory.seed.mixin']
