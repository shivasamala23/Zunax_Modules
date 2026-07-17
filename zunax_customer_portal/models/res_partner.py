# -*- coding: utf-8 -*-
from odoo import models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def get_portal_products(self):
        """
        Return products available for portal ordering.
        Checks if zunax_partner_product_access_control is installed and
        applies partner-level product filtering if so.
        Falls back to all published/available products.
        """
        self.ensure_one()
        Product = self.env['product.template'].sudo()

        # Check if partner product access control module is installed
        IrModule = self.env['ir.module.module'].sudo()
        access_module = IrModule.search([
            ('name', '=', 'zunax_partner_product_access_control'),
            ('state', '=', 'installed'),
        ], limit=1)

        if access_module:
            # Try to use partner-restricted products if the field exists
            try:
                if hasattr(self, 'allowed_product_ids') and self.allowed_product_ids:
                    return self.allowed_product_ids.filtered(
                        lambda p: p.active and p.sale_ok
                    )
            except Exception:
                pass

        # Default: all products available for sale
        return Product.search([
            ('active', '=', True),
            ('sale_ok', '=', True),
        ], order='name asc')
