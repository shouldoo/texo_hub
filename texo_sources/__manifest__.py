# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    'name': "Texo - External Sources",
    'summary': "What others publish, in the memory: channels to follow, feeds read on request, triage, "
               "structured cards with their people, themes and dates, approval",
    'license': 'LGPL-3',
    'author': "Daniele Lucarelli",
    'category': 'Services/Project',
    'version': '20.0.1.0.0',
    'website': "https://github.com/shouldoo/texo_hub",
    'depends': ['texo_memory'],
    'data': [
        'security/ir.access.csv',
        'data/memory_source_flag_data.xml',
        'data/ir_cron_data.xml',
        'views/memory_source_tag_views.xml',
        'views/memory_source_item_views.xml',
        'views/memory_source_channel_views.xml',
        'views/memory_source_menus.xml',
        'views/memory_review_views.xml',
        'data/memory_review_area_data.xml',
    ],
}
