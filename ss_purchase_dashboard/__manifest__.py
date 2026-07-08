# -*- coding: utf-8 -*-
{
    'name': 'Purchase Dashboard',
    'version': '1.0',
    'summary': 'Interactive Procurement & Purchase Dashboard',
    'description': """
        A  OWL-based Purchase Dashboard providing visibility into:
        1. PR, RFQ, and PO Process Statuses
        2. Outstanding Liabilities & Aging
        3. Vendor Performance
        4. Material Availability Risk
        5. Monthly Spend Analysis
    """,
    'category': 'Purchases',
    'author': 'zunax',
    'depends': ['purchase', 'stock', 'account', 'employee_purchase_requisition'],
    'data': [
        'security/ir.model.access.csv',
        'views/purchase_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ss_purchase_dashboard/static/src/css/purchase_dashboard.css',
            'ss_purchase_dashboard/static/src/xml/purchase_dashboard.xml',
            'ss_purchase_dashboard/static/src/js/purchase_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
