# -*- coding: utf-8 -*-
{
    'name': 'Zunax Inventory Dashboard',
    'version': '1.0',
    'summary': 'Interactive Inventory Status and Aging Dashboard same like Purchase Dashboard',
    'description': """
        A premium OWL-based Inventory Dashboard providing dynamic KPI metrics:
        1. Opening Value
        2. GRN Value
        3. Closing Value
        4. Stock Issue Value
        5. Stock Aging metrics (0-30 days, 31-90 days, 91-180 days, Above 180 days)
    """,
    'category': 'Inventory',
    'author': 'zunax',
    'depends': ['stock', 'purchase', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'views/inventory_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'zunax_inventory_dashboard/static/src/css/inventory_dashboard.css',
            'zunax_inventory_dashboard/static/src/xml/inventory_dashboard.xml',
            'zunax_inventory_dashboard/static/src/js/inventory_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
