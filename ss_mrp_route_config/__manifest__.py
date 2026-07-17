# -*- coding: utf-8 -*-
{
    'name': 'MRP Route Config',
    'version': '18.0.1.0.0',
    'summary': 'Configure dynamic Stock locations for MRP consumption, finished goods, and component pickings.',
    'description': """
SS MRP Route Config
======================
Allows configuring dynamic routes/locations for Manufacturing Orders and their component pickings.
Useful for routing raw materials and SFGs (e.g. Assembled cycles vs packing materials)
from distinct source locations to specific consumption/post-production lines (such as a Packing Line).
    """,
    'author': 'shivasamala',
    'category': 'Manufacturing',
    'depends': ['mrp', 'stock', 'product'],
    'data': [
        'security/mrp_route_config_security.xml',
        'security/ir.model.access.csv',
        'views/mrp_route_config_views.xml',
        'views/product_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
