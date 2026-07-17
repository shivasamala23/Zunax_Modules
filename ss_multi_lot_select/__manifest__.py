# -*- coding: utf-8 -*-
{
    'name': 'Multi Lot/Serial Selection in Deliveries',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Select multiple lot/serial numbers at once in delivery order details',
    'description': """
Multi Lot/Serial Selection in Delivery Orders
=============================================

This module adds a "Select Multiple Lots/Serials" button in the Details popup
of stock move lines (inside Delivery Orders). Instead of adding one lot per line,
users can now open a dialog, check all desired lot/serial numbers, and add them
all at once — automatically creating one move line per selected lot/serial.

Features:
- Multi-checkbox selection of available lots/serials
- Filtered by product and source location
- Works in both outgoing deliveries and internal transfers
- Respects existing lot/serial tracking settings
    """,
    'author': 'Zunax',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'wizard/stock_lot_multiselect_wizard_views.xml',
        'views/stock_move_views_inherit.xml',
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto_install': False,
    'application': False,
}
