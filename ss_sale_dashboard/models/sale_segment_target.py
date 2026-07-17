# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


SEGMENT_SELECTION = [
    ('HUPS',    'HUPS (Home UPS)'),
    ('IB',      'IB (Inverter Battery)'),
    ('2W',      '2W (Two-Wheeler)'),
    ('VRLA',    'VRLA'),
    ('PANEL',   'Solar Panel'),
    ('GTI',     'GTI / Hybrid'),
    ('LITHIUM', 'Lithium / ESSM'),
]

MONTH_SELECTION = [
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
]

YEAR_SELECTION = [
    ('2024', '2024'),
    ('2025', '2025'),
    ('2026', '2026'),
    ('2027', '2027'),
    ('2028', '2028'),
    ('2029', '2029'),
    ('2030', '2030'),
]


class SaleSegmentTarget(models.Model):
    """AOP (Annual Operating Plan) targets for each product segment per branch per month.

    This model replaces the Excel-based AOP tracking. One row = one branch's monthly
    unit-count target for one segment. Data is entered once a year (typically at start
    of FY) and read by the Segment Performance dashboard.
    """
    _name = 'sale.segment.target'
    _description = 'Sales Segment AOP Target (Unit Count)'
    _order = 'year desc, month desc, segment, branch_name'
    _rec_name = 'name'

    name = fields.Char(
        string='Target Name',
        compute='_compute_name',
        store=True,
    )
    year = fields.Selection(
        YEAR_SELECTION,
        string='Year',
        required=True,
        default=lambda self: str(fields.Date.today().year),
    )
    month = fields.Selection(
        MONTH_SELECTION,
        string='Month',
        required=True,
        default=lambda self: fields.Date.today().strftime('%b'),
    )
    segment = fields.Selection(
        SEGMENT_SELECTION,
        string='Product Segment',
        required=True,
        help='The product category group (HUPS, IB, 2W, VRLA, Solar Panel, GTI, Lithium).',
    )
    branch_name = fields.Char(
        string='Branch',
        required=True,
        help='Branch/region name exactly as it appears in your sales organization '
             '(e.g., "Lucknow E UP", "Bihar", "Guwahati NE").',
    )
    target_qty = fields.Integer(
        string='AOP Target (Units)',
        required=True,
        default=0,
        help='Planned unit count for this segment in this branch for the given month.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    @api.depends('year', 'month', 'segment', 'branch_name', 'company_id')
    def _compute_name(self):
        seg_map = dict(SEGMENT_SELECTION)
        for rec in self:
            seg_label = seg_map.get(rec.segment, rec.segment or '')
            rec.name = (
                f"{seg_label} – {rec.branch_name or '?'} – "
                f"{rec.month or '?'} {rec.year or '?'} "
                f"({rec.company_id.name if rec.company_id else ''})"
            )

    @api.constrains('target_qty')
    def _check_target_qty(self):
        for rec in self:
            if rec.target_qty < 0:
                raise ValidationError(_('AOP Target (Units) cannot be negative.'))

    _sql_constraints = [
        (
            'unique_segment_branch_month',
            'UNIQUE(year, month, segment, branch_name, company_id)',
            'A target already exists for this Segment + Branch + Month + Year + Company combination. '
            'Please edit the existing record instead of creating a duplicate.',
        ),
    ]
