# -*- coding: utf-8 -*-
{
    'name': 'Sale Dashboard',
    'version': '1.0',
    'summary': 'Interactive Sales & Collection Dashboard',
    'description': """
        A premium OWL-based Sales & Collection Dashboard providing visibility into:
        1. Daily Sales
        2. MTD Sales
        3. Target vs Achievement (with Monthly targets management)
        4. Region-wise Sales
        5. Product-wise Sales
        6. Collection Today
        7. Outstanding Collections
        8. Overdue Outstanding
    """,
    'category': 'Sales',
    'author': 'ss_zunax',
    'depends': ['sale_management','account_reports', 'stock', 'account', 'zunax_credit_limit'],
    'data': [
        'security/sale_target_security.xml',
        'security/ir.model.access.csv',
        'views/sale_target_views.xml',
        'views/sale_segment_target_views.xml',
        'views/sale_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ss_sale_dashboard/static/src/css/sale_dashboard.css',
            'ss_sale_dashboard/static/src/xml/sale_dashboard.xml',
            'ss_sale_dashboard/static/src/js/sale_dashboard.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'AGPL-3',
}
