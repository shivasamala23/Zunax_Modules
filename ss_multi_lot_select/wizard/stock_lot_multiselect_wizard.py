# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, Command
from odoo.exceptions import UserError


class StockLotMultiselectWizard(models.TransientModel):
    """
    Wizard to select multiple lot/serial numbers at once
    and apply them as move lines on a stock.move (Details popup).
    """
    _name = 'stock.lot.multiselect.wizard'
    _description = 'Select Multiple Lots/Serials'

    move_id = fields.Many2one(
        'stock.move',
        string='Stock Move',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        related='move_id.product_id',
        readonly=True,
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Source Location',
        related='move_id.location_id',
        readonly=True,
    )
    has_tracking = fields.Selection(
        related='move_id.has_tracking',
        readonly=True,
    )
    lot_line_ids = fields.One2many(
        'stock.lot.multiselect.line',
        'wizard_id',
        string='Lots / Serial Numbers',
    )
    quantity_per_lot = fields.Float(
        string='Quantity per Lot/Serial',
        default=1.0,
        help='Quantity to assign for each selected lot/serial number. '
             'For serial tracking this should remain 1.',
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        move_id = self.env.context.get('default_move_id') or self.env.context.get('active_id')
        if move_id:
            move = self.env['stock.move'].browse(move_id)
            res['move_id'] = move.id
            if 'lot_line_ids' in fields_list:
                lines = self._get_available_lot_lines(move)
                res['lot_line_ids'] = lines
        return res

    def _get_available_lot_lines(self, move):
        """
        Return lot/serial numbers available in the source location
        for the move's product, as wizard line vals.
        Already-used lots (present in move_line_ids) are pre-excluded.
        """
        if move.has_tracking == 'none':
            return []

        # Lots already assigned on this move
        already_used_lot_ids = move.move_line_ids.mapped('lot_id').ids

        # Search quants at source location
        domain = [
            ('product_id', '=', move.product_id.id),
            ('location_id', 'child_of', move.location_id.id),
            ('quantity', '>', 0),
            ('lot_id', '!=', False),
        ]
        quants = self.env['stock.quant'].search(domain)

        seen_lots = set()
        lines = []
        for quant in quants:
            lot = quant.lot_id
            if lot.id in seen_lots:
                continue
            seen_lots.add(lot.id)
            lines.append((0, 0, {
                'lot_id': lot.id,
                'available_qty': quant.quantity,
                'selected': lot.id not in already_used_lot_ids,
            }))
        return lines

    def action_apply(self):
        """
        Create one stock.move.line per selected lot/serial.
        If a move line already exists for a lot it is skipped.
        """
        self.ensure_one()
        move = self.move_id
        if move.has_tracking == 'none':
            raise UserError(_("This product is not tracked by lot/serial number."))

        selected_lines = self.lot_line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_("Please select at least one lot/serial number."))

        existing_lots = move.move_line_ids.mapped('lot_id').ids
        created = 0

        for line in selected_lines:
            if line.lot_id.id in existing_lots:
                continue
            qty = self.quantity_per_lot if move.has_tracking == 'lot' else 1.0
            self.env['stock.move.line'].create({
                'move_id': move.id,
                'picking_id': move.picking_id.id,
                'product_id': move.product_id.id,
                'product_uom_id': move.product_uom.id,
                'location_id': move.location_id.id,
                'location_dest_id': move.location_dest_id.id,
                'lot_id': line.lot_id.id,
                'quantity': qty,
                'company_id': move.company_id.id,
            })
            created += 1

        if not created:
            raise UserError(_("All selected lots/serials are already added to this move."))

        return {'type': 'ir.actions.act_window_close'}

    def action_refresh(self):
        """Reload available lots (e.g. after filtering)."""
        self.ensure_one()
        lines = self._get_available_lot_lines(self.move_id)
        self.lot_line_ids = [(5, 0, 0)] + lines
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_select_all(self):
        """Mark all lot lines as selected."""
        self.ensure_one()
        self.lot_line_ids.write({'selected': True})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_deselect_all(self):
        """Unmark all lot lines."""
        self.ensure_one()
        self.lot_line_ids.write({'selected': False})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }


class StockLotMultiselectLine(models.TransientModel):
    """
    One row per lot/serial in the multi-select wizard.
    """
    _name = 'stock.lot.multiselect.line'
    _description = 'Lot/Serial Multi-Select Line'
    _order = 'lot_id asc'

    wizard_id = fields.Many2one(
        'stock.lot.multiselect.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lot/Serial Number',
        required=True,
        readonly=True,
    )
    lot_name = fields.Char(
        string='Name',
        related='lot_id.name',
        readonly=True,
    )
    available_qty = fields.Float(
        string='Available Qty',
        readonly=True,
        digits='Product Unit of Measure',
    )
    selected = fields.Boolean(
        string='Select',
        default=True,
    )
    expiration_date = fields.Datetime(
        string='Expiry Date',
        related='lot_id.expiration_date',
        readonly=True,
    )
