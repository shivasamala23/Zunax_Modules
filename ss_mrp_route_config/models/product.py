# -*- coding: utf-8 -*-
from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    mrp_route_config_id = fields.Many2one(
        'mrp.route.config',
        string='MRP Route Config',
        company_dependent=True
    )
    mrp_comp_source_location_id = fields.Many2one(
        'stock.location',
        string='MRP Component Source Location',
        domain="[('usage', '=', 'internal')]",
        company_dependent=True
    )

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    mrp_route_config_id = fields.Many2one(
        'mrp.route.config',
        string='MRP Route Config',
        company_dependent=True
    )
    mrp_comp_source_location_id = fields.Many2one(
        'stock.location',
        string='MRP Component Source Location',
        domain="[('usage', '=', 'internal')]",
        company_dependent=True
    )
