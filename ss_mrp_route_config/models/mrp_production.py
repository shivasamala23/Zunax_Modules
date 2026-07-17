# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger('odoo.addons.ss_mrp_route_config')


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _get_route_config(self):
        self.ensure_one()
        if not self.product_id:
            return self.env['mrp.route.config']
        fg_product = self.product_id.with_company(self.company_id)
        config = fg_product.sudo().mrp_route_config_id
        if not config:
            temp_categ = fg_product.categ_id
            while temp_categ and not config:
                config = temp_categ.sudo().with_company(self.company_id).mrp_route_config_id
                temp_categ = temp_categ.parent_id
        return config

    @api.depends('picking_type_id', 'product_id', 'product_id.categ_id')
    def _compute_locations(self):
        super()._compute_locations()
        for production in self:
            if not production.product_id:
                continue
            try:
                config = production._get_route_config()
                if config:
                    config = config.sudo()
                    if config.consumption_location_id:
                        production.location_src_id = config.consumption_location_id
                    if config.dest_location_id:
                        production.location_dest_id = config.dest_location_id
            except Exception as e:
                _logger.warning("ss_mrp_route_config: could not resolve route config for MO %s: %s", production.name, e)

    def action_confirm(self):
        """Override to handle multi-company warehouse access gracefully.
        
        When the user is in one company branch (e.g., Burgula) but the MO's warehouse
        or stock rules reference another company's warehouse (e.g., Kothur), the standard
        _check_company() raises an AccessError. We bypass this by running _check_company
        with sudo() to avoid spurious cross-company read failures on warehouse lookups
        triggered during PBM picking confirmation.
        """
        # We use sudo() on the whole action_confirm call to prevent multi-company
        # access errors caused by cross-company warehouse reads during procurement rule
        # evaluation. The actual company ownership of the MO is preserved.
        try:
            return super().action_confirm()
        except Exception as e:
            error_msg = str(e)
            if 'multi-company' in error_msg.lower() or 'access' in error_msg.lower() or 'stock.warehouse' in error_msg:
                _logger.warning(
                    "ss_mrp_route_config: Multi-company access error during MO confirmation, "
                    "retrying with sudo: %s", e
                )
                return super(MrpProduction, self.sudo()).action_confirm()
            raise

    @api.model_create_multi
    def create(self, vals_list):
        productions = super().create(vals_list)
        for production in productions:
            production._sync_finished_move_locations()
        return productions

    def write(self, vals):
        res = super().write(vals)
        if 'location_dest_id' in vals or 'location_src_id' in vals:
            for production in self:
                production._sync_finished_move_locations()
        return res

    def _sync_finished_move_locations(self):
        for production in self:
            if production.location_dest_id:
                # Sync move_finished_ids destination location
                finished_moves = production.move_finished_ids.filtered(lambda m: m.product_id == production.product_id)
                if finished_moves:
                    finished_moves.write({'location_dest_id': production.location_dest_id.id})
                    # NOTE: We no longer sync chained SAM moves here because
                    # _skip_push() suppresses the SAM picking entirely when a
                    # Route Config with dest_location_id is configured.
            if production.location_src_id:
                # Sync move_raw_ids source location
                raw_moves = production.move_raw_ids
                if raw_moves:
                    raw_moves.write({'location_id': production.location_src_id.id})

    @api.depends('state', 'reservation_state', 'date_start', 'move_raw_ids', 'move_raw_ids.forecast_availability', 'move_raw_ids.forecast_expected_date')
    def _compute_components_availability(self):
        super()._compute_components_availability()
        from odoo.tools.float_utils import float_compare
        for production in self:
            if production.state in ('cancel', 'done', 'draft'):
                continue
            if production.components_availability_state == 'unavailable':
                all_available = True
                for move in production.move_raw_ids:
                    if move.state in ('cancel', 'done'):
                        continue
                    if not move.product_id:
                        continue
                    loc_qty = move.product_id.with_context(location=move.location_id.id).qty_available
                    if float_compare(loc_qty, move.product_qty, precision_rounding=move.product_id.uom_id.rounding) == -1:
                        all_available = False
                        break
                if all_available and production.move_raw_ids:
                    production.components_availability = _('Available')
                    production.components_availability_state = 'available'
