# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    'name': "Texo - Memory",
    'summary': "Project memory for agents: contexts, decisions, events and client-free lessons, behind the Texo token",
    'license': 'LGPL-3',
    'author': "Daniele Lucarelli",
    'category': 'Services/Project',
    'version': '20.0.1.3.0',
    'website': "https://github.com/shouldoo/texo_hub",
    'depends': ['texo_project'],
    'data': [
        'security/ir.access.csv',
        'data/memory_note_activity_data.xml',
        'data/memory_section_data.xml',
        'data/memory_review_area_data.xml',
        'views/memory_note_views.xml',
        'views/memory_note_activity_views.xml',
        'views/memory_document_views.xml',
        'views/memory_lesson_views.xml',
        'views/memory_optout_name_views.xml',
        'views/memory_links_views.xml',
        'wizard/memory_search_views.xml',
        'wizard/memory_review_views.xml',
        'views/memory_review_area_views.xml',
        'views/memory_menus.xml',
        'wizard/memory_optout_wizard_views.xml',
        'data/ir_cron_data.xml',
    ],
    'demo': [
        'demo/memory_demo.xml',
    ],
}
