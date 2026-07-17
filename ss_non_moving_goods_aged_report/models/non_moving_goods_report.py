from odoo import models, fields, api, tools

class StockNonMovingGoodsReport(models.Model):
    _name = 'stock.non.moving.goods.report'
    _description = 'Non-Moving Goods Aged Report'
    _auto = False
    _order = 'non_moving_days desc'

    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', readonly=True)
    location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    qty_on_hand = fields.Float(string='On Hand Quantity', readonly=True)
    standard_price = fields.Float(string='Cost Price', readonly=True)
    stock_value = fields.Float(string='Stock Value', readonly=True)
    last_outgoing_move_date = fields.Datetime(string='Last Outgoing Move Date', readonly=True)
    non_moving_days = fields.Integer(string='Non-Moving Days', readonly=True)
    age_bucket = fields.Selection([
        ('0-30', '0-30 Days'),
        ('31-60', '31-60 Days'),
        ('61-90', '61-90 Days'),
        ('91-180', '91-180 Days'),
        ('181-365', '181-365 Days'),
        ('365+', '365+ Days')
    ], string='Age Bucket', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    sq.id AS id,
                    sq.product_id AS product_id,
                    sq.lot_id AS lot_id,
                    pp.product_tmpl_id AS product_tmpl_id,
                    pt.categ_id AS categ_id,
                    sq.location_id AS location_id,
                    sl.warehouse_id AS warehouse_id,
                    sq.company_id AS company_id,
                    sq.quantity AS qty_on_hand,
                    COALESCE(
                        (pp.standard_price->>sq.company_id::text)::numeric, 
                        (pp.standard_price->>'1')::numeric, 
                        (pp.standard_price::jsonb->>0)::numeric, 
                        0.0
                    ) AS standard_price,
                    sq.quantity * COALESCE(
                        (pp.standard_price->>sq.company_id::text)::numeric, 
                        (pp.standard_price->>'1')::numeric, 
                        (pp.standard_price::jsonb->>0)::numeric, 
                        0.0
                    ) AS stock_value,
                    COALESCE(lm.max_date, pt.create_date) AS last_outgoing_move_date,
                    CURRENT_DATE - COALESCE(lm.max_date::date, pt.create_date::date) AS non_moving_days,
                    CASE 
                        WHEN (CURRENT_DATE - COALESCE(lm.max_date::date, pt.create_date::date)) <= 30 THEN '0-30'
                        WHEN (CURRENT_DATE - COALESCE(lm.max_date::date, pt.create_date::date)) <= 60 THEN '31-60'
                        WHEN (CURRENT_DATE - COALESCE(lm.max_date::date, pt.create_date::date)) <= 90 THEN '61-90'
                        WHEN (CURRENT_DATE - COALESCE(lm.max_date::date, pt.create_date::date)) <= 180 THEN '91-180'
                        WHEN (CURRENT_DATE - COALESCE(lm.max_date::date, pt.create_date::date)) <= 365 THEN '181-365'
                        ELSE '365+'
                    END AS age_bucket
                FROM stock_quant sq
                JOIN product_product pp ON pp.id = sq.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                JOIN stock_location sl ON sl.id = sq.location_id
                LEFT JOIN (
                    SELECT sm.product_id, MAX(sm.date) AS max_date
                    FROM stock_move sm
                    JOIN stock_location src ON src.id = sm.location_id
                    JOIN stock_location dest ON dest.id = sm.location_dest_id
                    WHERE sm.state = 'done'
                      AND src.usage = 'internal'
                      AND dest.usage != 'internal'
                    GROUP BY sm.product_id
                ) lm ON lm.product_id = sq.product_id
                WHERE sl.usage = 'internal' 
                  AND sq.quantity > 0
            )
        """)
