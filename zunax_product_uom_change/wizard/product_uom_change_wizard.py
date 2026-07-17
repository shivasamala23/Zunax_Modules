# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ProductUomChangeWizard(models.TransientModel):
    _name = 'product.uom.change.wizard'
    _description = 'Product UoM Change Wizard'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        required=True,
        ondelete='cascade',
        domain="[('type', '=', 'consu')]"
    )
    current_uom_id = fields.Many2one(
        'uom.uom',
        string='Current Default UoM',
        readonly=True
    )
    current_po_uom_id = fields.Many2one(
        'uom.uom',
        string='Current Purchase UoM',
        readonly=True
    )
    new_uom_id = fields.Many2one(
        'uom.uom',
        string='New Default UoM',
        required=True
    )
    new_po_uom_id = fields.Many2one(
        'uom.uom',
        string='New Purchase UoM',
        required=True
    )
    conversion_type = fields.Selection([
        ('direct', 'Direct (1:1 Update - keep quantity numbers)'),
        ('factor', 'Convert (Apply conversion factor to quantities)')
    ], string='Conversion Type', required=True, default='direct')
    factor = fields.Float(
        string='Conversion Factor',
        default=1.0,
        required=True,
        help="Multiplier for quantities: New Quantity = Old Quantity * Factor. Unit Price = Old Price / Factor. For example, if 1 Box = 10 Units, the factor is 10.0."
    )

    @api.model
    def default_get(self, fields_list):
        res = super(ProductUomChangeWizard, self).default_get(fields_list)
        active_id = self.env.context.get('active_id')
        active_model = self.env.context.get('active_model')
        if active_id and active_model == 'product.template':
            product_tmpl = self.env['product.template'].browse(active_id)
            res.update({
                'product_tmpl_id': product_tmpl.id,
                'current_uom_id': product_tmpl.uom_id.id,
                'current_po_uom_id': product_tmpl.uom_po_id.id,
                'new_uom_id': product_tmpl.uom_id.id,
                'new_po_uom_id': product_tmpl.uom_po_id.id,
            })
        return res

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        if self.product_tmpl_id:
            self.current_uom_id = self.product_tmpl_id.uom_id.id
            self.current_po_uom_id = self.product_tmpl_id.uom_po_id.id
            self.new_uom_id = self.product_tmpl_id.uom_id.id
            self.new_po_uom_id = self.product_tmpl_id.uom_po_id.id

    @api.onchange('new_uom_id')
    def _onchange_new_uom_id(self):
        if self.new_uom_id:
            self.new_po_uom_id = self.new_uom_id.id

    def action_change_uom(self):
        self.ensure_one()
        # Security check: must be stock manager
        if not self.env.user.has_group('stock.group_stock_manager'):
            raise UserError(_("Only Inventory Managers can perform this operation."))

        # Category check
        if self.new_uom_id.category_id != self.new_po_uom_id.category_id:
            raise UserError(_(
                "The default Unit of Measure and the purchase Unit of Measure must be in the same category.\n\n"
                "In Odoo, you cannot mix UoM categories (e.g., Units and Weight) on the same product because Odoo must be able to convert quantities between them. "
                "To purchase in KGS and store/sell in NOS, please do the following:\n"
                "1. Go to Inventory -> Configuration -> UoM Categories and create a new category (e.g., 'NOS to KGS').\n"
                "2. Create two UoMs in this new category: one for KGS (e.g., as the Reference Unit) and one for NOS (e.g., defining the conversion ratio, e.g. 1 NOS = 0.5 KGS).\n"
                "3. In this UoM change wizard, select your new custom NOS and KGS UoMs (since they are now in the same UoM Category, they will pass this check successfully)."
            ))

        product_tmpl = self.product_tmpl_id
        product_ids = product_tmpl.product_variant_ids.ids

        if not product_ids:
            # If no variants, just update product template directly via SQL (no stock moves anyway)
            self.env.cr.execute(
                "UPDATE product_template SET uom_id = %s, uom_po_id = %s WHERE id = %s",
                (self.new_uom_id.id, self.new_po_uom_id.id, product_tmpl.id)
            )
            self.env['product.template'].invalidate_model(fnames=['uom_id', 'uom_po_id'])
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Unit of Measure updated successfully.'),
                    'type': 'success',
                    'sticky': False,
                }
            }

        # Determine conversion factor
        factor = self.factor if self.conversion_type == 'factor' else 1.0
        if factor <= 0:
            raise UserError(_("Conversion factor must be greater than zero."))

        cr = self.env.cr

        # Helper function to check table existence
        def table_exists(table_name):
            cr.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)", (table_name,))
            return cr.fetchone()[0]

        # 1. Update product_template
        cr.execute(
            "UPDATE product_template SET uom_id = %s, uom_po_id = %s WHERE id = %s",
            (self.new_uom_id.id, self.new_po_uom_id.id, product_tmpl.id)
        )

        product_ids_tuple = tuple(product_ids)

        # 2. Update stock_move
        if table_exists('stock_move'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE stock_move 
                    SET product_uom = %s, 
                        product_uom_qty = product_uom_qty * %s, 
                        quantity = quantity * %s, 
                        price_unit = price_unit / %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, factor, factor, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE stock_move 
                    SET product_uom = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, product_ids_tuple)
                )

        # 3. Update stock_move_line
        if table_exists('stock_move_line'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE stock_move_line 
                    SET product_uom_id = %s, 
                        quantity = quantity * %s, 
                        quantity_product_uom = quantity_product_uom * %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, factor, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE stock_move_line 
                    SET product_uom_id = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, product_ids_tuple)
                )

        # 4. Update stock_quant
        if table_exists('stock_quant'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE stock_quant 
                    SET quantity = quantity * %s, 
                        reserved_quantity = reserved_quantity * %s 
                    WHERE product_id IN %s
                    """,
                    (factor, factor, product_ids_tuple)
                )

        # 5. Update purchase_order_line
        if table_exists('purchase_order_line'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE purchase_order_line 
                    SET product_uom = %s, 
                        product_qty = product_qty * %s, 
                        price_unit = price_unit / %s, 
                        qty_received = qty_received * %s, 
                        qty_invoiced = qty_invoiced * %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_po_uom_id.id, factor, factor, factor, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE purchase_order_line 
                    SET product_uom = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_po_uom_id.id, product_ids_tuple)
                )

        # 6. Update sale_order_line
        if table_exists('sale_order_line'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE sale_order_line 
                    SET product_uom = %s, 
                        product_uom_qty = product_uom_qty * %s, 
                        price_unit = price_unit / %s, 
                        qty_delivered = qty_delivered * %s, 
                        qty_invoiced = qty_invoiced * %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, factor, factor, factor, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE sale_order_line 
                    SET product_uom = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, product_ids_tuple)
                )

        # 7. Update account_move_line
        if table_exists('account_move_line'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE account_move_line 
                    SET product_uom_id = %s, 
                        quantity = quantity * %s, 
                        price_unit = price_unit / %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, factor, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE account_move_line 
                    SET product_uom_id = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, product_ids_tuple)
                )

        # 8. Update stock_valuation_layer
        if table_exists('stock_valuation_layer'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE stock_valuation_layer 
                    SET quantity = quantity * %s, 
                        remaining_qty = remaining_qty * %s, 
                        unit_cost = unit_cost / %s 
                    WHERE product_id IN %s
                    """,
                    (factor, factor, factor, product_ids_tuple)
                )

        # 9. Update mrp_bom
        if table_exists('mrp_bom'):
            cr.execute(
                """
                UPDATE mrp_bom 
                SET product_uom_id = %s 
                WHERE product_tmpl_id = %s OR product_id IN %s
                """,
                (self.new_uom_id.id, product_tmpl.id, product_ids_tuple)
            )

        # 10. Update mrp_bom_line
        if table_exists('mrp_bom_line'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE mrp_bom_line 
                    SET product_uom_id = %s, 
                        product_qty = product_qty * %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE mrp_bom_line 
                    SET product_uom_id = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, product_ids_tuple)
                )

        # 11. Update mrp_production
        if table_exists('mrp_production'):
            if factor != 1.0:
                cr.execute(
                    """
                    UPDATE mrp_production 
                    SET product_uom_id = %s, 
                        product_qty = product_qty * %s, 
                        qty_producing = qty_producing * %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, factor, factor, product_ids_tuple)
                )
            else:
                cr.execute(
                    """
                    UPDATE mrp_production 
                    SET product_uom_id = %s 
                    WHERE product_id IN %s
                    """,
                    (self.new_uom_id.id, product_ids_tuple)
                )

        # Invalidate cache for modified models
        self.env['product.template'].invalidate_model()
        self.env['product.product'].invalidate_model()
        if table_exists('stock_move'):
            self.env['stock.move'].invalidate_model()
        if table_exists('stock_move_line'):
            self.env['stock.move.line'].invalidate_model()
        if table_exists('stock_quant'):
            self.env['stock.quant'].invalidate_model()
        if table_exists('purchase_order_line'):
            self.env['purchase.order.line'].invalidate_model()
        if table_exists('sale_order_line'):
            self.env['sale.order.line'].invalidate_model()
        if table_exists('account_move_line'):
            self.env['account.move.line'].invalidate_model()
        if table_exists('stock_valuation_layer'):
            self.env['stock.valuation.layer'].invalidate_model()
        if table_exists('mrp_bom'):
            self.env['mrp.bom'].invalidate_model()
        if table_exists('mrp_bom_line'):
            self.env['mrp.bom.line'].invalidate_model()
        if table_exists('mrp_production'):
            self.env['mrp.production'].invalidate_model()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Unit of Measure and all transaction history updated successfully.'),
                'type': 'success',
                'sticky': False,
            }
        }
