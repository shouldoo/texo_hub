# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    'name': "Texo - Project",
    'summary': "Task context, my work and chatter notes for agents, behind the Texo token",
    'license': 'LGPL-3',
    'author': "Daniele Lucarelli",
    'category': 'Services/Project',
    'version': '20.0.1.1.0',
    'website': "https://github.com/shouldoo/texo_hub",
    'depends': ['texo', 'project'],
    'data': [
        'views/project_project_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': True,
}
