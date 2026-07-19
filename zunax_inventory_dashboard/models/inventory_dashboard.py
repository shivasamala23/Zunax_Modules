# -*- coding: utf-8 -*-
import logging
from odoo import models, api, fields
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class ZunaxInventoryDashboard(models.AbstractModel):
    _name = 'zunax.inventory.dashboard'
    _description = 'Zunax Inventory Dashboard'

    def _get_location_ids(self, company_ids, warehouse_ids=None):
        """Helper to get child internal locations for company/warehouse filter."""
        domain = [('usage', '=', 'internal')]
        if warehouse_ids:
            warehouses = self.env['stock.warehouse'].browse(warehouse_ids)
            parent_loc_ids = warehouses.mapped('view_location_id').ids + warehouses.mapped('lot_stock_id').ids
            domain.append(('id', 'child_of', parent_loc_ids))
        elif company_ids:
            domain.extend(['|', ('company_id', '=', False), ('company_id', 'in', company_ids)])
        else:
            domain.extend(['|', ('company_id', '=', False), ('company_id', 'in', self.env.companies.ids)])
        return self.env['stock.location'].search(domain).ids

    @api.model
    def get_dashboard_data(self, company_ids=None, warehouse_ids=None,
                           date_from=None, date_to=None,
                           category_ids=None, product_ids=None,
                           location_ids=None):
        """Fetch drop-down options and calculated KPI summary cards."""
        allowed_companies = self.env.companies.ids
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        else:
            active_company_ids = list(allowed_companies)
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        main_company_id = active_company_ids[0]
        w_ids = [int(w) for w in warehouse_ids] if warehouse_ids else []
        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        l_ids = [int(l) for l in location_ids] if location_ids else []

        # Expand category children
        expanded_category_ids = []
        if c_ids:
            self.env.cr.execute("""
                WITH RECURSIVE cat_tree AS (
                    SELECT id FROM product_category WHERE id = ANY(%s)
                    UNION ALL
                    SELECT pc.id FROM product_category pc
                    JOIN cat_tree ct ON pc.parent_id = ct.id
                )
                SELECT id FROM cat_tree
            """, (c_ids,))
            expanded_category_ids = [r[0] for r in self.env.cr.fetchall()]

        # Set default dates
        if not date_from and not date_to:
            current_year = datetime.now().year
            date_from = f"{current_year}-01-01"
            date_to = datetime.now().strftime('%Y-%m-%d')
        elif not date_from:
            date_from = "2020-01-01"
        elif not date_to:
            date_to = datetime.now().strftime('%Y-%m-%d')

        dt_from = f"{date_from} 00:00:00"
        dt_to = f"{date_to} 23:59:59"

        # Resolve selected location IDs
        selected_location_ids = list(l_ids)
        if not selected_location_ids:
            selected_location_ids = self._get_location_ids(active_company_ids, w_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        cr = self.env.cr

        # ── DROPDOWN LISTS (fast SQL, no ORM) ──────────────────────────────
        cr.execute("SELECT id, name FROM res_company WHERE id = ANY(%s) ORDER BY name",
                   (active_company_ids,))
        companies_list = [{'id': r[0], 'name': r[1]} for r in cr.fetchall()]

        cr.execute("SELECT id, name, company_id FROM stock_warehouse WHERE company_id = ANY(%s) ORDER BY name",
                   (active_company_ids,))
        warehouses_list = [{'id': r[0], 'name': r[1], 'company_id': r[2]} for r in cr.fetchall()]

        # Categories: complete_name is a stored computed VARCHAR in Odoo 18
        cr.execute("""
            SELECT id, name, complete_name
            FROM product_category
            ORDER BY COALESCE(complete_name, name)
        """)
        categories_list = [{'id': r[0], 'name': r[1], 'complete_name': r[2] or r[1]}
                           for r in cr.fetchall()]

        # Products: use name_get style — pt.name is JSONB in Odoo 18
        if c_ids:
            cr.execute("""
                SELECT pp.id,
                       COALESCE(pt.name->>'en_US', pt.name::text) AS name,
                       pp.default_code
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE pp.active = TRUE AND pt.active = TRUE
                  AND pt.categ_id = ANY(%s)
                ORDER BY COALESCE(pt.name->>'en_US', pt.name::text)
                LIMIT 5000
            """, (expanded_category_ids or c_ids,))
        else:
            cr.execute("""
                SELECT pp.id,
                       COALESCE(pt.name->>'en_US', pt.name::text) AS name,
                       pp.default_code
                FROM product_product pp
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE pp.active = TRUE AND pt.active = TRUE
                ORDER BY COALESCE(pt.name->>'en_US', pt.name::text)
                LIMIT 5000
            """)
        products_list = [{'id': r[0], 'name': r[1], 'default_code': r[2]} for r in cr.fetchall()]

        # Locations
        cr.execute("""
            SELECT id, name, complete_name
            FROM stock_location
            WHERE usage = 'internal'
              AND (company_id IS NULL OR company_id = ANY(%s))
            ORDER BY COALESCE(complete_name, name)
        """, (active_company_ids,))
        locations_list = [{'id': r[0], 'name': r[1], 'complete_name': r[2] or r[1]}
                          for r in cr.fetchall()]

        # ── KPI CALCULATIONS ────────────────────────────────────────────────
        # standard_price is company-dependent JSONB in Odoo 18: {"company_id": price}
        company_id_str = str(main_company_id)
        sq_pid_filter = "AND sq.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sq_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""
        sm_pid_filter = "AND sm.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sm_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""

        kpi_params = {
            'selected_locations': selected_location_ids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'product_ids': p_ids or [],
            'category_ids': expanded_category_ids or [],
            'company_id_str': company_id_str,
        }

        # Closing Value: stock_quant.quantity × standard_price (JSONB in Odoo 18)
        # Fast direct key COALESCE across permitted company IDs
        cr.execute(f"""
            SELECT COALESCE(SUM(
                sq.quantity * COALESCE(
                    (pp.standard_price->>%(company_id_str)s)::numeric,
                    (pp.standard_price->>'1')::numeric,
                    (pp.standard_price->>'2')::numeric,
                    (pp.standard_price->>'3')::numeric,
                    (pp.standard_price->>'4')::numeric,
                    (pp.standard_price->>'5')::numeric,
                    (pp.standard_price->>'6')::numeric,
                    (pp.standard_price->>'7')::numeric,
                    (pp.standard_price->>'8')::numeric,
                    0.0
                )
            ), 0.0)
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(selected_locations)s)
              AND sq.quantity > 0
              {sq_pid_filter}
              {sq_cat_filter}
        """, kpi_params)
        closing_val = float(cr.fetchone()[0] or 0.0)

        # Period Receipts (GRN) — stock moves INTO selected locations from external source
        # Use SVL.value directly (always recorded for valued products)
        cr.execute(f"""
            SELECT COALESCE(SUM(svl.value), 0.0)
            FROM stock_move sm
            JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            JOIN product_product pp ON sm.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sm.state = 'done'
              AND sm.date >= %(dt_from)s AND sm.date <= %(dt_to)s
              AND sm.location_dest_id = ANY(%(selected_locations)s)
              AND sm.location_id NOT IN (SELECT id FROM stock_location WHERE usage = 'internal')
              {sm_pid_filter}
              {sm_cat_filter}
        """, kpi_params)
        receipt_val = float(cr.fetchone()[0] or 0.0)

        # Period Issues — stock moves FROM selected locations to external destination
        cr.execute(f"""
            SELECT COALESCE(SUM(ABS(svl.value)), 0.0)
            FROM stock_move sm
            JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            JOIN product_product pp ON sm.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sm.state = 'done'
              AND sm.date >= %(dt_from)s AND sm.date <= %(dt_to)s
              AND sm.location_id = ANY(%(selected_locations)s)
              AND sm.location_dest_id NOT IN (SELECT id FROM stock_location WHERE usage = 'internal')
              {sm_pid_filter}
              {sm_cat_filter}
        """, kpi_params)
        issue_val = float(cr.fetchone()[0] or 0.0)

        # Opening Value = Closing - Receipts + Issues (inventory balance equation)
        opening_val = closing_val - receipt_val + issue_val

        # ── AGING ────────────────────────────────────────────────────────────
        ageing_data = self._get_ageing_analysis(
            main_company_id, selected_location_ids, dt_to,
            expanded_category_ids, p_ids)

        age_30 = sum(x.get('val_30', 0.0) for x in ageing_data)
        age_60 = sum(x.get('val_60', 0.0) for x in ageing_data)
        age_90 = sum(x.get('val_90', 0.0) for x in ageing_data)
        age_120 = sum(x.get('val_120', 0.0) for x in ageing_data)
        age_150 = sum(x.get('val_150', 0.0) for x in ageing_data)
        age_180 = sum(x.get('val_180', 0.0) for x in ageing_data)
        age_360 = sum(x.get('val_360', 0.0) for x in ageing_data)
        age_above = sum(x.get('val_above', 0.0) for x in ageing_data)

        quant_view_id = self.env.ref('zunax_inventory_dashboard.view_zunax_stock_quant_tree').id
        move_view_id = self.env.ref('zunax_inventory_dashboard.view_zunax_stock_move_tree').id
        return {
            'companies': companies_list,
            'warehouses': warehouses_list,
            'categories': categories_list,
            'products': products_list,
            'locations': locations_list,
            'quant_view_id': quant_view_id,
            'move_view_id': move_view_id,
            'filters': {
                'company_ids': active_company_ids,
                'warehouse_ids': w_ids,
                'date_from': date_from,
                'date_to': date_to,
                'category_ids': c_ids,
                'product_ids': p_ids,
                'location_ids': l_ids,
            },
            'kpis': {
                'opening_value': round(opening_val, 2),
                'grn_value': round(receipt_val, 2),
                'issue_value': round(issue_val, 2),
                'closing_value': round(closing_val, 2),
                'ageing_30': round(age_30, 2),
                'ageing_60': round(age_60, 2),
                'ageing_90': round(age_90, 2),
                'ageing_120': round(age_120, 2),
                'ageing_150': round(age_150, 2),
                'ageing_180': round(age_180, 2),
                'ageing_360': round(age_360, 2),
                'ageing_above': round(age_above, 2),
            }
        }


    def _get_inventory_status(self, company_id, location_ids, dt_from, dt_to,
                              category_ids, product_ids):
        cr = self.env.cr
        params = {
            'location_ids': location_ids,
            'product_ids': product_ids or [],
            'product_ids_empty': not bool(product_ids),
            'category_ids': category_ids or [],
            'category_ids_empty': not bool(category_ids),
            'dt_from': dt_from,
            'dt_to': dt_to,
            'company_id_str': str(company_id),  # for standard_price JSONB key lookup
        }


        # Step 1: Get closing quantities from stock_quant
        # In Odoo 18, standard_price is JSONB {company_id: price}, sq.value does not exist
        closing_q = """
            SELECT
                sq.product_id,
                pp.default_code AS item_code,
                COALESCE(pt.name->>'en_US', pt.name::text) AS item_name,
                SUM(sq.quantity) AS closing_qty,
                SUM(sq.quantity * COALESCE(
                    (pp.standard_price->>%(company_id_str)s)::numeric,
                    (pp.standard_price->>'1')::numeric,
                    (pp.standard_price->>'2')::numeric,
                    (pp.standard_price->>'3')::numeric,
                    (pp.standard_price->>'4')::numeric,
                    (pp.standard_price->>'5')::numeric,
                    (pp.standard_price->>'6')::numeric,
                    (pp.standard_price->>'7')::numeric,
                    (pp.standard_price->>'8')::numeric,
                    0.0
                )) AS closing_val
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(location_ids)s)
              AND (%(product_ids_empty)s OR sq.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
            GROUP BY sq.product_id, pp.default_code, pt.name
            ORDER BY COALESCE(pt.name->>'en_US', pt.name::text) ASC
            LIMIT 2000
        """
        cr.execute(closing_q, params)
        closing_rows = cr.dictfetchall()
        if not closing_rows:
            return []

        # Step 2: Get period receipts/issues AND post-period moves for opening balance
        active_pids = [r['product_id'] for r in closing_rows]
        params['active_pids'] = active_pids

        moves_q = """
            SELECT
                sm.product_id,
                -- Period receipts (dt_from to dt_to)
                SUM(CASE WHEN sm.date <= %(dt_to)s
                          AND sm.location_dest_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS receipt_qty,
                SUM(CASE WHEN sm.date <= %(dt_to)s
                          AND sm.location_dest_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_id = ANY(%(location_ids)s))
                     THEN COALESCE(svl.value, sm.quantity * COALESCE((pp.standard_price->>%(company_id_str)s)::numeric, 0.0))
                     ELSE 0.0 END)                                           AS receipt_val,
                -- Period issues (dt_from to dt_to)
                SUM(CASE WHEN sm.date <= %(dt_to)s
                          AND sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS issue_qty,
                SUM(CASE WHEN sm.date <= %(dt_to)s
                          AND sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN ABS(COALESCE(svl.value, sm.quantity * COALESCE((pp.standard_price->>%(company_id_str)s)::numeric, 0.0)))
                     ELSE 0.0 END)                                           AS issue_val,
                -- All receipts since dt_from (for opening balance computation)
                SUM(CASE WHEN sm.location_dest_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS all_receipts_since,
                SUM(CASE WHEN sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS all_issues_since
            FROM stock_move sm
            JOIN product_product pp ON sm.product_id = pp.id
            LEFT JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            WHERE sm.state = 'done'
              AND sm.date >= %(dt_from)s
              AND (sm.location_id = ANY(%(location_ids)s)
                   OR sm.location_dest_id = ANY(%(location_ids)s))
              AND sm.product_id = ANY(%(active_pids)s)
            GROUP BY sm.product_id
        """
        cr.execute(moves_q, params)
        moves_map = {r['product_id']: r for r in cr.dictfetchall()}

        # Step 3: Combine results
        result = []
        for row in closing_rows:
            pid = row['product_id']
            m = moves_map.get(pid, {})
            receipt_qty = float(m.get('receipt_qty') or 0)
            receipt_val = float(m.get('receipt_val') or 0)
            issue_qty   = float(m.get('issue_qty') or 0)
            issue_val   = float(m.get('issue_val') or 0)
            closing_qty = float(row.get('closing_qty') or 0)
            closing_val = float(row.get('closing_val') or 0)
            all_recv  = float(m.get('all_receipts_since') or 0)
            all_issue = float(m.get('all_issues_since') or 0)
            opening_qty = closing_qty - all_recv + all_issue
            opening_val = closing_val - receipt_val + issue_val

            if not any([opening_qty, receipt_qty, issue_qty, closing_qty]):
                continue

            result.append({
                'product_id':  pid,
                'item_code':   row['item_code'] or 'N/A',
                'item_name':   row['item_name'],
                'opening_qty': round(opening_qty, 4),
                'opening_val': round(opening_val, 2),
                'receipt_qty': round(receipt_qty, 4),
                'receipt_val': round(receipt_val, 2),
                'issue_qty':   round(issue_qty, 4),
                'issue_val':   round(issue_val, 2),
                'closing_qty': round(closing_qty, 4),
                'closing_val': round(closing_val, 2),
            })
        return result

    def _get_ageing_analysis(self, company_id, location_ids, dt_to,
                             category_ids, product_ids):
        """Compute stock aging buckets using standard_price (JSONB in Odoo 18) for unit cost."""
        cr = self.env.cr
        company_id_str = str(company_id)

        pid_filter = "AND sq.product_id = ANY(%(product_ids)s)" if product_ids else ""
        cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if category_ids else ""

        params = {
            'location_ids': location_ids,
            'product_ids': product_ids or [],
            'category_ids': category_ids or [],
            'dt_to': dt_to,
            'company_id_str': company_id_str,
        }

        # standard_price is JSONB in Odoo 18 with company_id as key
        query = f"""
            SELECT
                sq.product_id,
                pp.default_code AS item_code,
                COALESCE(pt.name->>'en_US', pt.name::text) AS item_name,
                COALESCE(
                    (pp.standard_price->>%(company_id_str)s)::numeric,
                    (pp.standard_price->>'1')::numeric,
                    (pp.standard_price->>'2')::numeric,
                    (pp.standard_price->>'3')::numeric,
                    (pp.standard_price->>'4')::numeric,
                    (pp.standard_price->>'5')::numeric,
                    (pp.standard_price->>'6')::numeric,
                    (pp.standard_price->>'7')::numeric,
                    (pp.standard_price->>'8')::numeric,
                    0.0
                ) AS unit_cost,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '30 days'
                              AND sq.in_date <= %(dt_to)s::timestamp
                         THEN sq.quantity ELSE 0 END) AS qty_30,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '60 days'
                              AND sq.in_date <  %(dt_to)s::timestamp - INTERVAL '30 days'
                         THEN sq.quantity ELSE 0 END) AS qty_60,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '90 days'
                              AND sq.in_date <  %(dt_to)s::timestamp - INTERVAL '60 days'
                         THEN sq.quantity ELSE 0 END) AS qty_90,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '120 days'
                              AND sq.in_date <  %(dt_to)s::timestamp - INTERVAL '90 days'
                         THEN sq.quantity ELSE 0 END) AS qty_120,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '150 days'
                              AND sq.in_date <  %(dt_to)s::timestamp - INTERVAL '120 days'
                         THEN sq.quantity ELSE 0 END) AS qty_150,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '180 days'
                              AND sq.in_date <  %(dt_to)s::timestamp - INTERVAL '150 days'
                         THEN sq.quantity ELSE 0 END) AS qty_180,
                SUM(CASE WHEN sq.in_date >= %(dt_to)s::timestamp - INTERVAL '360 days'
                              AND sq.in_date <  %(dt_to)s::timestamp - INTERVAL '180 days'
                         THEN sq.quantity ELSE 0 END) AS qty_360,
                SUM(CASE WHEN sq.in_date IS NULL
                              OR sq.in_date < %(dt_to)s::timestamp - INTERVAL '360 days'
                         THEN sq.quantity ELSE 0 END) AS qty_above,
                SUM(sq.quantity) AS total_qty
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(location_ids)s)
              AND sq.quantity > 0
              {pid_filter}
              {cat_filter}
            GROUP BY sq.product_id, pp.default_code, pt.name, pp.standard_price
        """
        cr.execute(query, params)
        rows = cr.dictfetchall()

        result = []
        for r in rows:
            unit_cost = float(r['unit_cost'] or 0.0)
            qty_30    = float(r['qty_30'] or 0.0)
            qty_60    = float(r['qty_60'] or 0.0)
            qty_90    = float(r['qty_90'] or 0.0)
            qty_120   = float(r['qty_120'] or 0.0)
            qty_150   = float(r['qty_150'] or 0.0)
            qty_180   = float(r['qty_180'] or 0.0)
            qty_360   = float(r['qty_360'] or 0.0)
            qty_above = float(r['qty_above'] or 0.0)
            total_qty = float(r['total_qty'] or 0.0)
            result.append({
                'product_id': r['product_id'],
                'item_code':  r['item_code'] or 'N/A',
                'item_name':  r['item_name'],
                'total_qty':  round(total_qty, 4),
                'total_val':  round(total_qty * unit_cost, 2),
                'qty_30': round(qty_30, 4),   'val_30':  round(qty_30 * unit_cost, 2),
                'qty_60': round(qty_60, 4),   'val_60':  round(qty_60 * unit_cost, 2),
                'qty_90': round(qty_90, 4),   'val_90':  round(qty_90 * unit_cost, 2),
                'qty_120': round(qty_120, 4), 'val_120': round(qty_120 * unit_cost, 2),
                'qty_150': round(qty_150, 4), 'val_150': round(qty_150 * unit_cost, 2),
                'qty_180': round(qty_180, 4), 'val_180': round(qty_180 * unit_cost, 2),
                'qty_360': round(qty_360, 4), 'val_360': round(qty_360 * unit_cost, 2),
                'qty_above': round(qty_above, 4), 'val_above': round(qty_above * unit_cost, 2),
            })
        return result



    @api.model
    def action_open_opening_valuation(self, company_ids=None, date_from=None, category_ids=None, product_ids=None, location_ids=None):
        """Generates dynamic opening valuation line records for filters and opens their list view instantly."""
        self = self.sudo()
        self.env['zunax.opening.valuation.line'].search([('create_uid', '=', self.env.user.id)]).unlink()

        allowed_companies = self.env.companies.ids
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        else:
            active_company_ids = [self.env.company.id]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        l_ids = [int(l) for l in location_ids] if location_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search([('id', 'child_of', c_ids)]).ids

        if not date_from:
            date_from = f"{datetime.now().year}-01-01"

        selected_location_ids = l_ids or self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        cr = self.env.cr
        company_id_str = str(active_company_ids[0])
        params = {
            'selected_locations': selected_location_ids,
            'company_id_str': company_id_str,
        }
        val_filter_conds = []
        if p_ids:
            val_filter_conds.append("sq.product_id = ANY(%(product_ids)s)")
            params['product_ids'] = p_ids
        if expanded_category_ids:
            val_filter_conds.append("pt.categ_id = ANY(%(category_ids)s)")
            params['category_ids'] = expanded_category_ids

        val_filter_sql = ("AND " + " AND ".join(val_filter_conds)) if val_filter_conds else ""

        # Instant query starting from stock_quant
        query = f"""
            SELECT 
                sq.product_id,
                sq.lot_id,
                sq.location_id,
                SUM(sq.quantity) AS qty,
                SUM(sq.quantity * COALESCE(
                    (pp.standard_price->>%(company_id_str)s)::numeric,
                    (pp.standard_price->>'1')::numeric,
                    (pp.standard_price->>'2')::numeric,
                    0.0
                )) AS val
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(selected_locations)s)
              AND sq.quantity > 0
              {val_filter_sql}
            GROUP BY sq.product_id, sq.lot_id, sq.location_id, pp.standard_price
            HAVING SUM(sq.quantity) != 0
            LIMIT 5000
        """
        cr.execute(query, params)
        rows = cr.dictfetchall()

        vals_list = []
        for r in rows:
            qty = float(r['qty'] or 0.0)
            val = float(r['val'] or 0.0)
            unit_price = round(val / qty, 2) if qty else 0.0
            vals_list.append({
                'product_id': r['product_id'],
                'lot_id': r['lot_id'],
                'location_id': r['location_id'],
                'quantity': qty,
                'value': val,
                'unit_price': unit_price,
            })

        lines = self.env['zunax.opening.valuation.line'].create(vals_list)

        action = self.env["ir.actions.actions"]._for_xml_id("zunax_inventory_dashboard.action_zunax_opening_valuation_lines")
        action['domain'] = [('id', 'in', lines.ids)]
        return action

    @api.model
    def action_open_closing_valuation(self, company_ids=None, date_to=None, category_ids=None, product_ids=None, location_ids=None):
        self = self.sudo()
        allowed_companies = self.env.companies.ids
        
        active_company_ids = []
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        l_ids = [int(l) for l in location_ids] if location_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search([('id', 'child_of', c_ids)]).ids

        if not date_to:
            date_to = datetime.now().strftime('%Y-%m-%d')

        selected_location_ids = l_ids or self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        # 1. Clear old records created by current user
        self.env['zunax.opening.valuation.line'].search([('create_uid', '=', self.env.user.id)]).unlink()

        # 2. Fast query directly from stock_quant
        cr = self.env.cr
        company_id_str = str(active_company_ids[0])
        params = {
            'selected_locations': selected_location_ids,
            'company_id_str': company_id_str,
        }
        val_filter_conds = []
        if p_ids:
            val_filter_conds.append("sq.product_id = ANY(%(product_ids)s)")
            params['product_ids'] = p_ids
        if expanded_category_ids:
            val_filter_conds.append("pt.categ_id = ANY(%(category_ids)s)")
            params['category_ids'] = expanded_category_ids

        val_filter_sql = ("AND " + " AND ".join(val_filter_conds)) if val_filter_conds else ""

        query = f"""
            SELECT 
                sq.product_id,
                sq.lot_id,
                sq.location_id,
                SUM(sq.quantity) AS qty,
                SUM(sq.quantity * COALESCE(
                    (pp.standard_price->>%(company_id_str)s)::numeric,
                    (pp.standard_price->>'1')::numeric,
                    (pp.standard_price->>'2')::numeric,
                    0.0
                )) AS val
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(selected_locations)s)
              AND sq.quantity > 0
              {val_filter_sql}
            GROUP BY sq.product_id, sq.lot_id, sq.location_id, pp.standard_price
            HAVING SUM(sq.quantity) != 0
            LIMIT 5000
        """
        cr.execute(query, params)
        rows = cr.dictfetchall()

        # 3. Insert transient records in batch
        vals_list = []
        for r in rows:
            qty = float(r['qty'] or 0.0)
            val = float(r['val'] or 0.0)
            unit_price = round(val / qty, 2) if qty else 0.0
            vals_list.append({
                'product_id': r['product_id'],
                'lot_id': r['lot_id'],
                'location_id': r['location_id'],
                'quantity': qty,
                'value': val,
                'unit_price': unit_price,
            })

        lines = self.env['zunax.opening.valuation.line'].create(vals_list)

        # 4. Return the loaded action with custom title
        action = self.env["ir.actions.actions"]._for_xml_id("zunax_inventory_dashboard.action_zunax_opening_valuation_lines")
        action['name'] = f"Closing Stock Valuation (as of {date_to})"
        action['domain'] = [('id', 'in', lines.ids)]
        return action

    @api.model
    def action_open_aged_stock(self, days_min, days_max, company_ids=None, date_to=None, category_ids=None, product_ids=None, location_ids=None):
        self = self.sudo()
        allowed_companies = self.env.companies.ids
        
        active_company_ids = []
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        l_ids = [int(l) for l in location_ids] if location_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search(
                [('id', 'child_of', c_ids)]).ids

        if not date_to:
            date_to = datetime.now().strftime('%Y-%m-%d')

        selected_location_ids = l_ids
        if not selected_location_ids:
            selected_location_ids = self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        # Target date string parsed to datetime
        dt_to_parsed = datetime.strptime(date_to[:10], '%Y-%m-%d')
        
        # Max datetime is dt_to - days_min
        max_dt = dt_to_parsed - timedelta(days=days_min)
        max_dt_str = max_dt.strftime('%Y-%m-%d 23:59:59')
        
        domain = [
            ('company_id', 'in', active_company_ids),
            ('location_id', 'in', selected_location_ids),
            ('quantity', '>', 0)
        ]
        
        if days_max < 9999:
            min_dt = dt_to_parsed - timedelta(days=days_max)
            min_dt_str = min_dt.strftime('%Y-%m-%d 00:00:00')
            domain.append(('in_date', '>=', min_dt_str))
            domain.append(('in_date', '<=', max_dt_str))
        else:
            # Above 360 Days
            domain.append(('in_date', '<', max_dt_str))

        if p_ids:
            domain.append(('product_id', 'in', p_ids))
        if expanded_category_ids:
            domain.append(('product_categ_id', 'in', expanded_category_ids))

        return {
            'name': f"Stock Aged {days_min}-{days_max if days_max < 9999 else 'Above'} Days",
            'type': "ir.actions.act_window",
            'res_model': "stock.quant",
            'views': [[False, "list"], [False, "form"]],
            'domain': domain,
            'target': "current"
        }




class StockMove(models.Model):
    _inherit = 'stock.move'

    display_price_unit = fields.Float(string='Unit Price', compute='_compute_display_price_unit')
    zunax_subtotal = fields.Float(string='Sub Total', compute='_compute_zunax_subtotal')

    @api.depends('purchase_line_id', 'purchase_line_id.price_unit', 'price_unit', 'product_id', 'product_id.standard_price')
    def _compute_display_price_unit(self):
        for move in self:
            if move.purchase_line_id and move.purchase_line_id.price_unit:
                move.display_price_unit = move.purchase_line_id.price_unit
            elif move.price_unit:
                move.display_price_unit = move.price_unit
            else:
                move.display_price_unit = move.product_id.standard_price or 0.0

    @api.depends('quantity', 'display_price_unit', 'stock_valuation_layer_ids', 'stock_valuation_layer_ids.value')
    def _compute_zunax_subtotal(self):
        for move in self:
            if move.stock_valuation_layer_ids:
                move.zunax_subtotal = sum(abs(svl.value or 0.0) for svl in move.stock_valuation_layer_ids)
            else:
                move.zunax_subtotal = move.quantity * move.display_price_unit


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    product_code = fields.Char(related='product_id.default_code', string='Product Code')
    unit_price = fields.Float(string='Unit Price', compute='_compute_unit_price')
    value = fields.Float(string='Value', compute='_compute_value')

    @api.depends('quantity', 'product_id', 'product_id.standard_price')
    def _compute_unit_price(self):
        for quant in self:
            quant.unit_price = quant.product_id.standard_price or 0.0

    @api.depends('quantity', 'unit_price')
    def _compute_value(self):
        for quant in self:
            quant.value = quant.quantity * quant.unit_price



class ZunaxOpeningValuationLine(models.TransientModel):
    _name = 'zunax.opening.valuation.line'
    _description = 'Zunax Opening Valuation Line'

    product_id = fields.Many2one('product.product', string='Product')
    product_code = fields.Char(related='product_id.default_code', string='Product Code')
    product_categ_id = fields.Many2one('product.category', related='product_id.categ_id', string='Product Category')
    location_id = fields.Many2one('stock.location', string='Location')
    lot_id = fields.Many2one('stock.lot', string='Lot/Serial Number')
    quantity = fields.Float(string='Qty')
    value = fields.Float(string='Value')
    unit_price = fields.Float(string='Unit Price')

    def action_view_stock_moves(self):
        self.ensure_one()
        from ast import literal_eval
        action = self.env["ir.actions.actions"]._for_xml_id("stock.stock_move_line_action")
        action['domain'] = [
            '|',
                ('location_id', '=', self.location_id.id),
                ('location_dest_id', '=', self.location_id.id),
        ]
        if self.lot_id:
            action['domain'] += [('lot_id', '=', self.lot_id.id)]
        action['context'] = literal_eval(action.get('context') or '{}')
        action['context']['search_default_product_id'] = self.product_id.id
        return action

