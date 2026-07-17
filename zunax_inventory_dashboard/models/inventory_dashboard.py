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
            domain.append(('company_id', 'in', company_ids))
        else:
            domain.append(('company_id', 'in', self.env.companies.ids))
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
            active_company_ids = [self.env.company.id]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        main_company_id = active_company_ids[0]
        w_ids = [int(w) for w in warehouse_ids] if warehouse_ids else []
        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        l_ids = [int(l) for l in location_ids] if location_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search(
                [('id', 'child_of', c_ids)]).ids

        # Set default dates if not provided
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

        # Resolve selected location IDs and child locations
        selected_location_ids = []
        if l_ids:
            selected_location_ids = self.env['stock.location'].search(
                [('id', 'child_of', l_ids), ('usage', '=', 'internal')]).ids
        if not selected_location_ids:
            selected_location_ids = self._get_location_ids(active_company_ids, w_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        # 1. Fetch filter option lists for dashboard dropdowns
        companies_list = self.env['res.company'].sudo().search_read(
            [('id', 'in', allowed_companies)], ['id', 'name'])
        warehouses_list = self.env['stock.warehouse'].sudo().search_read(
            [('company_id', 'in', active_company_ids)], ['id', 'name', 'company_id'])
        categories_list = self.env['product.category'].sudo().search_read(
            [], ['id', 'name', 'complete_name'], order='complete_name ASC')
        # Filter products by selected categories when categories are active
        product_domain = [('active', '=', True)]
        if c_ids:
            product_domain.append(('categ_id', 'child_of', c_ids))
        products_list = self.env['product.product'].sudo().search_read(
            product_domain, ['id', 'name', 'default_code'],
            limit=1000, order='name ASC')
        locations_list = self.env['stock.location'].sudo().search_read(
            [('usage', '=', 'internal'), ('company_id', 'in', active_company_ids)],
            ['id', 'name', 'complete_name'], order='complete_name ASC')

        # 2. Calculate dynamic flow values directly from stock.valuation.layer and stock.move
        cr = self.env.cr
        params = {
            'company_ids': active_company_ids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'selected_locations': selected_location_ids,
            'product_ids': p_ids,
            'product_ids_empty': not bool(p_ids),
            'category_ids': expanded_category_ids,
            'category_ids_empty': not bool(expanded_category_ids),
        }

        # Opening Value
        cr.execute("""
            SELECT 
                SUM(CASE 
                    WHEN sm.location_dest_id = ANY(%(selected_locations)s) AND NOT (sm.location_id = ANY(%(selected_locations)s))
                    THEN svl.value 
                    WHEN sm.location_id = ANY(%(selected_locations)s) AND NOT (sm.location_dest_id = ANY(%(selected_locations)s))
                    THEN -svl.value 
                    ELSE 0.0 END)
            FROM stock_valuation_layer svl
            JOIN stock_move sm ON svl.stock_move_id = sm.id
            JOIN product_product pp ON svl.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE svl.company_id = ANY(%(company_ids)s)
              AND svl.create_date < %(dt_from)s
              AND (%(product_ids_empty)s OR svl.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
              AND (sm.location_id = ANY(%(selected_locations)s) OR sm.location_dest_id = ANY(%(selected_locations)s))
        """, params)
        opening_val = cr.fetchone()[0] or 0.0

        # GRN / Inward Valuation (only Receipt operations via picking_type code = 'incoming')
        cr.execute("""
            SELECT SUM(svl.value) 
            FROM stock_valuation_layer svl
            JOIN stock_move sm ON svl.stock_move_id = sm.id
            JOIN product_product pp ON svl.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN stock_picking sp ON sm.picking_id = sp.id
            LEFT JOIN stock_picking_type spt ON sp.picking_type_id = spt.id
            WHERE svl.company_id = ANY(%(company_ids)s)
              AND svl.create_date >= %(dt_from)s AND svl.create_date <= %(dt_to)s
              AND sm.location_dest_id = ANY(%(selected_locations)s)
              AND NOT (sm.location_id = ANY(%(selected_locations)s))
              AND (spt.code = 'incoming' OR (sp.id IS NULL AND sm.location_id NOT IN (
                  SELECT id FROM stock_location WHERE usage = 'internal'
              )))
              AND (%(product_ids_empty)s OR svl.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
        """, params)
        receipt_val = cr.fetchone()[0] or 0.0


        # Issue / Outward Valuation
        cr.execute("""
            SELECT SUM(ABS(svl.value)) 
            FROM stock_valuation_layer svl
            JOIN stock_move sm ON svl.stock_move_id = sm.id
            JOIN product_product pp ON svl.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE svl.company_id = ANY(%(company_ids)s)
              AND svl.create_date >= %(dt_from)s AND svl.create_date <= %(dt_to)s
              AND sm.location_id = ANY(%(selected_locations)s)
              AND NOT (sm.location_dest_id = ANY(%(selected_locations)s))
              AND (%(product_ids_empty)s OR svl.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
        """, params)
        issue_val = cr.fetchone()[0] or 0.0

        # Closing Value
        cr.execute("""
            SELECT 
                SUM(CASE 
                    WHEN sm.location_dest_id = ANY(%(selected_locations)s) AND NOT (sm.location_id = ANY(%(selected_locations)s))
                    THEN svl.value 
                    WHEN sm.location_id = ANY(%(selected_locations)s) AND NOT (sm.location_dest_id = ANY(%(selected_locations)s))
                    THEN -svl.value 
                    ELSE 0.0 END)
            FROM stock_valuation_layer svl
            JOIN stock_move sm ON svl.stock_move_id = sm.id
            JOIN product_product pp ON svl.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE svl.company_id = ANY(%(company_ids)s)
              AND svl.create_date <= %(dt_to)s
              AND (%(product_ids_empty)s OR svl.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
              AND (sm.location_id = ANY(%(selected_locations)s) OR sm.location_dest_id = ANY(%(selected_locations)s))
        """, params)
        closing_val = cr.fetchone()[0] or 0.0

        # 3. Calculate stock aging values
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
        lang = self.env.lang or 'en_US'
        company_id_str = str(company_id)

        params = {
            'location_ids': location_ids,
            'product_ids': product_ids or [],
            'product_ids_empty': not bool(product_ids),
            'category_ids': category_ids or [],
            'category_ids_empty': not bool(category_ids),
            'lang': lang,
            'company_id_str': company_id_str,
            'dt_from': dt_from,
            'dt_to': dt_to,
        }

        # Step 1: Get closing quantities from stock_quant
        closing_q = """
            SELECT
                sq.product_id,
                pp.default_code                                              AS item_code,
                COALESCE(pt.name->>%(lang)s, pt.name->>'en_US')             AS item_name,
                SUM(sq.quantity)                                             AS closing_qty,
                SUM(sq.quantity * COALESCE(
                    (pp.standard_price->>%(company_id_str)s)::numeric,
                    (pp.standard_price->>'1')::numeric, 0.0))                 AS closing_val
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(location_ids)s)
              AND (%(product_ids_empty)s OR sq.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
            GROUP BY sq.product_id, pp.default_code,
                     COALESCE(pt.name->>%(lang)s, pt.name->>'en_US')
            ORDER BY COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') ASC
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
                     THEN COALESCE(svl.value,
                          sm.quantity * COALESCE(
                              (pp.standard_price->>%(company_id_str)s)::numeric,
                              (pp.standard_price->>'1')::numeric, 0.0))
                     ELSE 0.0 END)                                           AS receipt_val,
                -- Period issues (dt_from to dt_to)
                SUM(CASE WHEN sm.date <= %(dt_to)s
                          AND sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS issue_qty,
                SUM(CASE WHEN sm.date <= %(dt_to)s
                          AND sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN ABS(COALESCE(svl.value,
                          sm.quantity * COALESCE(
                              (pp.standard_price->>%(company_id_str)s)::numeric,
                              (pp.standard_price->>'1')::numeric, 0.0)))
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
        cr = self.env.cr
        lang = self.env.lang or 'en_US'
        company_id_str = str(company_id)

        params = {
            'location_ids': location_ids,
            'product_ids': product_ids or [],
            'product_ids_empty': not bool(product_ids),
            'category_ids': category_ids or [],
            'category_ids_empty': not bool(category_ids),
            'lang': lang,
            'company_id_str': company_id_str,
        }

        qty_q = """
            SELECT
                sq.product_id,
                pp.default_code                                              AS item_code,
                COALESCE(pt.name->>%(lang)s, pt.name->>'en_US')             AS item_name,
                COALESCE((pp.standard_price->>%(company_id_str)s)::numeric,
                         (pp.standard_price->>'1')::numeric, 0.0)            AS unit_cost,
                SUM(sq.quantity)                                             AS total_qty
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(location_ids)s)
              AND (%(product_ids_empty)s OR sq.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
            GROUP BY sq.product_id, pp.default_code,
                     COALESCE(pt.name->>%(lang)s, pt.name->>'en_US'),
                     pp.standard_price
            HAVING SUM(sq.quantity) > 0
            ORDER BY COALESCE(pt.name->>%(lang)s, pt.name->>'en_US') ASC
            LIMIT 1000
        """
        cr.execute(qty_q, params)
        products = cr.dictfetchall()
        if not products:
            return []

        product_qty_map = {r['product_id']: float(r['total_qty'] or 0) for r in products}
        dt_to_parsed = datetime.strptime(dt_to[:10], '%Y-%m-%d')
        dt_limit = (dt_to_parsed - timedelta(days=365)).strftime('%Y-%m-%d')

        params['active_pids'] = list(product_qty_map.keys())
        params['dt_to'] = dt_to
        params['dt_limit'] = dt_limit

        receipt_q = """
            SELECT
                sm.product_id,
                sm.date,
                sm.quantity,
                COALESCE(svl.unit_cost,
                    COALESCE((pp.standard_price->>%(company_id_str)s)::numeric,
                             (pp.standard_price->>'1')::numeric, 0.0))       AS unit_cost
            FROM stock_move sm
            JOIN product_product pp ON sm.product_id = pp.id
            LEFT JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            WHERE sm.state = 'done'
              AND sm.location_dest_id = ANY(%(location_ids)s)
              AND NOT (sm.location_id = ANY(%(location_ids)s))
              AND sm.date <= %(dt_to)s
              AND sm.date >= %(dt_limit)s
              AND sm.product_id = ANY(%(active_pids)s)
            ORDER BY sm.product_id, sm.date DESC
        """
        cr.execute(receipt_q, params)
        receipts = cr.dictfetchall()

        receipt_by_product = {}
        for r in receipts:
            receipt_by_product.setdefault(r['product_id'], []).append(r)

        target_date = dt_to_parsed

        report_lines = []
        for p in products:
            prod_id   = p['product_id']
            qty_rem   = float(p['total_qty'] or 0)
            unit_cost = float(p['unit_cost'] or 0)

            aged = {k: {'qty': 0.0, 'val': 0.0}
                    for k in ('30', '60', '90', '120', '150', '180', '360', 'above')}

            for r in receipt_by_product.get(prod_id, []):
                if qty_rem <= 0:
                    break
                recv_qty   = float(r['quantity'] or 0)
                matched    = min(qty_rem, recv_qty)
                r_cost     = float(r['unit_cost'] or 0) or unit_cost
                r_val      = matched * r_cost
                move_date  = r['date']
                if isinstance(move_date, str):
                    move_date = datetime.strptime(move_date[:19], '%Y-%m-%d %H:%M:%S')
                age = (target_date - move_date.replace(tzinfo=None)).days

                bucket = ('30' if age <= 30 else '60' if age <= 60 else '90' if age <= 90
                          else '120' if age <= 120 else '150' if age <= 150
                          else '180' if age <= 180 else '360' if age <= 360 else 'above')
                aged[bucket]['qty'] += matched
                aged[bucket]['val'] += r_val
                qty_rem -= matched

            if qty_rem > 0:
                aged['above']['qty'] += qty_rem
                aged['above']['val'] += qty_rem * unit_cost

            report_lines.append({
                'product_id': prod_id,
                'item_code':  p['item_code'] or 'N/A',
                'item_name':  p['item_name'],
                'total_qty':  float(p['total_qty'] or 0),
                'total_val':  float(p['total_qty'] or 0) * unit_cost,
                'qty_30':   aged['30']['qty'],   'val_30':   aged['30']['val'],
                'qty_60':   aged['60']['qty'],   'val_60':   aged['60']['val'],
                'qty_90':   aged['90']['qty'],   'val_90':   aged['90']['val'],
                'qty_120':  aged['120']['qty'],  'val_120':  aged['120']['val'],
                'qty_150':  aged['150']['qty'],  'val_150':  aged['150']['val'],
                'qty_180':  aged['180']['qty'],  'val_180':  aged['180']['val'],
                'qty_360':  aged['360']['qty'],  'val_360':  aged['360']['val'],
                'qty_above': aged['above']['qty'], 'val_above': aged['above']['val'],
            })

        return report_lines


    @api.model
    def action_open_opening_valuation(self, company_ids=None, date_from=None, category_ids=None, product_ids=None, location_ids=None):
        """Generates dynamic opening valuation line records for filters and opens their list view."""
        # 1. Clear old records created by current user
        self.env['zunax.opening.valuation.line'].search([('create_uid', '=', self.env.user.id)]).unlink()

        # 2. Parse active filter params
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
            expanded_category_ids = self.env['product.category'].search(
                [('id', 'child_of', c_ids)]).ids

        if not date_from:
            current_year = datetime.now().year
            date_from = f"{current_year}-01-01"

        dt_from = f"{date_from} 00:00:00"

        # Resolve selected location IDs and child locations
        selected_location_ids = []
        if l_ids:
            selected_location_ids = self.env['stock.location'].search(
                [('id', 'child_of', l_ids), ('usage', '=', 'internal')]).ids
        if not selected_location_ids:
            selected_location_ids = self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        # 3. Query the valuation layers prior to dt_from, grouping by location
        cr = self.env.cr
        params = {
            'company_ids': active_company_ids,
            'dt_from': dt_from,
            'selected_locations': selected_location_ids,
            'product_ids': p_ids,
            'product_ids_empty': not bool(p_ids),
            'category_ids': expanded_category_ids,
            'category_ids_empty': not bool(expanded_category_ids),
        }

        query = """
            SELECT 
                combined.product_id,
                combined.lot_id,
                combined.location_id,
                SUM(combined.qty) AS qty,
                SUM(combined.val) AS val
            FROM (
                -- incoming moves
                SELECT 
                    svl.product_id,
                    svl.lot_id,
                    sm.location_dest_id AS location_id,
                    svl.quantity AS qty,
                    svl.value AS val
                FROM stock_valuation_layer svl
                JOIN stock_move sm ON svl.stock_move_id = sm.id
                WHERE svl.company_id = ANY(%(company_ids)s)
                  AND svl.create_date < %(dt_from)s
                  AND sm.location_dest_id = ANY(%(selected_locations)s)
                
                UNION ALL
                
                -- outgoing moves
                SELECT 
                    svl.product_id,
                    svl.lot_id,
                    sm.location_id AS location_id,
                    -svl.quantity AS qty,
                    -svl.value AS val
                FROM stock_valuation_layer svl
                JOIN stock_move sm ON svl.stock_move_id = sm.id
                WHERE svl.company_id = ANY(%(company_ids)s)
                  AND svl.create_date < %(dt_from)s
                  AND sm.location_id = ANY(%(selected_locations)s)
            ) combined
            JOIN product_product pp ON combined.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE (%(product_ids_empty)s OR combined.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
            GROUP BY combined.product_id, combined.lot_id, combined.location_id
            HAVING SUM(combined.qty) != 0 OR SUM(combined.val) != 0
        """
        cr.execute(query, params)
        rows = cr.dictfetchall()

        # 4. Insert transient records in batch
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

        # 5. Return an act_window action to view these lines
        view_id = self.env.ref('zunax_inventory_dashboard.view_zunax_opening_valuation_tree').id
        return {
            'name': 'Opening Stock Valuation (as of closing of previous day)',
            'type': 'ir.actions.act_window',
            'res_model': 'zunax.opening.valuation.line',
            'view_mode': 'list,form',
            'views': [
                (view_id, 'list'),
                (False, 'form')
            ],
            'domain': [('id', 'in', lines.ids)],
            'target': 'current',
        }


class StockMove(models.Model):
    _inherit = 'stock.move'

    display_price_unit = fields.Float(string='Unit Price', compute='_compute_display_price_unit')
    zunax_subtotal = fields.Float(string='Sub Total', compute='_compute_zunax_subtotal')

    @api.depends('purchase_line_id', 'purchase_line_id.price_unit', 'purchase_line_id.invoice_lines.price_unit', 'price_unit')
    def _compute_display_price_unit(self):
        for move in self:
            price = 0.0
            if move.purchase_line_id:
                # Find any linked invoice/bill lines
                invoice_lines = move.purchase_line_id.invoice_lines.filtered(
                    lambda l: l.move_id.move_type == 'in_invoice' and l.move_id.state == 'posted'
                )
                if invoice_lines:
                    # Take the price of the first posted vendor bill line
                    price = invoice_lines[0].price_unit
                else:
                    # Fallback to the purchase order line price
                    price = move.purchase_line_id.price_unit
            else:
                # Fallback to stock move's standard price unit
                price = move.price_unit
            move.display_price_unit = price

    @api.depends('quantity', 'display_price_unit')
    def _compute_zunax_subtotal(self):
        for move in self:
            move.zunax_subtotal = move.quantity * move.display_price_unit


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    product_code = fields.Char(related='product_id.default_code', string='Product Code')
    unit_price = fields.Float(string='Unit Price', compute='_compute_unit_price')

    @api.depends('quantity', 'value')
    def _compute_unit_price(self):
        for quant in self:
            quant.unit_price = (quant.value / quant.quantity) if quant.quantity else 0.0


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

