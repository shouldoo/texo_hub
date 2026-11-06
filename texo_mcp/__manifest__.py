# Copyright 2026 Daniele Lucarelli
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
{
    'name': "Texo - MCP",
    'summary': "The memory of Texo as a remote MCP server: the same tools for any MCP client, "
               "with the person's token",
    'license': 'LGPL-3',
    'author': "Daniele Lucarelli",
    'category': 'Services/Project',
    'version': '20.0.1.0.2',
    'website': "https://github.com/shouldoo/texo_hub",
    'depends': ['texo_memory'],
    'data': [
        'security/ir.access.csv',
        'views/oauth_templates.xml',
        'views/oauth_views.xml',
    ],
}
