# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
from . import controllers
from . import models


def post_init_hook(env):
    """Every company of the instance gets its home project at the installation."""
    env['res.company']._texo_ensure_homes()
