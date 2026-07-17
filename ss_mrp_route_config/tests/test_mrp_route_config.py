# -*- coding: utf-8 -*-
from odoo.tests import common
from odoo.exceptions import ValidationError

class TestMrpRouteConfig(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestMrpRouteConfig, cls).setUpClass()
        import logging
        logger = logging.getLogger(__name__)

        logger.warning("TEST SETUP: env.company = %s", cls.env.company)
        logger.warning("TEST SETUP: env.companies = %s", cls.env.companies)
        logger.warning("TEST SETUP: all companies = %s", cls.env['res.company'].search([]))
        logger.warning("TEST SETUP: all warehouses = %s", cls.env['stock.warehouse'].search([]))

        # Add creator/editor groups to test user to bypass custom access constraints if any
        creator_group = cls.env.ref('zunax_partner_product_access_control.group_partner_creator', raise_if_not_found=False)
        if creator_group:
            cls.env.user.write({'groups_id': [(4, creator_group.id)]})
        editor_group = cls.env.ref('zunax_partner_product_access_control.group_partner_editor', raise_if_not_found=False)
        if editor_group:
            cls.env.user.write({'groups_id': [(4, editor_group.id)]})

        # Find default warehouse and stock location
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        if not cls.warehouse:
            cls.warehouse = cls.env['stock.warehouse'].search([], limit=1)
        
        # Check all stock rules
        rules = cls.env['stock.rule'].sudo().search([])
        logger.warning("TEST SETUP: total stock rules = %s", len(rules))
        for r in rules:
            logger.warning("RULE: name=%s, action=%s, route=%s, src=%s, dest=%s, procure_method=%s",
                           r.name, r.action, r.route_id.name, r.location_src_id.name, r.location_dest_id.name, r.procure_method)
        
        cls.stock_location = cls.warehouse.lot_stock_id

        # Enable 3-step manufacture on warehouse
        cls.warehouse.manufacture_steps = 'pbm_sam'
        
        # Ensure the manufacturing picking type is active and has a valid sequence
        mrp_pt = cls.env['stock.picking.type'].sudo().with_context(active_test=False).search([
            ('code', '=', 'mrp_operation'),
            ('warehouse_id', '=', cls.warehouse.id)
        ], limit=1)
        if mrp_pt:
            mrp_pt.write({'active': True})
            if not mrp_pt.sequence_id:
                seq = cls.env['ir.sequence'].sudo().search([('code', '=', 'mrp.production')], limit=1)
                if not seq:
                    seq = cls.env['ir.sequence'].sudo().create({
                        'name': 'Manufacturing Sequence',
                        'code': 'mrp.production',
                        'prefix': 'MO/',
                        'padding': 5,
                        'company_id': cls.env.company.id,
                    })
                mrp_pt.write({'sequence_id': seq.id})

        # Create custom locations
        cls.loc_assembly_post = cls.env['stock.location'].create({
            'name': 'Assembly Post-Production',
            'location_id': cls.stock_location.location_id.id,
            'usage': 'internal',
        })
        cls.loc_store = cls.env['stock.location'].create({
            'name': 'Raw Material Store',
            'location_id': cls.stock_location.location_id.id,
            'usage': 'internal',
        })
        cls.loc_pre_prod_packing = cls.env['stock.location'].create({
            'name': 'Pre-production Packing',
            'location_id': cls.stock_location.location_id.id,
            'usage': 'internal',
        })
        cls.loc_post_prod_packing = cls.env['stock.location'].create({
            'name': 'Post-production Packing',
            'location_id': cls.stock_location.location_id.id,
            'usage': 'internal',
        })

        # Create products
        cls.sfg_cycle = cls.env['product.product'].create({
            'name': 'Assembled Cycle SFG',
            'type': 'consu',
            'is_storable': True,
        })
        cls.raw_packing = cls.env['product.product'].create({
            'name': 'Packing Materials Raw',
            'type': 'consu',
            'is_storable': True,
        })
        cls.fg_cycle = cls.env['product.product'].create({
            'name': 'Packed Cycle FG',
            'type': 'consu',
            'is_storable': True,
        })

        # Create MRP Route Configuration
        cls.route_config = cls.env['mrp.route.config'].create({
            'name': 'Packing Line Route Config',
            'consumption_location_id': cls.loc_pre_prod_packing.id,
            'dest_location_id': cls.loc_post_prod_packing.id,
            'line_ids': [
                (0, 0, {
                    'product_id': cls.sfg_cycle.id,
                    'source_location_id': cls.loc_assembly_post.id,
                }),
                (0, 0, {
                    'product_id': cls.raw_packing.id,
                    'source_location_id': cls.loc_store.id,
                })
            ]
        })

        # Assign Route Config to FG product
        cls.fg_cycle.write({
            'mrp_route_config_id': cls.route_config.id
        })

        # Create BOM for Finished Product
        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.fg_cycle.product_tmpl_id.id,
            'product_qty': 1.0,
            'type': 'normal',
            'bom_line_ids': [
                (0, 0, {
                    'product_id': cls.sfg_cycle.id,
                    'product_qty': 1.0,
                }),
                (0, 0, {
                    'product_id': cls.raw_packing.id,
                    'product_qty': 2.0,
                })
            ]
        })

    def test_mrp_route_configuration(self):
        """Test that manufacturing locations and component pickings resolve dynamically."""
        import logging
        logger = logging.getLogger(__name__)
        
        # 1. Create a Manufacturing Order
        mo = self.env['mrp.production'].create({
            'product_id': self.fg_cycle.id,
            'bom_id': self.bom.id,
            'product_qty': 5.0,
        })
        
        logger.warning("TEST MO: initial src=%s, dest=%s", mo.location_src_id.display_name, mo.location_dest_id.display_name)
        for move in mo.move_raw_ids:
            logger.warning("TEST MO MOVE BEFORE CONFIRM: product=%s, loc_src=%s, loc_dest=%s, procure_method=%s",
                           move.product_id.name, move.location_id.display_name, move.location_dest_id.display_name, move.procure_method)

        # Verify default computed locations on MO match route config
        self.assertEqual(mo.location_src_id, self.loc_pre_prod_packing, "MO source location should be custom pre-production.")
        self.assertEqual(mo.location_dest_id, self.loc_post_prod_packing, "MO destination location should be custom post-production.")

        # Verify component moves (raw moves) locations
        raw_move_sfg = mo.move_raw_ids.filtered(lambda m: m.product_id == self.sfg_cycle)
        raw_move_raw = mo.move_raw_ids.filtered(lambda m: m.product_id == self.raw_packing)
        self.assertEqual(raw_move_sfg.location_id, self.loc_pre_prod_packing)
        self.assertEqual(raw_move_raw.location_id, self.loc_pre_prod_packing)

        # 2. Confirm the MO to trigger PBM and SAM pickings
        mo.action_confirm()
        
        # Trigger push rules on finished move manually to simulate generation of SAM picking
        for move in mo.move_finished_ids:
            if not move._skip_push():
                move._push_apply()
        
        logger.warning("TEST MO CONFIRMED: state=%s, pickings=%s", mo.state, mo.picking_ids)
        for move in mo.move_raw_ids:
            logger.warning("TEST MO MOVE AFTER CONFIRM: product=%s, loc_src=%s, loc_dest=%s, procure_method=%s, move_origs=%s",
                           move.product_id.name, move.location_id.display_name, move.location_dest_id.display_name, move.procure_method, move.move_orig_ids)

        # Verify pickings generated for components
        pickings = mo.picking_ids
        self.assertTrue(pickings, "Pickings should be generated.")

        # Verify picking moves locations
        pbm_moves = pickings.move_ids.filtered(lambda m: m.location_dest_id == self.loc_pre_prod_packing)
        self.assertTrue(pbm_moves, "Component picking moves to Pre-production Packing should exist.")

        pbm_sfg = pbm_moves.filtered(lambda m: m.product_id == self.sfg_cycle)
        pbm_raw = pbm_moves.filtered(lambda m: m.product_id == self.raw_packing)

        # SFG picking move source should be custom: Assembly Post-Prod
        self.assertEqual(pbm_sfg.location_id, self.loc_assembly_post, "SFG should be picked from Assembly Post-production.")
        # Raw materials picking move source should be custom: Store
        self.assertEqual(pbm_raw.location_id, self.loc_store, "Raw materials should be picked from Store.")

        # Verify store finished move (SAM) location
        finished_move = mo.move_finished_ids.filtered(lambda m: m.product_id == self.fg_cycle)
        self.assertEqual(finished_move.location_dest_id, self.loc_post_prod_packing)

        chained_sam_moves = finished_move.move_dest_ids
        self.assertFalse(chained_sam_moves, "Chained Finished Goods storage move should NOT be created because a Route Config with dest_location_id is active.")

    def test_default_resolution_fallback(self):
        """Test the default resolution fallback logic when no custom route line matches."""
        # 1. Create categories
        categ_sfg = self.env['product.category'].create({
            'name': 'Semi Finished Good (SFG)',
            'category_prefix': 'SFG_T',
        })
        categ_raw = self.env['product.category'].create({
            'name': 'Raw Materials',
            'category_prefix': 'RAW_T',
        })

        # 2. Create products representing different categories
        prod_plate = self.env['product.product'].create({
            'name': 'Lead Plate SFG',
            'categ_id': categ_sfg.id,
            'type': 'consu',
            'is_storable': True,
        })
        prod_spine = self.env['product.product'].create({
            'name': 'Alloy Spine Component',
            'categ_id': categ_sfg.id,
            'type': 'consu',
            'is_storable': True,
        })
        prod_container = self.env['product.product'].create({
            'name': 'Battery Container Lid',
            'categ_id': categ_sfg.id,
            'type': 'consu',
            'is_storable': True,
        })
        prod_charging = self.env['product.product'].create({
            'name': 'Charging Component',
            'categ_id': categ_sfg.id,
            'type': 'consu',
            'is_storable': True,
        })
        prod_general_sfg = self.env['product.product'].create({
            'name': 'General Frame SFG',
            'categ_id': categ_sfg.id,
            'type': 'consu',
            'is_storable': True,
        })
        prod_raw = self.env['product.product'].create({
            'name': 'Raw Acid Chemical',
            'categ_id': categ_raw.id,
            'type': 'consu',
            'is_storable': True,
        })

        # 3. Create a finished product (battery) that uses these components
        prod_battery = self.env['product.product'].create({
            'name': 'Test Battery FG',
            'type': 'consu',
            'is_storable': True,
        })
        
        # 4. Create a Bill of Materials (BOM)
        bom_battery = self.env['mrp.bom'].create({
            'product_tmpl_id': prod_battery.product_tmpl_id.id,
            'product_qty': 1.0,
            'type': 'normal',
            'bom_line_ids': [
                (0, 0, {'product_id': prod_plate.id, 'product_qty': 1.0}),
                (0, 0, {'product_id': prod_spine.id, 'product_qty': 1.0}),
                (0, 0, {'product_id': prod_container.id, 'product_qty': 1.0}),
                (0, 0, {'product_id': prod_charging.id, 'product_qty': 1.0}),
                (0, 0, {'product_id': prod_general_sfg.id, 'product_qty': 1.0}),
                (0, 0, {'product_id': prod_raw.id, 'product_qty': 2.0}),
            ]
        })

        # Create a dummy Route Config with no matching lines to test fallback resolution to Store
        fallback_config = self.env['mrp.route.config'].create({
            'name': 'Fallback Test Route Config',
            'consumption_location_id': self.loc_pre_prod_packing.id,
            'dest_location_id': self.loc_post_prod_packing.id,
        })
        prod_battery.write({
            'mrp_route_config_id': fallback_config.id
        })

        # 5. Create a Manufacturing Order (MO) for this FG
        mo = self.env['mrp.production'].create({
            'product_id': prod_battery.id,
            'bom_id': bom_battery.id,
            'product_qty': 1.0,
        })
        
        # Confirm the MO. This will trigger stock rules execution for raw materials/SFGs.
        mo.action_confirm()
        
        pickings = mo.picking_ids
        self.assertTrue(pickings, "Pickings should be generated for the components.")
        
        pbm_moves = pickings.move_ids
        self.assertTrue(pbm_moves, "Component transfers should be created.")

        # Check source location of moves
        move_plate = pbm_moves.filtered(lambda m: m.product_id == prod_plate)
        move_spine = pbm_moves.filtered(lambda m: m.product_id == prod_spine)
        move_container = pbm_moves.filtered(lambda m: m.product_id == prod_container)
        move_charging = pbm_moves.filtered(lambda m: m.product_id == prod_charging)
        move_general = pbm_moves.filtered(lambda m: m.product_id == prod_general_sfg)
        move_raw = pbm_moves.filtered(lambda m: m.product_id == prod_raw)

        # All products must default to the warehouse lot stock location (Store) since they are not configured
        self.assertEqual(move_plate.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(move_spine.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(move_container.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(move_charging.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(move_general.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(move_raw.location_id, self.warehouse.lot_stock_id)

        # Destination location of all moves should be overridden to MO's consumption location
        for move in pbm_moves:
            self.assertEqual(move.location_dest_id, mo.location_src_id, "All components should be routed to MO's actual source/consumption location.")
