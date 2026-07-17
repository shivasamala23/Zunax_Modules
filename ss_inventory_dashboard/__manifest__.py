# -*- coding: utf-8 -*-
{
    'name': 'Inventory Report Dashboard',
    'version': '1.0',
    'summary': 'Interactive Inventory Status, Ledger, Ageing & Pending PO Dashboard',
    'description': """
        A premium OWL-based Inventory Report Dashboard providing visibility into:
        1. Inventory Status Report (Opening, Receipts, Issues, Closing Qty & Value)
        2. Stock Ledger Report (Supplier & Item wise transaction history)
        3. Ageing Analysis (FIFO-based stock aging buckets: 30, 60, 90, 120, 150, 180, 360, Above 360 Days)
        4. Pending Purchase Order Status Report (Supplier & Item wise balance quantities)
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
            'ss_inventory_dashboard/static/src/css/inventory_dashboard.css',
            'ss_inventory_dashboard/static/src/xml/inventory_dashboard.xml',
            'ss_inventory_dashboard/static/src/js/inventory_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
