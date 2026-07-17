# -*- coding: utf-8 -*-
{
    'name': 'Zunax Product UoM Change with History',
    'version': '18.0.1.0.0',
    'summary': 'Allows changing the Unit of Measure of a product even after it has moving history.',
    'description': """
This module adds a wizard that enables Inventory Managers to safely change a product's default and purchase Units of Measure
even after there are stock movements. It updates all historical transactions (stock moves, stock move lines, quants, PO lines, SO lines, invoice lines) to prevent database mismatch and conversion crashes.
    """,
    'category': 'Inventory',
    'author': 'Zunax',
    'depends': [
        'product',
        'stock',
        'purchase',
        'sale',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/product_uom_change_wizard_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
