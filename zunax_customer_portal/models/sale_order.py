# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    portal_note = fields.Text(
        string='Customer Note',
        help='Note from customer when requesting quotation via portal',
    )

    # ─── Portal-facing computed fields ───────────────────────────────────────

    portal_shipment_status = fields.Char(
        string='Shipment Status',
        compute='_compute_portal_shipment_status',
        store=False,
    )
    portal_shipment_label = fields.Char(
        string='Shipment Label',
        compute='_compute_portal_shipment_status',
        store=False,
    )
    portal_tracking_url = fields.Char(
        string='Tracking URL',
        compute='_compute_portal_shipment_status',
        store=False,
    )

    @api.depends('picking_ids', 'picking_ids.state')
    def _compute_portal_shipment_status(self):
        for order in self:
            pickings = order.picking_ids.filtered(
                lambda p: p.picking_type_code == 'outgoing'
            )
            if not pickings:
                order.portal_shipment_status = 'no_shipment'
                order.portal_shipment_label = 'No Shipment'
                order.portal_tracking_url = False
            else:
                # Take the last outgoing picking
                picking = pickings.sorted('id', reverse=True)[0]
                state_map = {
                    'draft': ('waiting', 'Waiting'),
                    'confirmed': ('confirmed', 'Confirmed'),
                    'waiting': ('waiting', 'Waiting'),
                    'assigned': ('ready', 'Ready to Ship'),
                    'done': ('done', 'Delivered'),
                    'cancel': ('cancel', 'Cancelled'),
                }
                status_key, label = state_map.get(picking.state, ('waiting', 'In Progress'))
                order.portal_shipment_status = status_key
                order.portal_shipment_label = label
                # carrier tracking url — only exists if delivery module installed
                tracking_url = False
                if hasattr(picking, 'carrier_tracking_url'):
                    tracking_url = picking.carrier_tracking_url
                order.portal_tracking_url = tracking_url or False


    def get_portal_order_lines_data(self):
        """Return order lines as list of dicts for portal rendering."""
        self.ensure_one()
        lines = []
        for line in self.order_line:
            lines.append({
                'product_name': line.product_id.display_name,
                'description': line.name or '',
                'qty': line.product_uom_qty,
                'uom': line.product_uom.name if line.product_uom else '',
                'unit_price': line.price_unit,
                'subtotal': line.price_subtotal,
            })
        return lines
