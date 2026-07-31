# -*- coding: utf-8 -*-

from odoo import models, fields

class ItTicketSubject(models.Model):
    _name = 'it.ticket.subject'
    _description = 'IT Ticket Predefined Subject'
    _order = 'name'

    name = fields.Char(string='Subject Name', required=True, translate=True)
    department_id = fields.Many2one(
        'it.department',
        string='IT Department',
        required=True,
        help='The IT department that will handle issues for this subject'
    )
    active = fields.Boolean(default=True)
