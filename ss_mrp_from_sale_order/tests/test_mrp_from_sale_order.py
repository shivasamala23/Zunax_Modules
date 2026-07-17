# -*- coding: utf-8 -*-
from odoo.tests import common

class TestMrpFromSaleOrder(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestMrpFromSaleOrder, cls).setUpClass()
        
        # Add creator/editor groups to test user to bypass custom zunax_partner_product_access_control constraints
        creator_group = cls.env.ref('zunax_partner_product_access_control.group_partner_creator', raise_if_not_found=False)
        if creator_group:
            cls.env.user.write({'groups_id': [(4, creator_group.id)]})
        editor_group = cls.env.ref('zunax_partner_product_access_control.group_partner_editor', raise_if_not_found=False)
        if editor_group:
            cls.env.user.write({'groups_id': [(4, editor_group.id)]})

        # Create a product to manufacture
        cls.product = cls.env['product.product'].create({
            'name': 'Manufactured Product',
            'type': 'consu',
            'is_storable': True,
        })
        
        # Create a raw component
        cls.component = cls.env['product.product'].create({
            'name': 'Raw Component',
            'type': 'consu',
            'is_storable': True,
        })

        # Create a BoM for the product
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.product.product_tmpl_id.id,
            'product_qty': 1,
            'type': 'normal',
            'bom_line_ids': [
                (0, 0, {'product_id': cls.component.id, 'product_qty': 2})
            ]
        })

        # Create a partner for the Sale Order
        cls.partner = cls.env['res.partner'].create({
            'name': 'Test Customer',
        })

        # Find the default warehouse stock location
        warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        if not warehouse:
            warehouse = cls.env['stock.warehouse'].create({
                'name': 'Test Warehouse',
                'code': 'TWH',
                'company_id': cls.env.company.id,
            })
        cls.stock_location = warehouse.lot_stock_id

        # Ensure there is an active mrp_operation picking type for the company
        picking_type = cls.env['stock.picking.type'].search([
            ('code', '=', 'mrp_operation'),
            ('company_id', '=', cls.env.company.id)
        ], limit=1)
        if not picking_type:
            inactive_pt = cls.env['stock.picking.type'].with_context(active_test=False).search([
                ('code', '=', 'mrp_operation'),
                ('company_id', '=', cls.env.company.id)
            ], limit=1)
            if inactive_pt:
                inactive_pt.write({'active': True})
            else:
                cls.env['stock.picking.type'].create({
                    'name': 'Manufacturing',
                    'code': 'mrp_operation',
                    'warehouse_id': warehouse.id,
                    'sequence_code': 'MO',
                    'company_id': cls.env.company.id,
                })

    def test_auto_mo_creation_on_so_confirm(self):
        """Verify that confirming a Sale Order automatically creates an MO for the shortage"""
        # Ensure initial stock is 0
        self.assertEqual(self.product.qty_available, 0.0)

        # Create a Sale Order for 5 units
        sale_order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id,
                    'product_uom_qty': 5.0,
                })
            ]
        })

        # Confirm the Sale Order
        sale_order.action_confirm()

        # Check that a Manufacturing Order was created for 5 units
        mo = self.env['mrp.production'].search([
            ('sale_order_id', '=', sale_order.id),
            ('product_id', '=', self.product.id),
        ])
        
        self.assertTrue(mo, "Manufacturing Order should be created")
        self.assertEqual(mo.product_qty, 5.0, "MO quantity should match Sale Order quantity when stock is 0")
        self.assertEqual(mo.state, 'confirmed', "MO should be in 'confirmed' state")

        # Now test with stock on hand
        # Adjust stock of the product to 2 units
        quant = self.env['stock.quant'].with_context(inventory_mode=True).create({
            'product_id': self.product.id,
            'location_id': self.stock_location.id,
            'inventory_quantity': 2.0,
        })
        quant.action_apply_inventory()
        self.assertEqual(self.product.qty_available, 2.0)

        sale_order_2 = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [
                (0, 0, {
                    'product_id': self.product.id,
                    'product_uom_qty': 10.0,
                })
            ]
        })

        sale_order_2.action_confirm()

        # It should create an MO for the shortage: 10 - 2 = 8 units
        mo_2 = self.env['mrp.production'].search([
            ('sale_order_id', '=', sale_order_2.id),
            ('product_id', '=', self.product.id),
        ])
        
        self.assertTrue(mo_2, "Manufacturing Order should be created for the shortage")
        self.assertEqual(mo_2.product_qty, 8.0, "MO quantity should be 8.0 (10 ordered - 2 available)")
