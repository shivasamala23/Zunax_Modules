# -*- coding: utf-8 -*-
{
    'name': 'MRP From Sale Order',
    'version': '18.0.1.0.0',
    'summary': 'Automatically generate Manufacturing Orders from confirmed Sales Orders.',
    'description': """
SS MRP From Sale Order
=========================
Automatically triggers Manufacturing Orders when a Sales Order is confirmed.
    """,
    'author': 'shivasamala',
    'category': 'Manufacturing',
    'depends': ['sale', 'mrp', 'sale_mrp'],
    'data': [
        'views/sale_order_views.xml',
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
