# -*- coding: utf-8 -*-
from odoo import models, fields

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    sale_order_id = fields.Many2one(
        'sale.order',
        string='Source Sale Order',
        copy=False,
        readonly=True
    )
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Source Sale Order Line',
        copy=False,
        readonly=True
    )
