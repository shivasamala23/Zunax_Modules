# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class MrpRouteConfig(models.Model):
    _name = 'mrp.route.config'
    _description = 'Manufacturing Route Configuration'

    name = fields.Char(string='Route Name', required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    consumption_location_id = fields.Many2one(
        'stock.location',
        string='Components Location (Consumption)',
        required=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]"
    )
    dest_location_id = fields.Many2one(
        'stock.location',
        string='Finished Products Location (Dest)',
        required=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]"
    )
    line_ids = fields.One2many(
        'mrp.route.config.line',
        'config_id',
        string='Component Source Rules'
    )

class MrpRouteConfigLine(models.Model):
    _name = 'mrp.route.config.line'
    _description = 'Component Source Override Line'

    config_id = fields.Many2one(
        'mrp.route.config',
        string='Route Config',
        required=True,
        ondelete='cascade'
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='config_id.company_id',
        store=True,
        readonly=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Component Product',
        help='Apply rule to this specific component product'
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Component Category',
        help='Apply rule to components belonging to this product category'
    )
    source_location_id = fields.Many2one(
        'stock.location',
        string='Component Source Location',
        required=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]"
    )
