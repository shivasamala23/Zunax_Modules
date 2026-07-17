# -*- coding: utf-8 -*-
from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    original_order_id = fields.Many2one(
        'sale.order',
        string='Original Sale Order',
        readonly=True,
        copy=False,
        index=True
    )
    split_order_ids = fields.One2many(
        'sale.order',
        'original_order_id',
        string='Split Child Orders'
    )
    split_order_count = fields.Integer(
        string='Split Orders Count',
        compute='_compute_split_order_count'
    )

    @api.depends('split_order_ids')
    def _compute_split_order_count(self):
        for order in self:
            order.split_order_count = len(order.split_order_ids)

    def action_view_split_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("sale.action_orders")
        action['domain'] = [('id', 'in', self.split_order_ids.ids)]
        action['context'] = {'create': False}
        return action
