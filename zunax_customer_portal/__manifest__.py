# -*- coding: utf-8 -*-
{
    'name': 'Zunax Customer Portal',
    'version': '18.0.1.0.0',
    'summary': 'Customer Portal: Ledger, Invoices, Payments, Orders, Quotation Requests & Shipment Tracking',
    'description': """
Zunax Customer Portal
=====================
Provides portal customers with a full self-service dashboard:
- Customer Ledger (paginated + Excel download)
- Invoices & Payments
- Sale Quotation Requests (create from portal)
- Order status tracking
- Real-time Shipment / Delivery tracking
""",
    'author': 'Zunax Energy Products LLP',
    'category': 'Sales/Portal',
    'license': 'LGPL-3',
    'depends': [
        'sale',
        'account',
        'stock',
        'portal',
        'website',
        'zunax_portal_user',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/portal_dashboard.xml',
        'views/portal_ledger.xml',
        'views/portal_quotations.xml',
        'views/portal_orders.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
