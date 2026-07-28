# -*- coding: utf-8 -*-
import logging
from odoo import models, api, fields
from datetime import datetime, timedelta
import pytz

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

    def _get_reconstructed_stock_value(self, company_id, location_ids, target_date, category_ids=None, product_ids=None):
        cr = self.env.cr
        company_id_str = str(company_id)
        
        sq_pid_filter = "AND sq.product_id = ANY(%(product_ids)s)" if product_ids else ""
        sq_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if category_ids else ""
        sml_pid_filter = "AND sml.product_id = ANY(%(product_ids)s)" if product_ids else ""
        sml_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if category_ids else ""
        svl_pid_filter = "AND svl.product_id = ANY(%(product_ids)s)" if product_ids else ""
        svl_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if category_ids else ""
        
        params = {
            'selected_locations': location_ids or [0],
            'company_id_str': company_id_str,
            'company_id': company_id,
            'product_ids': product_ids or [],
            'category_ids': category_ids or [],
            'target_date': target_date,
        }
        
        query = f"""
            WITH current_quants AS (
                SELECT 
                    sq.product_id,
                    sq.lot_id,
                    sq.location_id,
                    SUM(sq.quantity) AS qty
                FROM stock_quant sq
                JOIN product_product pp ON sq.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sq.location_id = ANY(%(selected_locations)s)
                  {sq_pid_filter}
                  {sq_cat_filter}
                GROUP BY sq.product_id, sq.lot_id, sq.location_id
            ),
            inflows AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    sml.location_dest_id AS location_id,
                    SUM(sml.quantity) AS qty
                FROM stock_move_line sml
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sml.state = 'done'
                  AND sml.date > %(target_date)s
                  AND sml.location_dest_id = ANY(%(selected_locations)s)
                  {sml_pid_filter}
                  {sml_cat_filter}
                GROUP BY sml.product_id, sml.lot_id, sml.location_dest_id
            ),
            outflows AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    sml.location_id,
                    SUM(sml.quantity) AS qty
                FROM stock_move_line sml
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sml.state = 'done'
                  AND sml.date > %(target_date)s
                  AND sml.location_id = ANY(%(selected_locations)s)
                  {sml_pid_filter}
                  {sml_cat_filter}
                GROUP BY sml.product_id, sml.lot_id, sml.location_id
            ),
            reconstructed AS (
                SELECT 
                    COALESCE(c.product_id, i.product_id, o.product_id) AS product_id,
                    COALESCE(c.lot_id, i.lot_id, o.lot_id) AS lot_id,
                    COALESCE(c.location_id, i.location_id, o.location_id) AS location_id,
                    (COALESCE(c.qty, 0.0) - COALESCE(i.qty, 0.0) + COALESCE(o.qty, 0.0)) AS qty
                FROM current_quants c
                FULL OUTER JOIN inflows i 
                    ON c.product_id = i.product_id 
                    AND COALESCE(c.lot_id, 0) = COALESCE(i.lot_id, 0) 
                    AND c.location_id = i.location_id
                FULL OUTER JOIN outflows o 
                    ON COALESCE(c.product_id, i.product_id) = o.product_id 
                    AND COALESCE(COALESCE(c.lot_id, i.lot_id), 0) = COALESCE(o.lot_id, 0) 
                    AND COALESCE(c.location_id, i.location_id) = o.location_id
            ),
            hist_costs AS (
                SELECT 
                    svl.product_id,
                    CASE 
                        WHEN SUM(svl.quantity) > 0 THEN SUM(svl.value) / SUM(svl.quantity)
                        ELSE 0.0
                    END AS cost
                FROM stock_valuation_layer svl
                JOIN product_product pp ON svl.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE svl.create_date <= %(target_date)s
                  AND svl.company_id = %(company_id)s
                  {svl_pid_filter}
                  {svl_cat_filter}
                GROUP BY svl.product_id
            )
            SELECT COALESCE(SUM(r.qty * COALESCE(
                hc.cost,
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
            )), 0.0) AS total_val
            FROM reconstructed r
            JOIN product_product pp ON r.product_id = pp.id
            LEFT JOIN hist_costs hc ON r.product_id = hc.product_id
        """
        cr.execute(query, params)
        return float(cr.fetchone()[0] or 0.0)

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

        # Convert local timezone dates to UTC for database query alignment
        user_tz = pytz.timezone(self.env.user.tz or self._context.get('tz') or 'UTC')
        
        local_from = datetime.strptime(f"{date_from} 00:00:00", "%Y-%m-%d %H:%M:%S")
        local_to = datetime.strptime(f"{date_to} 23:59:59", "%Y-%m-%d %H:%M:%S")
        
        dt_from = user_tz.localize(local_from).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")
        dt_to = user_tz.localize(local_to).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")

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

        # Closing Value: reconstructed as of dt_to
        closing_val = self._get_reconstructed_stock_value(
            main_company_id, selected_location_ids, dt_to,
            expanded_category_ids, p_ids
        )

        # Opening Value: reconstructed as of dt_from (ensures exact match with Opening list view)
        opening_val = self._get_reconstructed_stock_value(
            main_company_id, selected_location_ids, dt_from,
            expanded_category_ids, p_ids
        )

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
              AND NOT (sm.location_id = ANY(%(selected_locations)s))
              {sm_pid_filter}
              {sm_cat_filter}
        """, kpi_params)
        receipt_val = float(cr.fetchone()[0] or 0.0)

        # Period Issues — stock moves FROM selected locations (derived via standard COGS equation to balance perfectly)
        issue_val = max(0.0, opening_val + receipt_val - closing_val)

        # Gate Entry Done, Receipt Pending (location filter excluded)
        ge_pending_picking_ids = self._get_gate_entry_pending_picking_ids(
            active_company_ids, dt_from, dt_to,
            expanded_category_ids, p_ids
        )
        gate_entry_pending_count = len(ge_pending_picking_ids)
        gate_entry_pending_val = 0.0

        if ge_pending_picking_ids:
            query_ge_val = f"""
                SELECT COALESCE(SUM(
                    COALESCE(NULLIF(sm.quantity, 0), sm.product_uom_qty) * COALESCE(
                        pol.price_unit,
                        (pprod.standard_price->>%(company_id_str)s)::numeric,
                        (pprod.standard_price->>'1')::numeric,
                        (pprod.standard_price->>'2')::numeric,
                        (pprod.standard_price->>'3')::numeric,
                        (pprod.standard_price->>'4')::numeric,
                        (pprod.standard_price->>'5')::numeric,
                        (pprod.standard_price->>'6')::numeric,
                        (pprod.standard_price->>'7')::numeric,
                        (pprod.standard_price->>'8')::numeric,
                        0.0
                    )
                ), 0.0)
                FROM stock_move sm
                JOIN product_product pprod ON sm.product_id = pprod.id
                JOIN product_template pt ON pprod.product_tmpl_id = pt.id
                LEFT JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
                WHERE sm.picking_id = ANY(%(picking_ids)s)
                  AND sm.state NOT IN ('done', 'cancel')
                  {sm_pid_filter}
                  {sm_cat_filter}
            """
            ge_val_params = dict(kpi_params)
            ge_val_params['picking_ids'] = ge_pending_picking_ids
            cr.execute(query_ge_val, ge_val_params)
            gate_entry_pending_val = float(cr.fetchone()[0] or 0.0)

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
                'gate_entry_pending_value': round(gate_entry_pending_val, 2),
                'gate_entry_pending_count': gate_entry_pending_count,
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
                -- Post-period receipts (after dt_to)
                SUM(CASE WHEN sm.date > %(dt_to)s
                          AND sm.location_dest_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS post_receipt_qty,
                SUM(CASE WHEN sm.date > %(dt_to)s
                          AND sm.location_dest_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_id = ANY(%(location_ids)s))
                     THEN COALESCE(svl.value, sm.quantity * COALESCE((pp.standard_price->>%(company_id_str)s)::numeric, 0.0))
                     ELSE 0.0 END)                                           AS post_receipt_val,
                -- Post-period issues (after dt_to)
                SUM(CASE WHEN sm.date > %(dt_to)s
                          AND sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN sm.quantity ELSE 0.0 END)                          AS post_issue_qty,
                SUM(CASE WHEN sm.date > %(dt_to)s
                          AND sm.location_id = ANY(%(location_ids)s)
                          AND NOT (sm.location_dest_id = ANY(%(location_ids)s))
                     THEN ABS(COALESCE(svl.value, sm.quantity * COALESCE((pp.standard_price->>%(company_id_str)s)::numeric, 0.0)))
                     ELSE 0.0 END)                                           AS post_issue_val
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
            
            post_receipt_qty = float(m.get('post_receipt_qty') or 0)
            post_receipt_val = float(m.get('post_receipt_val') or 0)
            post_issue_qty   = float(m.get('post_issue_qty') or 0)
            post_issue_val   = float(m.get('post_issue_val') or 0)
            
            closing_qty_current = float(row.get('closing_qty') or 0)
            closing_val_current = float(row.get('closing_val') or 0)
            
            # Reconstruct historical closing stock level as of dt_to
            closing_qty = closing_qty_current - post_receipt_qty + post_issue_qty
            closing_val = closing_val_current - post_receipt_val + post_issue_val
            
            # Calculate historical opening stock level as of dt_from
            opening_qty = closing_qty - receipt_qty + issue_qty
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
        """Compute stock aging buckets using FIFO receipt matching and standard_price (JSONB in Odoo 18)."""
        cr = self.env.cr
        company_id_str = str(company_id)

        params = {
            'location_ids': location_ids,
            'product_ids': product_ids or [],
            'product_ids_empty': not bool(product_ids),
            'category_ids': category_ids or [],
            'category_ids_empty': not bool(category_ids),
            'company_id_str': company_id_str,
        }

        # Step 1: Get current on-hand stock per product from stock_quant
        qty_q = """
            SELECT
                sq.product_id,
                sq.lot_id,
                sq.location_id,
                MAX(sq.in_date)                                              AS last_moved_date,
                pp.default_code                                              AS item_code,
                COALESCE(pt.name->>'en_US', pt.name::text)                   AS item_name,
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
                )                                                            AS unit_cost,
                SUM(sq.quantity)                                             AS total_qty
            FROM stock_quant sq
            JOIN product_product pp ON sq.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE sq.location_id = ANY(%(location_ids)s)
              AND (%(product_ids_empty)s OR sq.product_id = ANY(%(product_ids)s))
              AND (%(category_ids_empty)s OR pt.categ_id = ANY(%(category_ids)s))
            GROUP BY sq.product_id, sq.lot_id, sq.location_id, pp.default_code, pt.name, pp.standard_price
            HAVING SUM(sq.quantity) > 0
            ORDER BY COALESCE(pt.name->>'en_US', pt.name::text) ASC
            LIMIT 5000
        """
        cr.execute(qty_q, params)
        products = cr.dictfetchall()
        if not products:
            return []

        product_qty_map = {}
        for r in products:
            pid = r['product_id']
            qty = float(r['total_qty'] or 0)
            product_qty_map[pid] = product_qty_map.get(pid, 0.0) + qty

        # Get database start date (earliest done move date)
        cr.execute("SELECT MIN(date) FROM stock_move WHERE state = 'done'")
        min_date_row = cr.fetchone()
        db_start_date = min_date_row[0] if min_date_row and min_date_row[0] else None

        # Step 2: Fetch receipts from the last 365 days for FIFO ageing
        dt_to_parsed = datetime.strptime(dt_to[:10], '%Y-%m-%d')
        dt_limit = (dt_to_parsed - timedelta(days=365)).strftime('%Y-%m-%d 00:00:00')

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
            JOIN stock_location dest ON dest.id = sm.location_dest_id
            JOIN stock_location src ON src.id = sm.location_id
            LEFT JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            WHERE sm.state = 'done'
              AND dest.usage = 'internal'
              AND src.usage != 'internal'
              AND sm.date <= %(dt_to)s
              AND sm.date >= %(dt_limit)s
              AND sm.product_id = ANY(%(active_pids)s)
            ORDER BY sm.product_id, sm.date DESC
        """
        cr.execute(receipt_q, params)
        receipts = cr.dictfetchall()

        receipt_by_product = {}
        for r in receipts:
            r_copy = dict(r)
            r_copy['qty_left'] = float(r['quantity'] or 0.0)
            receipt_by_product.setdefault(r['product_id'], []).append(r_copy)

        result = []
        for p in products:
            prod_id   = p['product_id']
            qty_rem   = float(p['total_qty'] or 0)
            unit_cost = float(p['unit_cost'] or 0)

            aged = {k: {'qty': 0.0, 'val': 0.0}
                    for k in ('30', '60', '90', '120', '150', '180', '365', 'above')}

            for r in receipt_by_product.get(prod_id, []):
                if qty_rem <= 0:
                    break
                if r['qty_left'] <= 0:
                    continue
                matched  = min(qty_rem, r['qty_left'])
                r_cost   = float(r['unit_cost'] or 0) or unit_cost
                r_val    = matched * r_cost
                move_date = r['date']
                if isinstance(move_date, str):
                    move_date = datetime.strptime(move_date[:19], '%Y-%m-%d %H:%M:%S')
                age = (dt_to_parsed - move_date.replace(tzinfo=None)).days

                bucket = ('30' if age <= 30 else '60' if age <= 60 else '90' if age <= 90
                          else '120' if age <= 120 else '150' if age <= 150
                          else '180' if age <= 180 else '365' if age <= 365 else 'above')
                aged[bucket]['qty'] += matched
                aged[bucket]['val'] += r_val
                r['qty_left'] -= matched
                qty_rem -= matched

            if qty_rem > 0:
                if db_start_date:
                    db_start_dt = db_start_date.replace(tzinfo=None) if hasattr(db_start_date, 'replace') else db_start_date
                    max_possible_age = (dt_to_parsed - db_start_dt).days
                else:
                    max_possible_age = 9999
                
                bucket = ('30' if max_possible_age <= 30 else '60' if max_possible_age <= 60
                          else '90' if max_possible_age <= 90 else '120' if max_possible_age <= 120
                          else '150' if max_possible_age <= 150 else '180' if max_possible_age <= 180
                          else '365' if max_possible_age <= 365 else 'above')
                
                aged[bucket]['qty'] += qty_rem
                aged[bucket]['val'] += qty_rem * unit_cost

            total_qty = float(p['total_qty'] or 0)
            result.append({
                'product_id': prod_id,
                'lot_id':     p['lot_id'],
                'location_id': p['location_id'],
                'last_moved_date': p['last_moved_date'],
                'item_code':  p['item_code'] or 'N/A',
                'item_name':  p['item_name'],
                'total_qty':  round(total_qty, 4),
                'total_val':  round(total_qty * unit_cost, 2),
                'qty_30': round(aged['30']['qty'], 4),     'val_30': round(aged['30']['val'], 2),
                'qty_60': round(aged['60']['qty'], 4),     'val_60': round(aged['60']['val'], 2),
                'qty_90': round(aged['90']['qty'], 4),     'val_90': round(aged['90']['val'], 2),
                'qty_120': round(aged['120']['qty'], 4),   'val_120': round(aged['120']['val'], 2),
                'qty_150': round(aged['150']['qty'], 4),   'val_150': round(aged['150']['val'], 2),
                'qty_180': round(aged['180']['qty'], 4),   'val_180': round(aged['180']['val'], 2),
                'qty_360': round(aged['365']['qty'], 4),   'val_360': round(aged['365']['val'], 2),
                'qty_above': round(aged['above']['qty'], 4), 'val_above': round(aged['above']['val'], 2),
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
            active_company_ids = list(allowed_companies)
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []
        l_ids = [int(l) for l in location_ids] if location_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search([('id', 'child_of', c_ids)]).ids

        # Convert local timezone date to UTC for database query alignment
        user_tz = pytz.timezone(self.env.user.tz or self._context.get('tz') or 'UTC')
        local_from = datetime.strptime(f"{date_from} 00:00:00", "%Y-%m-%d %H:%M:%S")
        target_date_utc = user_tz.localize(local_from).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")

        selected_location_ids = l_ids or self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        cr = self.env.cr
        company_id_str = str(active_company_ids[0])
        company_id = active_company_ids[0]
        
        sq_pid_filter = "AND sq.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sq_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""
        sml_pid_filter = "AND sml.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sml_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""
        svl_pid_filter = "AND svl.product_id = ANY(%(product_ids)s)" if p_ids else ""
        svl_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""

        params = {
            'selected_locations': selected_location_ids,
            'company_id_str': company_id_str,
            'company_id': company_id,
            'product_ids': p_ids,
            'category_ids': expanded_category_ids,
            'target_date': target_date_utc,
        }

        # CTE query starting from stock_quant reconstructed with done moves and historical costs
        query = f"""
            WITH current_quants AS (
                SELECT 
                    sq.product_id,
                    sq.lot_id,
                    sq.location_id,
                    SUM(sq.quantity) AS qty
                FROM stock_quant sq
                JOIN product_product pp ON sq.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sq.location_id = ANY(%(selected_locations)s)
                  {sq_pid_filter}
                  {sq_cat_filter}
                GROUP BY sq.product_id, sq.lot_id, sq.location_id
            ),
            inflows AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    sml.location_dest_id AS location_id,
                    SUM(sml.quantity) AS qty
                FROM stock_move_line sml
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sml.state = 'done'
                  AND sml.date > %(target_date)s
                  AND sml.location_dest_id = ANY(%(selected_locations)s)
                  {sml_pid_filter}
                  {sml_cat_filter}
                GROUP BY sml.product_id, sml.lot_id, sml.location_dest_id
            ),
            outflows AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    sml.location_id,
                    SUM(sml.quantity) AS qty
                FROM stock_move_line sml
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sml.state = 'done'
                  AND sml.date > %(target_date)s
                  AND sml.location_id = ANY(%(selected_locations)s)
                  {sml_pid_filter}
                  {sml_cat_filter}
                GROUP BY sml.product_id, sml.lot_id, sml.location_id
            ),
            reconstructed AS (
                SELECT 
                    COALESCE(c.product_id, i.product_id, o.product_id) AS product_id,
                    COALESCE(c.lot_id, i.lot_id, o.lot_id) AS lot_id,
                    COALESCE(c.location_id, i.location_id, o.location_id) AS location_id,
                    (COALESCE(c.qty, 0.0) - COALESCE(i.qty, 0.0) + COALESCE(o.qty, 0.0)) AS qty
                FROM current_quants c
                FULL OUTER JOIN inflows i 
                    ON c.product_id = i.product_id 
                    AND COALESCE(c.lot_id, 0) = COALESCE(i.lot_id, 0) 
                    AND c.location_id = i.location_id
                FULL OUTER JOIN outflows o 
                    ON COALESCE(c.product_id, i.product_id) = o.product_id 
                    AND COALESCE(COALESCE(c.lot_id, i.lot_id), 0) = COALESCE(o.lot_id, 0) 
                    AND COALESCE(c.location_id, i.location_id) = o.location_id
            ),
            hist_costs AS (
                SELECT 
                    svl.product_id,
                    CASE 
                        WHEN SUM(svl.quantity) > 0 THEN SUM(svl.value) / SUM(svl.quantity)
                        ELSE 0.0
                    END AS cost
                FROM stock_valuation_layer svl
                JOIN product_product pp ON svl.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE svl.create_date <= %(target_date)s
                  AND svl.company_id = %(company_id)s
                  {svl_pid_filter}
                  {svl_cat_filter}
                GROUP BY svl.product_id
            )
            SELECT 
                r.product_id,
                r.lot_id,
                r.location_id,
                r.qty,
                (r.qty * COALESCE(
                    hc.cost,
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
                )) AS val
            FROM reconstructed r
            JOIN product_product pp ON r.product_id = pp.id
            LEFT JOIN hist_costs hc ON r.product_id = hc.product_id
            WHERE r.qty != 0
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
        action['name'] = f"Opening Stock Valuation (as of {date_from})"
        action['domain'] = [('id', 'in', lines.ids)]
        return action

    @api.model
    def action_open_closing_valuation(self, company_ids=None, date_to=None, category_ids=None, product_ids=None, location_ids=None):
        self = self.sudo()
        allowed_companies = self.env.companies.ids
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        else:
            active_company_ids = list(allowed_companies)
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

        # Convert local timezone date to UTC for database query alignment
        user_tz = pytz.timezone(self.env.user.tz or self._context.get('tz') or 'UTC')
        local_to = datetime.strptime(f"{date_to} 23:59:59", "%Y-%m-%d %H:%M:%S")
        target_date_utc = user_tz.localize(local_to).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")

        selected_location_ids = l_ids or self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        # 1. Clear old records created by current user
        self.env['zunax.opening.valuation.line'].search([('create_uid', '=', self.env.user.id)]).unlink()

        # 2. Fast query directly from stock_quant
        cr = self.env.cr
        company_id_str = str(active_company_ids[0])
        company_id = active_company_ids[0]
        
        sq_pid_filter = "AND sq.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sq_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""
        sml_pid_filter = "AND sml.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sml_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""
        svl_pid_filter = "AND svl.product_id = ANY(%(product_ids)s)" if p_ids else ""
        svl_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""

        params = {
            'selected_locations': selected_location_ids,
            'company_id_str': company_id_str,
            'company_id': company_id,
            'product_ids': p_ids,
            'category_ids': expanded_category_ids,
            'target_date': target_date_utc,
        }

        # CTE query starting from stock_quant reconstructed with done moves after date_to and historical costs
        query = f"""
            WITH current_quants AS (
                SELECT 
                    sq.product_id,
                    sq.lot_id,
                    sq.location_id,
                    SUM(sq.quantity) AS qty
                FROM stock_quant sq
                JOIN product_product pp ON sq.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sq.location_id = ANY(%(selected_locations)s)
                  {sq_pid_filter}
                  {sq_cat_filter}
                GROUP BY sq.product_id, sq.lot_id, sq.location_id
            ),
            inflows AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    sml.location_dest_id AS location_id,
                    SUM(sml.quantity) AS qty
                FROM stock_move_line sml
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sml.state = 'done'
                  AND sml.date > %(target_date)s
                  AND sml.location_dest_id = ANY(%(selected_locations)s)
                  {sml_pid_filter}
                  {sml_cat_filter}
                GROUP BY sml.product_id, sml.lot_id, sml.location_dest_id
            ),
            outflows AS (
                SELECT 
                    sml.product_id,
                    sml.lot_id,
                    sml.location_id,
                    SUM(sml.quantity) AS qty
                FROM stock_move_line sml
                JOIN product_product pp ON sml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE sml.state = 'done'
                  AND sml.date > %(target_date)s
                  AND sml.location_id = ANY(%(selected_locations)s)
                  {sml_pid_filter}
                  {sml_cat_filter}
                GROUP BY sml.product_id, sml.lot_id, sml.location_id
            ),
            reconstructed AS (
                SELECT 
                    COALESCE(c.product_id, i.product_id, o.product_id) AS product_id,
                    COALESCE(c.lot_id, i.lot_id, o.lot_id) AS lot_id,
                    COALESCE(c.location_id, i.location_id, o.location_id) AS location_id,
                    (COALESCE(c.qty, 0.0) - COALESCE(i.qty, 0.0) + COALESCE(o.qty, 0.0)) AS qty
                FROM current_quants c
                FULL OUTER JOIN inflows i 
                    ON c.product_id = i.product_id 
                    AND COALESCE(c.lot_id, 0) = COALESCE(i.lot_id, 0) 
                    AND c.location_id = i.location_id
                FULL OUTER JOIN outflows o 
                    ON COALESCE(c.product_id, i.product_id) = o.product_id 
                    AND COALESCE(COALESCE(c.lot_id, i.lot_id), 0) = COALESCE(o.lot_id, 0) 
                    AND COALESCE(c.location_id, i.location_id) = o.location_id
            ),
            hist_costs AS (
                SELECT 
                    svl.product_id,
                    CASE 
                        WHEN SUM(svl.quantity) > 0 THEN SUM(svl.value) / SUM(svl.quantity)
                        ELSE 0.0
                    END AS cost
                FROM stock_valuation_layer svl
                JOIN product_product pp ON svl.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE svl.create_date <= %(target_date)s
                  AND svl.company_id = %(company_id)s
                  {svl_pid_filter}
                  {svl_cat_filter}
                GROUP BY svl.product_id
            )
            SELECT 
                r.product_id,
                r.lot_id,
                r.location_id,
                r.qty,
                (r.qty * COALESCE(
                    hc.cost,
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
                )) AS val
            FROM reconstructed r
            JOIN product_product pp ON r.product_id = pp.id
            LEFT JOIN hist_costs hc ON r.product_id = hc.product_id
            WHERE r.qty != 0
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
        else:
            active_company_ids = list(allowed_companies)
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

        # Convert local timezone date to UTC for database query alignment
        user_tz = pytz.timezone(self.env.user.tz or self._context.get('tz') or 'UTC')
        local_to = datetime.strptime(f"{date_to[:10]} 23:59:59", "%Y-%m-%d %H:%M:%S")
        target_date_utc = user_tz.localize(local_to).astimezone(pytz.utc).strftime("%Y-%m-%d %H:%M:%S")

        selected_location_ids = l_ids
        if not selected_location_ids:
            selected_location_ids = self._get_location_ids(active_company_ids)
        if not selected_location_ids:
            selected_location_ids = [0]

        # 1. Clear old records created by current user
        self.env['zunax.opening.valuation.line'].search([('create_uid', '=', self.env.user.id)]).unlink()

        # 2. Get ageing data from the helper method
        ageing_data = self._get_ageing_analysis(
            active_company_ids[0], selected_location_ids, target_date_utc,
            expanded_category_ids, p_ids
        )

        # 3. Determine the bucket keys to read based on days_min and days_max
        if days_min == 181 and days_max == 365:
            qty_key = 'qty_360'
            val_key = 'val_360'
        elif days_min >= 366:
            qty_key = 'qty_above'
            val_key = 'val_above'
        else:
            qty_key = f'qty_{days_max}'
            val_key = f'val_{days_max}'

        # 4. Populate list view rows
        vals_list = []
        for line in ageing_data:
            qty = float(line.get(qty_key, 0.0))
            val = float(line.get(val_key, 0.0))
            if qty > 0:
                vals_list.append({
                    'product_id': line['product_id'],
                    'lot_id': line['lot_id'],
                    'location_id': line['location_id'],
                    'last_moved_date': line['last_moved_date'],
                    'quantity': qty,
                    'value': val,
                    'unit_price': round(val / qty, 2) if qty else 0.0,
                })

        lines = self.env['zunax.opening.valuation.line'].create(vals_list)

        # 5. Return the loaded action with custom title and domain
        action = self.env["ir.actions.actions"]._for_xml_id("zunax_inventory_dashboard.action_zunax_opening_valuation_lines")
        action['name'] = f"Stock Aged {days_min}-{days_max if days_max < 9999 else 'Above'} Days (as of {date_to})"
        action['domain'] = [('id', 'in', lines.ids)]
        return action

    def _get_gate_entry_pending_picking_ids(self, active_company_ids, dt_from, dt_to, expanded_category_ids=None, p_ids=None):
        """Find picking IDs where Gate Entry is confirmed but receipt state is not done (without location filter)."""
        cr = self.env.cr
        cr.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'gate_entry'
            );
        """)
        has_gate_entry = cr.fetchone()[0]
        if not has_gate_entry:
            return []

        cr.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'gate_entry_non_po'
            );
        """)
        has_gate_entry_non_po = cr.fetchone()[0]

        ge_non_po_join = "LEFT JOIN gate_entry_non_po gen ON gen.id = sp.gate_entry_num_for_non_po" if has_gate_entry_non_po else ""
        ge_non_po_cond = "OR (gen.id IS NOT NULL AND gen.state = 'confirm')" if has_gate_entry_non_po else ""
        ge_non_po_date = ", gen.entry_date" if has_gate_entry_non_po else ""

        sm_pid_filter = "AND sm.product_id = ANY(%(product_ids)s)" if p_ids else ""
        sm_cat_filter = "AND pt.categ_id = ANY(%(category_ids)s)" if expanded_category_ids else ""

        query = f"""
            SELECT DISTINCT sp.id
            FROM stock_picking sp
            JOIN stock_move sm ON sm.picking_id = sp.id
            JOIN product_product pp ON sm.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
            LEFT JOIN gate_entry_picking_rel rel ON rel.picking_id = sp.id
            LEFT JOIN gate_entry ge ON ge.id = rel.gate_entry_id
            {ge_non_po_join}
            WHERE sp.company_id = ANY(%(active_company_ids)s)
              AND sp.state NOT IN ('done', 'cancel')
              AND sm.state NOT IN ('done', 'cancel')
              AND spt.code = 'incoming'
              AND (
                  (ge.id IS NOT NULL AND ge.state = 'confirm')
                  OR (sp.gate_entry_num IS NOT NULL AND sp.gate_entry_num != '')
                  {ge_non_po_cond}
              )
              AND COALESCE(ge.entry_date {ge_non_po_date}, sp.scheduled_date, sp.date) >= %(dt_from)s
              AND COALESCE(ge.entry_date {ge_non_po_date}, sp.scheduled_date, sp.date) <= %(dt_to)s
              {sm_pid_filter}
              {sm_cat_filter}
        """
        params = {
            'active_company_ids': active_company_ids,
            'dt_from': dt_from,
            'dt_to': dt_to,
            'product_ids': p_ids or [],
            'category_ids': expanded_category_ids or [],
        }
        cr.execute(query, params)
        return [r[0] for r in cr.fetchall()]

    @api.model
    def action_open_gate_entry_pending_pickings(self, company_ids=None, date_from=None, date_to=None, category_ids=None, product_ids=None, location_ids=None):
        self = self.sudo()
        allowed_companies = self.env.companies.ids
        if company_ids:
            active_company_ids = [int(c) for c in company_ids if int(c) in allowed_companies]
        else:
            active_company_ids = [self.env.company.id]
        if not active_company_ids:
            active_company_ids = [self.env.company.id]

        c_ids = [int(c) for c in category_ids] if category_ids else []
        p_ids = [int(p) for p in product_ids] if product_ids else []

        expanded_category_ids = []
        if c_ids:
            expanded_category_ids = self.env['product.category'].search([('id', 'child_of', c_ids)]).ids

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

        picking_ids = self._get_gate_entry_pending_picking_ids(
            active_company_ids, dt_from, dt_to,
            expanded_category_ids, p_ids
        )

        return {
            'name': 'Gate Entry Done (GRN Pending) Pickings',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'views': [[False, 'list'], [False, 'form']],
            'domain': [('id', 'in', picking_ids)],
            'target': 'current',
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

    @api.depends('quantity', 'unit_price', 'company_id')
    def _compute_value(self):
        for quant in self:
            quant.value = quant.quantity * quant.unit_price
            if hasattr(quant, 'currency_id'):
                quant.currency_id = quant.company_id.currency_id or self.env.company.currency_id



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
    last_moved_date = fields.Datetime(string='Last Moved Date & Time')

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

