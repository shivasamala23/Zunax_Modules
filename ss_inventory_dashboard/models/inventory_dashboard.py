# -*- coding: utf-8 -*-
import logging
from odoo import models, api
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class InventoryDashboard(models.AbstractModel):
    _name = 'inventory.dashboard'
    _description = 'Inventory Report Dashboard'

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
    def get_filter_options(self, company_ids=None):
        """Fast call: returns only dropdown list data. Called once on page open."""
        allowed_companies = self.env.companies.ids
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        else:
            active_company_ids = [self.env.company.id]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        companies_list = self.env['res.company'].search_read(
            [('id', 'in', allowed_companies)], ['id', 'name'])
        warehouses_list = self.env['stock.warehouse'].search_read(
            [('company_id', 'in', active_company_ids)], ['id', 'name', 'company_id'])
        categories_list = self.env['product.category'].search_read(
            [], ['id', 'name', 'complete_name'], order='name ASC')
        products_list = self.env['product.product'].search_read(
            [('active', '=', True)], ['id', 'name', 'default_code'],
            limit=500, order='name ASC')
        partners_list = self.env['res.partner'].search_read(
            [('active', '=', True), ('supplier_rank', '>', 0)],
            ['id', 'name', 'ref'], limit=500, order='name ASC')

        return {
            'companies': companies_list,
            'warehouses': warehouses_list,
            'categories': categories_list,
            'products': products_list,
            'partners': partners_list,
        }

    @api.model
    def get_report_data(self, report_name, company_ids=None, warehouse_ids=None,
                        date_from=None, date_to=None,
                        category_ids=None, product_ids=None, partner_ids=None):
        """Lazy call: returns only one specific report's data. Called per tab."""
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
        part_ids = [int(p) for p in partner_ids] if partner_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search(
                [('id', 'child_of', c_ids)]).ids

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

        location_ids = self._get_location_ids(active_company_ids, w_ids)
        if not location_ids:
            location_ids = [0]

        if report_name == 'inventory_status':
            return self._get_inventory_status(
                main_company_id, location_ids, dt_from, dt_to,
                expanded_category_ids, p_ids)
        elif report_name == 'stock_ledger':
            return self._get_stock_ledger(
                main_company_id, location_ids, dt_from, dt_to,
                expanded_category_ids, p_ids, part_ids)
        elif report_name == 'ageing_analysis':
            return self._get_ageing_analysis(
                main_company_id, location_ids, dt_to,
                expanded_category_ids, p_ids)
        elif report_name == 'pending_po':
            return self._get_pending_po(
                active_company_ids, dt_from, dt_to,
                expanded_category_ids, p_ids, part_ids)
        return []

    @api.model
    def get_dashboard_data(self, company_ids=None, warehouse_ids=None,
                           date_from=None, date_to=None,
                           category_ids=None, product_ids=None, partner_ids=None):
        """Legacy combined call for Excel export compatibility."""
        allowed_companies = self.env.companies.ids
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        else:
            active_company_ids = [self.env.company.id]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        w_ids = [int(w) for w in warehouse_ids] if warehouse_ids else []
        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        part_ids = [int(p) for p in partner_ids] if partner_ids else []

        if not date_from and not date_to:
            current_year = datetime.now().year
            date_from = f"{current_year}-01-01"
            date_to = datetime.now().strftime('%Y-%m-%d')
        elif not date_from:
            date_from = "2020-01-01"
        elif not date_to:
            date_to = datetime.now().strftime('%Y-%m-%d')

        filter_opts = self.get_filter_options(company_ids=active_company_ids)
        kwargs = dict(
            company_ids=active_company_ids, warehouse_ids=w_ids,
            date_from=date_from, date_to=date_to,
            category_ids=c_ids, product_ids=p_ids, partner_ids=part_ids,
        )
        return {
            **filter_opts,
            'filters': {
                'company_ids': active_company_ids, 'warehouse_ids': w_ids,
                'date_from': date_from, 'date_to': date_to,
                'category_ids': c_ids, 'product_ids': p_ids, 'partner_ids': part_ids,
            },
            'reports': {
                'inventory_status': self.get_report_data('inventory_status', **kwargs),
                'stock_ledger':     self.get_report_data('stock_ledger',     **kwargs),
                'ageing_analysis':  self.get_report_data('ageing_analysis',  **kwargs),
                'pending_po':       self.get_report_data('pending_po',        **kwargs),
            }
        }

    # ──────────────────────────────────────────────────────────────────────────────
    # REPORT 1: Inventory Status
    # Fast path: stock_quant (pre-aggregated) for closing qty/val
    #            stock_move only for the selected period (date-bounded)
    # Opening qty = closing_qty - period_receipts + period_issues
    # ──────────────────────────────────────────────────────────────────────────────
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

        # Step 1: Get closing quantities from stock_quant (pre-computed by Odoo, very fast)
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
        # opening_qty = stock_quant_qty - all_receipts_since_dt_from + all_issues_since_dt_from
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
            # opening = current stock - everything received since dt_from + everything issued since dt_from
            all_recv  = float(m.get('all_receipts_since') or 0)
            all_issue = float(m.get('all_issues_since') or 0)
            opening_qty = closing_qty - all_recv + all_issue
            opening_val = closing_val - receipt_val + issue_val  # approximate

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

    # ──────────────────────────────────────────────────────────────────────────────
    # REPORT 2: Stock Ledger
    # Fast: stock_quant for opening balance, stock_move only for period
    # ──────────────────────────────────────────────────────────────────────────────
    def _get_stock_ledger(self, company_id, location_ids, dt_from, dt_to,
                          category_ids, product_ids, partner_ids):
        cr = self.env.cr
        lang = self.env.lang or 'en_US'
        company_id_str = str(company_id)

        params = {
            'location_ids': location_ids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'product_ids': product_ids or [],
            'product_ids_empty': not bool(product_ids),
            'category_ids': category_ids or [],
            'category_ids_empty': not bool(category_ids),
            'partner_ids': partner_ids or [],
            'partner_ids_empty': not bool(partner_ids),
            'lang': lang,
            'company_id_str': company_id_str,
        }

        # Step 1: Use stock_quant + post-period moves to compute opening balance at dt_from
        # opening_at_dt_from = current_qty - all_moves_from_dt_from_to_now
        opening_q = """
            SELECT
                sq.product_id,
                SUM(sq.quantity) AS current_qty
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(location_ids)s)
              AND (%(product_ids_empty)s OR sq.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
            GROUP BY sq.product_id
        """
        cr.execute(opening_q, params)
        current_qtys = {r['product_id']: float(r['current_qty'] or 0)
                        for r in cr.dictfetchall()}

        if not current_qtys:
            return []

        params['active_pids'] = list(current_qtys.keys())

        # Moves from dt_from to NOW (to derive opening balance by working backwards from current)
        since_q = """
            SELECT
                sm.product_id,
                SUM(CASE WHEN sm.location_dest_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END) AS receipts_since,
                SUM(CASE WHEN sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END) AS issues_since
            FROM stock_move sm
            WHERE sm.state = 'done'
              AND sm.date >= %(dt_from)s
              AND (sm.location_id = ANY(%(location_ids)s)
                   OR sm.location_dest_id = ANY(%(location_ids)s))
              AND sm.product_id = ANY(%(active_pids)s)
            GROUP BY sm.product_id
        """
        cr.execute(since_q, params)
        since_map = {r['product_id']: r for r in cr.dictfetchall()}

        # opening_qty at dt_from = current_qty - receipts_since + issues_since
        opening_balances = {}
        for pid, cur_qty in current_qtys.items():
            s = since_map.get(pid, {})
            opening_balances[pid] = cur_qty - float(s.get('receipts_since') or 0) + float(s.get('issues_since') or 0)

        # Step 2: Fetch period moves for the ledger lines
        ledger_q = """
            SELECT
                sm.product_id,
                pp.default_code                                              AS item_code,
                COALESCE(pt.name->>%(lang)s, pt.name->>'en_US')             AS item_name,
                sm.date,
                sm.reference,
                COALESCE(rp.name, 'No Vendor/Customer')                     AS partner_name,
                sm.quantity,
                sm.location_id,
                sm.location_dest_id,
                COALESCE(svl.value,
                    sm.quantity * COALESCE(
                        (pp.standard_price->>%(company_id_str)s)::numeric,
                        (pp.standard_price->>'1')::numeric, 0.0))            AS move_value,
                (
                    SELECT string_agg(sl.name, ', ')
                    FROM stock_move_line sml
                    JOIN stock_lot sl ON sml.lot_id = sl.id
                    WHERE sml.move_id = sm.id
                )                                                            AS lot_name
            FROM stock_move sm
            JOIN product_product pp ON sm.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            LEFT JOIN stock_picking sp ON sm.picking_id = sp.id
            LEFT JOIN res_partner rp ON COALESCE(sm.partner_id, sp.partner_id) = rp.id
            LEFT JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            WHERE sm.state = 'done'
              AND sm.date >= %(dt_from)s AND sm.date <= %(dt_to)s
              AND (sm.location_id = ANY(%(location_ids)s)
                   OR sm.location_dest_id = ANY(%(location_ids)s))
              AND sm.product_id = ANY(%(active_pids)s)
              AND (%(partner_ids_empty)s
                   OR COALESCE(sm.partner_id, sp.partner_id) = ANY(%(partner_ids)s))
            ORDER BY sm.product_id, sm.date ASC
            LIMIT 5000
        """
        cr.execute(ledger_q, params)
        moves = cr.dictfetchall()

        running_balances = opening_balances.copy()
        ledger_lines = []
        loc_set = set(location_ids)

        for m in moves:
            pid = m['product_id']
            curr_qty = running_balances.get(pid, 0.0)
            is_incoming = m['location_dest_id'] in loc_set and m['location_id'] not in loc_set
            is_outgoing = m['location_id'] in loc_set and m['location_dest_id'] not in loc_set
            if not is_incoming and not is_outgoing:
                continue

            qty_receipt = float(m['quantity']) if is_incoming else 0.0
            qty_issue   = float(m['quantity']) if is_outgoing else 0.0
            new_qty     = curr_qty + qty_receipt - qty_issue
            running_balances[pid] = new_qty

            ledger_lines.append({
                'product_id':  pid,
                'item_code':   m['item_code'] or 'N/A',
                'item_name':   m['item_name'],
                'date':        m['date'].strftime('%Y-%m-%d %H:%M:%S') if isinstance(m['date'], datetime) else str(m['date']),
                'reference':   m['reference'] or 'N/A',
                'partner':     m['partner_name'],
                'lot_name':    m['lot_name'] or '',
                'opening_qty': round(curr_qty, 4),
                'receipt_qty': round(qty_receipt, 4),
                'issue_qty':   round(qty_issue, 4),
                'closing_qty': round(new_qty, 4),
                'value':       round(abs(float(m['move_value'] or 0)), 2),
            })

        return ledger_lines

    # ──────────────────────────────────────────────────────────────────────────────
    # REPORT 3: Ageing Analysis
    # Fast: stock_quant for current quantities, stock_move only for recent receipts
    # ──────────────────────────────────────────────────────────────────────────────
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

        # Step 1: Get current stock from stock_quant (replaces the huge stock_move aggregation)
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

        # Step 2: Fetch receipts from the last 365 days only for FIFO ageing
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

    # ──────────────────────────────────────────────────────────────────────────────
    # REPORT 4: Pending PO — simple, already fast with LIMIT
    # ──────────────────────────────────────────────────────────────────────────────
    def _get_pending_po(self, company_ids, dt_from, dt_to,
                        category_ids, product_ids, partner_ids):
        cr = self.env.cr
        params = {
            'company_ids': company_ids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'product_ids': product_ids or [],
            'product_ids_empty': not bool(product_ids),
            'category_ids': category_ids or [],
            'category_ids_empty': not bool(category_ids),
            'partner_ids': partner_ids or [],
            'partner_ids_empty': not bool(partner_ids),
            'lang': self.env.lang or 'en_US',
        }
        query = """
            SELECT
                pp.id                                                         AS product_id,
                po.partner_id                                                 AS partner_id,
                po.name                                                       AS po_name,
                pp.default_code                                               AS item_code,
                rp.name                                                       AS partner_name,
                COALESCE(pt.name->>%(lang)s, pt.name->>'en_US', pol.name)    AS item_description,
                pol.product_qty                                               AS po_qty,
                (pol.product_qty - pol.qty_received)                          AS balance_po_qty
            FROM purchase_order_line pol
            JOIN purchase_order po  ON pol.order_id    = po.id
            JOIN product_product pp ON pol.product_id  = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            JOIN res_partner rp     ON po.partner_id   = rp.id
            WHERE po.state IN ('purchase', 'done')
              AND po.company_id = ANY(%(company_ids)s)
              AND (pol.product_qty - pol.qty_received) > 0
              AND (%(product_ids_empty)s OR pol.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id   = ANY(%(category_ids)s))
              AND (%(partner_ids_empty)s  OR po.partner_id = ANY(%(partner_ids)s))
              AND po.date_order >= %(dt_from)s AND po.date_order <= %(dt_to)s
            ORDER BY po.date_order DESC, po.name DESC
            LIMIT 2000
        """
        cr.execute(query, params)
        return cr.dictfetchall()

    @api.model
    def get_kpi_data(self, company_ids=None, warehouse_ids=None,
                     date_from=None, date_to=None,
                     category_ids=None, product_ids=None, partner_ids=None):
        """Dynamic KPI summary data calculation."""
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

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search(
                [('id', 'child_of', c_ids)]).ids

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

        location_ids = self._get_location_ids(active_company_ids, w_ids)
        if not location_ids:
            location_ids = [0]

        # 1. Fetch status report values
        status_data = self._get_inventory_status(
            main_company_id, location_ids, dt_from, dt_to,
            expanded_category_ids, p_ids)

        opening_val = sum(x.get('opening_val', 0.0) for x in status_data)
        receipt_val = sum(x.get('receipt_val', 0.0) for x in status_data)
        issue_val = sum(x.get('issue_val', 0.0) for x in status_data)
        closing_val = sum(x.get('closing_val', 0.0) for x in status_data)

        # 2. Fetch aging report values
        ageing_data = self._get_ageing_analysis(
            main_company_id, location_ids, dt_to,
            expanded_category_ids, p_ids)

        age_30 = sum(x.get('val_30', 0.0) for x in ageing_data)
        age_60 = sum(x.get('val_60', 0.0) for x in ageing_data)
        age_90 = sum(x.get('val_90', 0.0) for x in ageing_data)
        age_120 = sum(x.get('val_120', 0.0) for x in ageing_data)
        age_150 = sum(x.get('val_150', 0.0) for x in ageing_data)
        age_180 = sum(x.get('val_180', 0.0) for x in ageing_data)
        age_360 = sum(x.get('val_360', 0.0) for x in ageing_data)
        age_above = sum(x.get('val_above', 0.0) for x in ageing_data)

        return {
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
