{
    'name': 'Non-Moving Goods Aged Report',
    'version': '0.1',
    'category': 'Inventory/Inventory',
    'summary': 'Aged report of non-moving inventory products inside Inventory Reporting menu',
    'author': 'shivasamala',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'security/non_moving_goods_report_security.xml',
        'views/non_moving_goods_report_views.xml',
    ],
    'installable': True,
    'application': False,
}
