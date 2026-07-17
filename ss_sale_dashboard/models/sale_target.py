# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class SaleTarget(models.Model):
    _name = 'sale.target'
    _description = 'Sales Target'
    _order = 'year desc, month desc'

    name = fields.Char(string='Target Name', compute='_compute_name', store=True)
    year = fields.Selection([
        ('2024', '2024'),
        ('2025', '2025'),
        ('2026', '2026'),
        ('2027', '2027'),
        ('2028', '2028'),
        ('2029', '2029'),
        ('2030', '2030'),
    ], string='Year', required=True,readonly=True,default=lambda self: str(fields.Date.today().year))
    
    month = fields.Selection([
        ('Jan', 'January'),
        ('Feb', 'February'),
        ('Mar', 'March'),
        ('Apr', 'April'),
        ('May', 'May'),
        ('Jun', 'June'),
        ('Jul', 'July'),
        ('Aug', 'August'),
        ('Sep', 'September'),
        ('Oct', 'October'),
        ('Nov', 'November'),
        ('Dec', 'December'),
    ], string='Month', required=True,readonly=True, default=lambda self: fields.Date.today().strftime('%b'))

    target_amount = fields.Float(string='Target Amount (₹)', required=True, default=0.0)
    company_id = fields.Many2one('res.company', string='Company', required=True,readonly=True, default=lambda self: self.env.company, domain="[]")

    @api.depends('year', 'month', 'company_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"Sales Target - {rec.month} {rec.year} ({rec.company_id.name})"
