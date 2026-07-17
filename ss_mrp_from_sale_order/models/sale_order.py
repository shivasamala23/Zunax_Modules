# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    custom_mrp_production_ids = fields.One2many(
        'mrp.production', 
        'sale_order_id', 
        string='Custom Manufacturing Orders'
    )
    custom_mrp_production_count = fields.Integer(
        string='Custom MO Count', 
        compute='_compute_custom_mrp_production_count'
    )

    @api.depends('custom_mrp_production_ids')
    def _compute_custom_mrp_production_count(self):
        for order in self:
            order.custom_mrp_production_count = len(order.custom_mrp_production_ids)

    def action_confirm(self):
        # Call super first to let standard Odoo confirmation complete
        res = super(SaleOrder, self).action_confirm()

        MrpProduction = self.env['mrp.production']
        MrpBom = self.env['mrp.bom']

        for order in self:
            for line in order.order_line:
                # Only check goods/storables with BoM
                if not line.product_id or line.product_id.type == 'service':
                    continue

                # Find the appropriate Bill of Materials (BoM)
                bom = MrpBom._bom_find(line.product_id)[line.product_id]
                if not bom:
                    continue

                # Avoid duplicate MO creation: check if any MO is already linked to this SO Line
                domain = [('sale_line_id', '=', line.id)]
                if order.name and order.name != 'New':
                    domain = ['|'] + domain + [
                        '&',
                        ('origin', '=', order.name),
                        ('product_id', '=', line.product_id.id)
                    ]
                existing_mo = MrpProduction.search(domain, limit=1)

                if existing_mo:
                    continue

                # Calculate quantity to produce based on shortage (Ordered Qty - Qty on Hand)
                qty_needed = line.product_uom_qty
                qty_available = line.product_id.qty_available or 0.0
                qty_to_produce = qty_needed - max(0.0, qty_available)

                if qty_to_produce > 0.0:
                    picking_type = self.env['stock.picking.type'].search([
                        ('code', '=', 'mrp_operation'),
                        ('company_id', '=', order.company_id.id)
                    ], limit=1)
                    if not picking_type:
                        picking_type = self.env['stock.picking.type'].search([
                            ('code', '=', 'mrp_operation'),
                            ('company_id', '=', False)
                        ], limit=1)
                    if not picking_type:
                        raise UserError(_("No active Manufacturing operation type found for company %s. Please configure a Manufacturing operation type in Inventory settings.") % order.company_id.name)

                    mo_vals = {
                        'product_id': line.product_id.id,
                        'bom_id': bom.id,
                        'product_qty': qty_to_produce,
                        'product_uom_id': line.product_uom.id,
                        'origin': order.name,
                        'sale_order_id': order.id,
                        'sale_line_id': line.id,
                        'company_id': order.company_id.id,
                        'picking_type_id': picking_type.id,
                    }
                    
                    mo = MrpProduction.create(mo_vals)
                    # Automatically confirm the manufacturing order
                    mo.action_confirm()

        return res

    def action_view_custom_mrp_production(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        if self.custom_mrp_production_count > 1:
            action['domain'] = [('id', 'in', self.custom_mrp_production_ids.ids)]
        elif self.custom_mrp_production_ids:
            action['views'] = [(self.env.ref('mrp.mrp_production_form_view').id, 'form')]
            action['res_id'] = self.custom_mrp_production_ids.id
            action['type'] = 'ir.actions.act_window'
        else:
            action = {'type': 'ir.actions.act_window_close'}
        return action
