# -*- coding: utf-8 -*-
{
    'name': 'Zunax IT Ticketing & Routing',
    'version': '18.0.1.0.0',
    'category': 'IT Support',
    'summary': 'IT department ticketing tool with auto-routing, portal access, and email/WhatsApp resolution alerts',
    'author': 'zunax',
    'company': 'Zunax Energy Products LLP',
    'website': 'https://www.zunax.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'portal',
        'website'
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'views/it_department_views.xml',
        'views/it_cancellation_reason_views.xml',
        'wizard/it_ticket_cancel_wizard_views.xml',
        'views/it_ticket_subject_views.xml',
        'views/it_ticket_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
