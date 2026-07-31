# -*- coding: utf-8 -*-

from odoo import models, fields

class ItCancellationReason(models.Model):
    _name = 'it.cancellation.reason'
    _description = 'IT Ticket Cancellation Reason'
    _order = 'name'

    name = fields.Char(string='Reason', required=True, translate=True)
    active = fields.Boolean(default=True)
