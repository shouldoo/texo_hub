# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    'name': "Texo",
    'summary': "Identity, access tokens and configuration of Texo, managed in Odoo",
    'license': 'LGPL-3',
    'author': "Daniele Lucarelli",
    'category': 'Technical',
    'version': '20.0.1.2.0',
    'website': "https://github.com/shouldoo/texo_hub",
    'depends': ['base'],
    'data': [
        'security/texo_security.xml',
        'security/ir.access.csv',
        'views/res_users_apikeys_views.xml',
        'views/texo_config_views.xml',
        'data/ir_config_parameter_data.xml',
    ],
}
