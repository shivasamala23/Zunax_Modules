# -*- coding: utf-8 -*-
from collections import defaultdict
import logging
from odoo import models, fields, api, _
from odoo.tools import float_compare, float_round

_logger = logging.getLogger('odoo.addons.ss_mrp_route_config')
def _find_mrp_production(env, values):
    move_dest_ids = values.get('move_dest_ids')
    if move_dest_ids and isinstance(move_dest_ids, models.BaseModel):
        mo_moves = move_dest_ids.filtered(lambda m: m.raw_material_production_id)
        if mo_moves:
            return mo_moves[0].raw_material_production_id
    group_id = values.get('group_id')
    if group_id:
        if isinstance(group_id, int):
            group = env['procurement.group'].browse(group_id)
        else:
            group = group_id
        if hasattr(group, 'mrp_production_ids') and group.mrp_production_ids:
            return group.mrp_production_ids[0]
    return env['mrp.production']


class ProcurementGroup(models.Model):
    _inherit = 'procurement.group'

    @api.model
    def _get_rule(self, product_id, location_id, values):
        mo = _find_mrp_production(self.env, values)
        if mo:
            try:
                config = mo._get_route_config()
                if config:
                    config = config.sudo()
                    if config.consumption_location_id:
                        loc_id = location_id.id if hasattr(location_id, 'id') else location_id
                        config_loc_id = config.consumption_location_id.id if hasattr(config.consumption_location_id, 'id') else config.consumption_location_id
                        if loc_id and loc_id == config_loc_id:
                            location_id = mo.sudo().picking_type_id.default_location_src_id or location_id
                if ('warehouse_id' not in values or not values['warehouse_id']):
                    wh = mo.sudo().picking_type_id.warehouse_id
                    if wh:
                        values['warehouse_id'] = wh
            except Exception as e:
                _logger.warning("ss_mrp_route_config: _get_rule config resolution error: %s", e)

        return super(ProcurementGroup, self)._get_rule(product_id, location_id, values)

    @api.model
    def _get_push_rule(self, product_id, location_dest_id, values):
        if location_dest_id:
            loc_dest_id = location_dest_id.id if hasattr(location_dest_id, 'id') else location_dest_id
            config = self.env['mrp.route.config'].sudo().search([('dest_location_id', '=', loc_dest_id)], limit=1)
            if config:
                warehouse = values.get('warehouse_id')
                if not warehouse:
                    company_id = location_dest_id.company_id.id if hasattr(location_dest_id, 'company_id') else (self.env.company.id or 1)
                    warehouse = self.env['stock.warehouse'].sudo().search([('company_id', '=', company_id)], limit=1)
                if warehouse and warehouse.sam_loc_id:
                    location_dest_id = warehouse.sam_loc_id

        return super(ProcurementGroup, self)._get_push_rule(product_id, location_dest_id, values)


class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values):
        res = super()._get_stock_move_values(
            product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values
        )
        
        mo = _find_mrp_production(self.env, values)
        if mo:
            resolved_loc = False
            try:
                mo_sudo = mo.sudo()
                route_config = mo._get_route_config()

                if route_config:
                    route_config = route_config.sudo()
                    # Direct product match on the route lines
                    matching_line = route_config.line_ids.filtered(lambda l: l.product_id == product_id)
                    if matching_line:
                        resolved_loc = matching_line[0].source_location_id
                    else:
                        # Category match (with parent category traversal fallback)
                        comp_categ = product_id.categ_id
                        while comp_categ and not resolved_loc:
                            matching_line = route_config.line_ids.filtered(lambda l: l.categ_id == comp_categ)
                            if matching_line:
                                resolved_loc = matching_line[0].source_location_id
                            comp_categ = comp_categ.parent_id

                    # 2. Resolve from component's own configuration defaults (with parent category traversal fallback)
                    if not resolved_loc:
                        comp_product = product_id.sudo().with_company(mo.company_id)
                        resolved_loc = comp_product.mrp_comp_source_location_id
                        if not resolved_loc:
                            temp_categ = comp_product.categ_id
                            while temp_categ and not resolved_loc:
                                resolved_loc = temp_categ.sudo().with_company(mo.company_id).mrp_comp_source_location_id
                                temp_categ = temp_categ.parent_id

                    # 3. Default fallback to warehouse lot stock (Store)
                    if not resolved_loc:
                        warehouse = mo_sudo.picking_type_id.warehouse_id or (self.env['stock.warehouse'].sudo().browse(values.get('warehouse_id')) if values.get('warehouse_id') else False)
                        if warehouse and warehouse.lot_stock_id:
                            resolved_loc = warehouse.lot_stock_id

            except Exception as e:
                _logger.warning("ss_mrp_route_config: _get_stock_move_values resolution error: %s", e)

            if resolved_loc:
                res['location_id'] = resolved_loc.id
            if mo:
                try:
                    if mo.sudo().location_src_id:
                        res['location_dest_id'] = mo.sudo().location_src_id.id
                except Exception:
                    pass

        return res

    @api.model
    def _run_pull(self, procurements):
        new_procurements = []
        for procurement, rule in procurements:
            mo = _find_mrp_production(self.env, procurement.values)
            if mo:
                config = mo._get_route_config()
                if config:
                    consumption_loc = mo.location_src_id
                    product = procurement.product_id
                    avail_qty = product.with_context(location=consumption_loc.id).qty_available
                    if avail_qty > 0.0:
                        if product.uom_id != procurement.product_uom:
                            avail_qty_in_uom = product.uom_id._compute_quantity(avail_qty, procurement.product_uom)
                        else:
                            avail_qty_in_uom = avail_qty
                        
                        new_qty = max(0.0, procurement.product_qty - avail_qty_in_uom)
                        _logger.info("Adjusting PBM procurement for %s in MO %s: original qty %s, available in consumption loc %s, new qty %s",
                                     product.default_code, mo.name, procurement.product_qty, avail_qty_in_uom, new_qty)
                        
                        if float_compare(new_qty, 0.0, precision_rounding=procurement.product_uom.rounding) <= 0:
                            move_dest_ids = procurement.values.get('move_dest_ids')
                            if move_dest_ids:
                                for move in move_dest_ids:
                                    vals = {'procure_method': 'make_to_stock'}
                                    if move.state == 'waiting':
                                        vals['state'] = 'confirmed'
                                    move.sudo().write(vals)
                            continue
                        
                        procurement = procurement._replace(product_qty=new_qty)
            
            new_procurements.append((procurement, rule))
            
        return super()._run_pull(new_procurements)


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _adjust_procure_method(self, picking_type_code=False):
        bypass_ids = self.env.context.get('bypass_mto_move_ids', [])
        moves_to_adjust = self.filtered(lambda m: m.id not in bypass_ids)
        
        custom_moves = self.env['stock.move']
        for move in moves_to_adjust:
            if move.raw_material_production_id:
                try:
                    mo = move.raw_material_production_id
                    config = mo._get_route_config()
                    if config and config.consumption_location_id:
                        orig_loc = move.location_id
                        move.location_id = mo.picking_type_id.default_location_src_id or orig_loc
                        try:
                            super(StockMove, move)._adjust_procure_method(picking_type_code=picking_type_code)
                        finally:
                            move.location_id = orig_loc
                        custom_moves |= move
                except Exception as e:
                    _logger.warning("ss_mrp_route_config: _adjust_procure_method error for move %s: %s", move.id, e)

        remaining_moves = moves_to_adjust - custom_moves
        if remaining_moves:
            super(StockMove, remaining_moves)._adjust_procure_method(picking_type_code=picking_type_code)
            
        bypassed_moves = self & self.env['stock.move'].browse(bypass_ids)
        if bypassed_moves:
            bypassed_moves.write({'procure_method': 'make_to_stock'})

    def _action_confirm(self, merge=True, merge_into=False):
        mo_raw_moves = self.filtered(lambda m: m.raw_material_production_id and m.state == 'draft')
        
        if mo_raw_moves and not self.env.context.get('in_custom_mrp_split'):
            mo_raw_moves.with_context(in_custom_mrp_split=True)._adjust_procure_method()
            return super(StockMove, self.with_context(in_custom_mrp_split=True))._action_confirm(merge=merge, merge_into=merge_into)
            
        return super(StockMove, self)._action_confirm(merge=merge, merge_into=merge_into)

    def _skip_push(self):
        """Skip the SAM (Store After Manufacture) push rule when a Route Config
        has explicitly set the dest_location_id for the finished product's MO.

        In 3-step manufacturing (pbm_sam), after an MO is marked done, Odoo
        fires push rules on the finished goods move to create a 'Store Finished
        Product' transfer from Post-Production → Stock. When a Route Config is
        active, the finished product is ALREADY stored at the correct location
        (e.g. Post-Production / Pasting), so we suppress this extra SAM picking.
        """
        # Standard skip checks first (inventory adjustments, already-chained moves)
        if super()._skip_push():
            return True

        # Only applicable to finished goods moves of an MO
        production = self.production_id
        if not production:
            return False

        try:
            config = production._get_route_config()
            if config and config.sudo().dest_location_id:
                # Route Config controls the destination — skip the SAM picking
                _logger.debug(
                    "ss_mrp_route_config: Skipping SAM push for MO %s "
                    "(finished goods stay at Route Config dest: %s)",
                    production.name, config.dest_location_id.display_name
                )
                return True
        except Exception as e:
            _logger.warning("ss_mrp_route_config: _skip_push error for move %s: %s", self.id, e)

        return False
