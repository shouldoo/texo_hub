# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    'name': "Texo - Vector",
    'summary': "Vectors for the memory: a hybrid search over the episodes, facts, procedures, lessons and documents, and "
               "near-duplicates by meaning, with a local embedding service and pgvector",
    'license': 'LGPL-3',
    'author': "Daniele Lucarelli",
    'category': 'Services/Project',
    'version': '20.0.1.0.0',
    'website': "https://github.com/shouldoo/texo_hub",
    'depends': ['texo_memory'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/ir.access.csv',
        'data/ir_config_parameter_data.xml',
        'data/ir_cron_data.xml',
        'views/memory_vector_status_views.xml',
        'views/memory_review_views.xml',
        'data/memory_review_area_data.xml',
    ],
}
