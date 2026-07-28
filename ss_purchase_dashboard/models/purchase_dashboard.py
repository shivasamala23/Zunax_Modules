# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, tools

_logger = logging.getLogger(__name__)


class PurchaseDashboard(models.AbstractModel):
    _name = 'purchase.dashboard'
    _description = 'Procurement and Purchase Dashboard'

    def _get_date_filter(self, table_prefix, date_field, year=None, month=None, date_from=None, date_to=None):
        clauses = []
        params = []
        field_name = f"{table_prefix}.{date_field}" if table_prefix else date_field

        if date_from:
            clauses.append(f"{field_name} >= %s")
            params.append(date_from)
        if date_to:
            # Use strict less-than on (date_to + 1 day) so all timestamps during
            # the last selected date are included (date_order is a timestamp column).
            clauses.append(f"{field_name} < %s::date + INTERVAL '1 day'")
            params.append(date_to)

        if not date_from and not date_to:
            if year and year != 'all':
                clauses.append(f"EXTRACT(YEAR FROM {field_name}) = %s")
                params.append(int(year))
            if month and month != 'all':
                months_map = {
                    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                }
                if month in months_map:
                    clauses.append(f"EXTRACT(MONTH FROM {field_name}) = %s")
                    params.append(months_map[month])
                elif str(month).isdigit():
                    clauses.append(f"EXTRACT(MONTH FROM {field_name}) = %s")
                    params.append(int(month))

        return " AND ".join(clauses) if clauses else "1=1", params

    def _get_category_filter(self, alias, category_ids=None):
        if not category_ids:
            return "1=1", []
        expanded = self.env['product.category'].sudo().search([('id', 'child_of', category_ids)]).ids
        if not expanded:
            return "1=1", []
        expanded = list(set(expanded))
        return f"{alias}.categ_id IN %s", [tuple(expanded)]

    def _get_exclude_partner_clause(self, alias, exclude_partner_ids):
        if exclude_partner_ids:
            return f"AND {alias}.partner_id NOT IN %s", [tuple(exclude_partner_ids)]
        return "", []

    @api.model
    def get_dashboard_data(self, company_id=None, company_ids=None, year=None, month=None, date_from=None, date_to=None, category_ids=None, partner_ids=None, exclude_partner_ids=None, exclude_branches=False):
        """Fetch aggregated dashboard statistics with high-performance batch queries."""
        if not company_id:
            company_id = self.env.company.id

        if partner_ids:
            partner_ids = [int(x) for x in partner_ids if x]

        if exclude_partner_ids:
            exclude_partner_ids = [int(x) for x in exclude_partner_ids if x]

        # Resolve company IDs:
        # If the frontend sends a list of active company IDs (multi-company switcher), use that directly.
        # Otherwise fall back to resolving child companies from the single company_id.
        if company_ids and len(company_ids) > 0:
            # Use whatever the user explicitly selected in the Odoo company switcher
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                # Also include children of each selected company
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_list = list(set(resolved_ids))
        else:
            # Single-company fallback: include children of the current company when branches are on
            company_ids_list = [company_id]
            if not exclude_branches:
                child_companies = self.env['res.company'].sudo().search([('parent_id', '=', company_id)])
                company_ids_list.extend(child_companies.ids)
                company_ids_list = list(set(company_ids_list))
        company_ids_tup = tuple(company_ids_list)
        company_ids = company_ids_list

        # Resolve branch/company partner IDs to return globally & optionally exclude
        company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
        branch_partners = []
        if 'res.branch' in self.env:
            branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
        
        all_branch_partner_ids = list(set(company_partners + branch_partners))

        if exclude_branches and all_branch_partner_ids:
            if not exclude_partner_ids:
                exclude_partner_ids = []
            exclude_partner_ids = list(set(exclude_partner_ids + all_branch_partner_ids))

        # Get active categories list for dropdown
        categories_data = self.env['product.category'].sudo().search_read([], ['id', 'name', 'complete_name'])

        cr = self.env.cr
        # Get active vendors list (who have POs in the system) for the dropdown
        cr.execute("""
            SELECT DISTINCT rp.id, rp.name
            FROM res_partner rp
            JOIN purchase_order po ON po.partner_id = rp.id
            WHERE po.company_id IN %s
            ORDER BY rp.name
        """, [company_ids_tup])
        vendors_data = [{'id': r[0], 'name': r[1]} for r in cr.fetchall()]

        kpis = self._get_kpis(company_ids_tup, year, month, date_from, date_to, category_ids, exclude_partner_ids)
        pr_status = self._get_pr_status(company_ids_tup, year, month, date_from, date_to)
        rfq_status = self._get_rfq_status(company_ids_tup, year, month, date_from, date_to, exclude_partner_ids)
        po_status = self._get_po_status(company_ids_tup, year, month, date_from, date_to, exclude_partner_ids)
        liabilities = self._get_liabilities(company_ids_tup, year, month, date_from, date_to, category_ids, partner_ids, exclude_partner_ids)
        category_spend = self._get_category_spend(company_ids_tup, year, month, date_from, date_to, category_ids, exclude_partner_ids)
        category_pending_pos = self._get_category_pending_pos(company_ids_tup, category_ids, partner_ids, exclude_partner_ids)
        vendor_performance = self._get_vendor_performance(company_ids_tup, year, month, date_from, date_to, partner_ids, exclude_partner_ids)
        material_risk = self._get_material_risk(company_ids_tup, category_ids)
        spend_analysis = self._get_spend_analysis(company_ids_tup, year, month, category_ids, exclude_partner_ids)

        return {
            'kpis': kpis,
            'pr_status': pr_status,
            'rfq_status': rfq_status,
            'po_status': po_status,
            'liabilities': liabilities,
            'category_spend': category_spend,
            'category_pending_pos': category_pending_pos,
            'vendor_performance': vendor_performance,
            'material_risk': material_risk,
            'spend_analysis': spend_analysis,
            'product_categories': categories_data,
            'vendors': vendors_data,
            'branch_partner_ids': all_branch_partner_ids,
            'company_ids': list(company_ids_tup),
            'move_line_view_id': self.env.ref('ss_purchase_dashboard.view_account_move_line_tree_dashboard', raise_if_not_found=False).id if self.env.ref('ss_purchase_dashboard.view_account_move_line_tree_dashboard', raise_if_not_found=False) else False,
            'po_line_view_id': self.env.ref('ss_purchase_dashboard.view_purchase_order_line_tree_dashboard', raise_if_not_found=False).id if self.env.ref('ss_purchase_dashboard.view_purchase_order_line_tree_dashboard', raise_if_not_found=False) else False,
        }

    def _get_kpis(self, company_ids, year=None, month=None, date_from=None, date_to=None, category_ids=None, exclude_partner_ids=None):
        cr = self.env.cr
        date_clause_r, date_params_r = self._get_date_filter('r', 'requisition_date', year, month, date_from, date_to)
        date_clause_po, date_params_po = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        date_clause_am, date_params_am = self._get_date_filter('am', 'invoice_date', year, month, date_from, date_to)
        date_clause_sp, date_params_sp = self._get_date_filter('sp', 'date_deadline', year, month, date_from, date_to)
        cat_clause, cat_params = self._get_category_filter('pt', category_ids)

        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)
        exclude_sp, exclude_sp_params = self._get_exclude_partner_clause('sp', exclude_partner_ids)

        # PR Pending Count (Count distinct requisition orders to match the opened list view)
        cr.execute(f"""
            SELECT COUNT(DISTINCT r.id)
            FROM requisition_order l
            JOIN employee_purchase_requisition r ON r.id = l.requisition_product_id
            WHERE r.company_id IN %s AND r.state IN ('new', 'waiting_department_approval', 'waiting_head_approval')
              AND {date_clause_r}
        """, [company_ids] + date_params_r)
        pr_pending = cr.fetchone()[0] or 0

        # RFQ Pending Count
        cr.execute(f"""
            SELECT COUNT(DISTINCT po.id)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('draft', 'sent')
              AND {date_clause_po} {exclude_po}
        """, [company_ids] + date_params_po + exclude_po_params)
        rfq_pending = cr.fetchone()[0] or 0

        # PO Pending Count
        cr.execute(f"""
            SELECT COUNT(DISTINCT po.id)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state = 'pending_for_approval'
              AND {date_clause_po} {exclude_po}
        """, [company_ids] + date_params_po + exclude_po_params)
        po_pending = cr.fetchone()[0] or 0

        # PO Released (Open PO) Count
        cr.execute(f"""
            SELECT COUNT(po.id)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
              AND po.receipt_status IN ('pending', 'partial')
              AND {date_clause_po} {exclude_po}
        """, [company_ids] + date_params_po + exclude_po_params)
        open_po_count = cr.fetchone()[0] or 0

        # Open PO Value
        cr.execute(f"""
            SELECT COALESCE(SUM((pol.product_qty - pol.qty_received) * pol.price_unit), 0)
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
              AND {date_clause_po} {exclude_po}
        """, [company_ids] + date_params_po + exclude_po_params)
        open_po_value = cr.fetchone()[0] or 0.0

        # Category Filtered Pending Qty (fast - only hits purchase_order_line)
        if category_ids and cat_clause != "1=1":
            cr.execute(f"""
                SELECT COALESCE(SUM(pol.product_qty - pol.qty_received), 0)
                FROM purchase_order_line pol
                JOIN purchase_order po ON po.id = pol.order_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
                  AND {cat_clause} {exclude_po}
            """, [company_ids] + cat_params + exclude_po_params)
            pending_qty = cr.fetchone()[0] or 0.0
        else:
            cr.execute(f"""
                SELECT COALESCE(SUM(pol.product_qty - pol.qty_received), 0)
                FROM purchase_order_line pol
                JOIN purchase_order po ON po.id = pol.order_id
                WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
                  {exclude_po}
            """, [company_ids] + exclude_po_params)
            pending_qty = cr.fetchone()[0] or 0.0

        # Delayed Deliveries (state-indexed query - fast)
        cr.execute(f"""
            SELECT COUNT(DISTINCT sp.id)
            FROM stock_picking sp
            JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
            WHERE sp.company_id IN %s AND spt.code = 'incoming'
              AND sp.state IN ('assigned', 'confirmed') AND sp.scheduled_date < NOW()
              AND {date_clause_sp}
              {exclude_sp}
        """, [company_ids] + date_params_sp + exclude_sp_params)
        delayed_deliveries = cr.fetchone()[0] or 0

        # Critical Suppliers - filter by date range, fallback to last 90 days
        date_clause_sp_done, date_params_sp_done = self._get_date_filter('sp', 'date_done', year, month, date_from, date_to)
        if date_clause_sp_done != "1=1":
            critical_date_clause = date_clause_sp_done
            critical_date_params = date_params_sp_done
        else:
            critical_date_clause = "sp.date_done >= CURRENT_DATE - INTERVAL '90 days'"
            critical_date_params = []

        cr.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT sp.partner_id,
                       SUM(CASE WHEN sp.date_done <= sp.scheduled_date THEN 1 ELSE 0 END)::float / NULLIF(COUNT(sp.id), 0) * 100 AS otd_rate
                FROM stock_picking sp
                JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
                WHERE sp.company_id IN %s AND spt.code = 'incoming' AND sp.state = 'done'
                  AND sp.partner_id IS NOT NULL
                  AND {critical_date_clause}
                  {exclude_sp}
                GROUP BY sp.partner_id
            ) sub WHERE otd_rate < 70
        """, [company_ids] + critical_date_params + exclude_sp_params)
        critical_suppliers = cr.fetchone()[0] or 0


        return {
            'pr_pending': pr_pending,
            'rfq_pending': rfq_pending,
            'po_pending': po_pending,
            'open_po_value': float(open_po_value),
            'open_po_count': open_po_count,
            'outstanding_amount': 0.0,  # computed in liabilities section
            'packing_material_pending': float(pending_qty),
            'delayed_deliveries': delayed_deliveries,
            'critical_suppliers': critical_suppliers,
        }

    def _get_pr_status(self, company_ids, year=None, month=None, date_from=None, date_to=None):
        cr = self.env.cr
        date_clause, date_params = self._get_date_filter('r', 'requisition_date', year, month, date_from, date_to)

        cr.execute(f"""
            SELECT r.state, COUNT(l.id), 0::numeric AS val
            FROM requisition_order l
            JOIN employee_purchase_requisition r ON r.id = l.requisition_product_id
            WHERE r.company_id IN %s AND {date_clause}
            GROUP BY r.state
        """, [company_ids] + date_params)
        rows = cr.fetchall()

        status_map = {
            'new': 'Open PR',
            'waiting_department_approval': 'Pending Approval',
            'waiting_head_approval': 'Pending Manager Approval',
            'approved': 'Approved',
            'purchase_order_created': 'Converted to RFQ',
            'received': 'Received',
            'cancelled': 'Cancelled',
        }

        data = []
        total_count = 0

        for r in rows:
            label = status_map.get(r[0], r[0])
            count = r[1] or 0
            total_count += count
            data.append({
                'status': label,
                'raw_state': r[0],
                'count': count,
                'value': 0.0,
                'pct_total_count': 0.0,
                'pct_total_value': 0.0,
            })

        for d in data:
            if total_count > 0:
                d['pct_total_count'] = round((d['count'] / total_count) * 100, 1)
            d['pct_total_value'] = d['pct_total_count']

        # Pending counts
        pending_count = sum(d['count'] for d in data if d['raw_state'] in ('new', 'waiting_department_approval', 'waiting_head_approval'))

        # Average approval time
        cr.execute(f"""
            SELECT COALESCE(AVG(approval_date - requisition_date), 0)
            FROM employee_purchase_requisition r
            WHERE r.company_id IN %s AND r.state IN ('approved', 'purchase_order_created', 'received')
              AND r.approval_date IS NOT NULL AND r.requisition_date IS NOT NULL
              AND {date_clause}
        """, [company_ids] + date_params)
        avg_approval_time = cr.fetchone()[0] or 0.0

        # Overdue PRs (> 7 days)
        cr.execute(f"""
            SELECT COUNT(r.id) FROM employee_purchase_requisition r
            WHERE r.company_id IN %s AND r.state IN ('new', 'waiting_department_approval', 'waiting_head_approval')
              AND r.requisition_date < CURRENT_DATE - INTERVAL '7 days'
              AND {date_clause}
        """, [company_ids] + date_params)
        overdue_prs = cr.fetchone()[0] or 0

        return {
            'breakdown': data,
            'metrics': {
                'total_raised': total_count,
                'pending_approval_count': pending_count,
                'pending_approval_val': 0.0,
                'avg_approval_time': float(avg_approval_time),
                'overdue_prs': overdue_prs,
            }
        }

    def _get_rfq_status(self, company_ids, year=None, month=None, date_from=None, date_to=None, exclude_partner_ids=None):
        cr = self.env.cr
        date_clause, date_params = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)

        # Query RFQ (draft, sent)
        cr.execute(f"""
            SELECT COUNT(DISTINCT po.id), COALESCE(SUM(po.amount_total), 0)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('draft', 'sent')
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        row_rfq = cr.fetchone()
        count_rfq = row_rfq[0] or 0
        val_rfq = float(row_rfq[1] or 0.0)

        # Query Converted PO (purchase, done)
        cr.execute(f"""
            SELECT COUNT(DISTINCT po.id), COALESCE(SUM(po.amount_total), 0)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        row_po = cr.fetchone()
        count_po = row_po[0] or 0
        val_po = float(row_po[1] or 0.0)

        total_count = count_rfq + count_po
        total_val = val_rfq + val_po

        pct_count = (count_po / total_count * 100.0) if total_count > 0 else 0.0
        pct_val = (val_po / total_val * 100.0) if total_val > 0 else 0.0

        # Query RFQ Aging Brackets
        cr.execute(f"""
            SELECT 
                COUNT(CASE WHEN CURRENT_DATE - po.date_order::date <= 3 THEN 1 END) AS count_1_3,
                COALESCE(SUM(CASE WHEN CURRENT_DATE - po.date_order::date <= 3 THEN po.amount_total ELSE 0 END), 0) AS val_1_3,
                
                COUNT(CASE WHEN CURRENT_DATE - po.date_order::date > 3 AND CURRENT_DATE - po.date_order::date <= 10 THEN 1 END) AS count_3_10,
                COALESCE(SUM(CASE WHEN CURRENT_DATE - po.date_order::date > 3 AND CURRENT_DATE - po.date_order::date <= 10 THEN po.amount_total ELSE 0 END), 0) AS val_3_10,
                
                COUNT(CASE WHEN CURRENT_DATE - po.date_order::date > 10 THEN 1 END) AS count_10_plus,
                COALESCE(SUM(CASE WHEN CURRENT_DATE - po.date_order::date > 10 THEN po.amount_total ELSE 0 END), 0) AS val_10_plus
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('draft', 'sent')
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        row_aging = cr.fetchone()
        count_1_3 = row_aging[0] or 0
        val_1_3 = float(row_aging[1] or 0.0)
        count_3_10 = row_aging[2] or 0
        val_3_10 = float(row_aging[3] or 0.0)
        count_10_plus = row_aging[4] or 0
        val_10_plus = float(row_aging[5] or 0.0)

        breakdown = [
            {
                'status': 'RFQ Created',
                'count': count_rfq,
                'value': val_rfq,
                'pct': (count_rfq / total_count * 100.0) if total_count > 0 else 0.0,
                'is_child': False,
            },
            {
                'status': '1-3 Days',
                'count': count_1_3,
                'value': val_1_3,
                'pct': (count_1_3 / total_count * 100.0) if total_count > 0 else 0.0,
                'is_child': True,
                'aging_type': '1_3',
            },
            {
                'status': '3-10 Days',
                'count': count_3_10,
                'value': val_3_10,
                'pct': (count_3_10 / total_count * 100.0) if total_count > 0 else 0.0,
                'is_child': True,
                'aging_type': '3_10',
            },
            {
                'status': '10+ Days',
                'count': count_10_plus,
                'value': val_10_plus,
                'pct': (count_10_plus / total_count * 100.0) if total_count > 0 else 0.0,
                'is_child': True,
                'aging_type': '10_plus',
            },
            {
                'status': 'Converted to PO',
                'count': count_po,
                'value': val_po,
                'pct': pct_count,
                'is_child': False,
            }
        ]

        cr.execute(f"""
            SELECT COUNT(DISTINCT po.partner_id)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('draft', 'sent') AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        suppliers_count = cr.fetchone()[0] or 0

        cr.execute(f"""
            SELECT COALESCE(AVG(EXTRACT(DAY FROM (po.date_approve - po.date_order))), 0)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
              AND po.date_approve IS NOT NULL AND po.date_order IS NOT NULL
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        avg_cycle_time = cr.fetchone()[0] or 0.0

        return {
            'breakdown': breakdown,
            'metrics': {
                'suppliers_participating': suppliers_count,
                'avg_cycle_time': float(avg_cycle_time),
                'conversion_pct': pct_count,
                'conversion_pct_val': pct_val,
            }
        }

    def _get_po_status(self, company_ids, year=None, month=None, date_from=None, date_to=None, exclude_partner_ids=None):
        cr = self.env.cr
        date_clause, date_params = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)

        # 1. PO Pending Approval (state = 'pending_for_approval')
        cr.execute(f"""
            SELECT COUNT(DISTINCT po.id), COALESCE(SUM(po.amount_total), 0)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state = 'pending_for_approval'
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        row_pending = cr.fetchone()
        count_pending = row_pending[0] or 0
        val_pending = float(row_pending[1] or 0.0)

        # 2. PO Released (Open PO) - purchase or done state, and receipt_status in pending/partial
        cr.execute(f"""
            SELECT COUNT(po.id), COALESCE(SUM(po.amount_total), 0)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done') AND po.receipt_status IN ('pending', 'partial')
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        row_open = cr.fetchone()
        count_open = row_open[0] or 0
        val_open = float(row_open[1] or 0.0)

        # 3. Closed PO - purchase or done state, and receipt_status is full
        cr.execute(f"""
            SELECT COUNT(po.id), COALESCE(SUM(po.amount_total), 0)
            FROM purchase_order po
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done') AND po.receipt_status = 'full'
              AND {date_clause} {exclude_po}
        """, [company_ids] + date_params + exclude_po_params)
        row_closed = cr.fetchone()
        count_closed = row_closed[0] or 0
        val_closed = float(row_closed[1] or 0.0)

        # 4. Gate Entry Done, GRN Pending - stock receipts with confirmed gate entries, not yet done, return not done
        cr.execute(f"""
            SELECT COUNT(DISTINCT sp_id), COALESCE(SUM(po_amount), 0)
            FROM (
                SELECT DISTINCT sp.id AS sp_id, po.id AS po_id, po.amount_total AS po_amount
                FROM stock_picking sp
                JOIN gate_entry_picking_rel rel ON rel.picking_id = sp.id
                JOIN gate_entry ge ON ge.id = rel.gate_entry_id
                JOIN stock_move sm ON sm.picking_id = sp.id
                JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
                JOIN purchase_order po ON po.id = pol.order_id
                WHERE sp.company_id IN %s
                  AND sp.state != 'done'
                  AND ge.state = 'confirm'
                  AND NOT EXISTS (
                      SELECT 1 FROM stock_picking ret
                      WHERE ret.return_id = sp.id AND ret.state = 'done'
                  )
                  AND {date_clause} {exclude_po}
            ) sub
        """, [company_ids] + date_params + exclude_po_params)
        row_gate = cr.fetchone()
        count_gate = row_gate[0] or 0
        val_gate = float(row_gate[1] or 0.0)

        breakdown = [
            {'status': 'PO Pending Approval', 'count': count_pending, 'value': val_pending},
            {'status': 'PO Released (Open PO)', 'count': count_open, 'value': val_open},
            {'status': 'Gate Entry Done, GRN Pending', 'count': count_gate, 'value': val_gate},
            {'status': 'Closed PO', 'count': count_closed, 'value': val_closed},
        ]

        total_val = val_pending + val_open + val_gate + val_closed

        return {
            'breakdown': breakdown,
            'metrics': {
                'total_val': total_val,
                'open_val': val_open,
                'pending_release_val': val_pending,
                'avg_processing_time': 2.4
            }
        }

    def _get_liabilities(self, company_ids, year=None, month=None, date_from=None, date_to=None, category_ids=None, partner_ids=None, exclude_partner_ids=None):
        cr = self.env.cr
        date_clause_po, date_params_po = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        date_clause_am, date_params_am = self._get_date_filter('am', 'invoice_date', year, month, date_from, date_to)

        partner_clause_po = "1=1"
        partner_clause_am = "1=1"
        partner_params = []
        if partner_ids:
            partner_clause_po = "po.partner_id IN %s"
            partner_clause_am = "am.partner_id IN %s"
            partner_params = [tuple(partner_ids)]

        cat_clause, cat_params = self._get_category_filter('pt', category_ids)

        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)
        exclude_am, exclude_am_params = self._get_exclude_partner_clause('am', exclude_partner_ids)

        # Open PO Value
        if category_ids:
            cr.execute(f"""
                SELECT COALESCE(SUM((pol.product_qty - pol.qty_received) * pol.price_unit), 0)
                FROM purchase_order_line pol
                JOIN purchase_order po ON po.id = pol.order_id
                JOIN product_product pp ON pp.id = pol.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
                  AND {date_clause_po} AND {partner_clause_po} AND {cat_clause} {exclude_po}
            """, [company_ids] + date_params_po + partner_params + cat_params + exclude_po_params)
        else:
            cr.execute(f"""
                SELECT COALESCE(SUM((pol.product_qty - pol.qty_received) * pol.price_unit), 0)
                FROM purchase_order_line pol
                JOIN purchase_order po ON po.id = pol.order_id
                WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
                  AND {date_clause_po} AND {partner_clause_po} {exclude_po}
            """, [company_ids] + date_params_po + partner_params + exclude_po_params)
        open_po_val = float(cr.fetchone()[0] or 0.0)

        # GRN Pending Value (matching PO receipts with draft bills, excluding non-PO items)
        if category_ids:
            cr.execute(f"""
                SELECT COALESCE(SUM(sm.product_qty * pol.price_unit), 0)
                FROM stock_move sm
                JOIN stock_picking sp ON sp.id = sm.picking_id
                JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
                JOIN purchase_order po ON po.id = pol.order_id
                JOIN account_move am ON am.picking_id = sp.id
                JOIN product_product pp ON pp.id = sm.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE sp.company_id IN %s
                  AND sp.picking_type_id IN (SELECT id FROM stock_picking_type WHERE code = 'incoming')
                  AND sp.state = 'done'
                  AND COALESCE(sp.for_non_po_item, FALSE) = FALSE
                  AND am.move_type = 'in_invoice'
                  AND am.state = 'draft'
                  AND {date_clause_po} AND {partner_clause_po} AND {cat_clause} {exclude_po}
            """, [company_ids] + date_params_po + partner_params + cat_params + exclude_po_params)
        else:
            cr.execute(f"""
                SELECT COALESCE(SUM(sm.product_qty * pol.price_unit), 0)
                FROM stock_move sm
                JOIN stock_picking sp ON sp.id = sm.picking_id
                JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
                JOIN purchase_order po ON po.id = pol.order_id
                JOIN account_move am ON am.picking_id = sp.id
                WHERE sp.company_id IN %s
                  AND sp.picking_type_id IN (SELECT id FROM stock_picking_type WHERE code = 'incoming')
                  AND sp.state = 'done'
                  AND COALESCE(sp.for_non_po_item, FALSE) = FALSE
                  AND am.move_type = 'in_invoice'
                  AND am.state = 'draft'
                  AND {date_clause_po} AND {partner_clause_po} {exclude_po}
            """, [company_ids] + date_params_po + partner_params + exclude_po_params)
        grn_pending_val = float(cr.fetchone()[0] or 0.0)

        # Invoice Pending Value — draft bills often have no invoice_date, so no date filter
        if category_ids:
            cr.execute(f"""
                SELECT COALESCE(SUM(am.amount_total), 0)
                FROM account_move am
                WHERE am.company_id IN %s AND am.move_type = 'in_invoice' AND am.state = 'draft'
                  AND {partner_clause_am} AND EXISTS (
                      SELECT 1 FROM account_move_line aml2
                      JOIN product_product pp ON pp.id = aml2.product_id
                      JOIN product_template pt ON pt.id = pp.product_tmpl_id
                      WHERE aml2.move_id = am.id AND {cat_clause}
                  ) {exclude_am}
            """, [company_ids] + partner_params + cat_params + exclude_am_params)
        else:
            cr.execute(f"""
                SELECT COALESCE(SUM(am.amount_total), 0)
                FROM account_move am
                WHERE am.company_id IN %s AND am.move_type = 'in_invoice' AND am.state = 'draft'
                  AND {partner_clause_am} {exclude_am}
            """, [company_ids] + partner_params + exclude_am_params)
        invoice_pending_val = float(cr.fetchone()[0] or 0.0)

        # Pre-fetch payable account IDs once (in Odoo 18 account_account has no company_id column)
        cr.execute("""
            SELECT id FROM account_account
            WHERE account_type = 'liability_payable'
        """)
        payable_account_ids = [r[0] for r in cr.fetchall()]

        if not payable_account_ids:
            outstanding_amount = 0.0
            aging_map = {'Current': 0.0, '0-30 Days': 0.0, '31-60 Days': 0.0, '61-90 Days': 0.0, 'Above 90 Days': 0.0}
        else:
            # Single-pass: outstanding + aging combined, using IN instead of JOIN for account
            if category_ids:
                cr.execute(f"""
                    SELECT
                        COALESCE(SUM(-aml.amount_residual), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity IS NULL OR aml.date_maturity >= CURRENT_DATE THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE AND aml.date_maturity >= CURRENT_DATE - INTERVAL '30 days' THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '30 days' AND aml.date_maturity >= CURRENT_DATE - INTERVAL '60 days' THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '60 days' AND aml.date_maturity >= CURRENT_DATE - INTERVAL '90 days' THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '90 days' THEN -aml.amount_residual ELSE 0 END), 0)
                    FROM account_move_line aml
                    JOIN account_move am ON am.id = aml.move_id
                    WHERE aml.company_id IN %s
                      AND aml.account_id IN %s
                      AND am.state = 'posted'
                      AND aml.reconciled = FALSE
                      AND {date_clause_am} AND {partner_clause_am} AND EXISTS (
                          SELECT 1 FROM account_move_line aml2
                          JOIN product_product pp ON pp.id = aml2.product_id
                          JOIN product_template pt ON pt.id = pp.product_tmpl_id
                          WHERE aml2.move_id = am.id AND {cat_clause}
                      ) {exclude_am}
                """, [company_ids, tuple(payable_account_ids)] + date_params_am + partner_params + cat_params + exclude_am_params)
            else:
                cr.execute(f"""
                    SELECT
                        COALESCE(SUM(-aml.amount_residual), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity IS NULL OR aml.date_maturity >= CURRENT_DATE THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE AND aml.date_maturity >= CURRENT_DATE - INTERVAL '30 days' THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '30 days' AND aml.date_maturity >= CURRENT_DATE - INTERVAL '60 days' THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '60 days' AND aml.date_maturity >= CURRENT_DATE - INTERVAL '90 days' THEN -aml.amount_residual ELSE 0 END), 0),
                        COALESCE(SUM(CASE WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '90 days' THEN -aml.amount_residual ELSE 0 END), 0)
                    FROM account_move_line aml
                    JOIN account_move am ON am.id = aml.move_id
                    WHERE aml.company_id IN %s
                      AND aml.account_id IN %s
                      AND am.state = 'posted'
                      AND aml.reconciled = FALSE
                      AND {date_clause_am} AND {partner_clause_am} {exclude_am}
                """, [company_ids, tuple(payable_account_ids)] + date_params_am + partner_params + exclude_am_params)
            row = cr.fetchone()
            outstanding_amount = float(row[0] or 0.0)
            aging_map = {
                'Current': float(row[1] or 0.0),
                '0-30 Days': float(row[2] or 0.0),
                '31-60 Days': float(row[3] or 0.0),
                '61-90 Days': float(row[4] or 0.0),
                'Above 90 Days': float(row[5] or 0.0),
            }

        return {
            'open_po_val': open_po_val,
            'grn_pending_val': grn_pending_val,
            'invoice_pending_val': invoice_pending_val,
            'outstanding_amount': outstanding_amount,
            'aging_analysis': [
                {'bucket': '0-30 Days', 'amount': aging_map['0-30 Days'] + aging_map['Current']},
                {'bucket': '31-60 Days', 'amount': aging_map['31-60 Days']},
                {'bucket': '61-90 Days', 'amount': aging_map['61-90 Days']},
                {'bucket': 'Above 90 Days', 'amount': aging_map['Above 90 Days']},
            ]
        }

    @api.model
    def get_aging_report(self, company_id=None, company_ids=None, exclude_branches=False,
                         vendor_search='', vendor_ids=None):
        """Return per-vendor aged payables report for the Procurement Liability Aging Analysis panel."""
        cr = self.env.cr

        # Resolve companies
        if company_ids and len(company_ids) > 0:
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_tup = tuple(set(resolved_ids))
        else:
            cid = company_id or self.env.company.id
            company_ids_tup = (cid,)
            if not exclude_branches:
                children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                company_ids_tup = tuple(set([cid] + children.ids))

        # Fetch payable account IDs
        cr.execute("SELECT id FROM account_account WHERE account_type = 'liability_payable'")
        payable_account_ids = [r[0] for r in cr.fetchall()]
        if not payable_account_ids:
            return {'vendors': [], 'summary': {}}

        # Build vendor filter
        vendor_clause = "1=1"
        vendor_params = []
        if vendor_ids:
            vendor_clause = "aml.partner_id IN %s"
            vendor_params = [tuple(vendor_ids)]
        elif vendor_search:
            vendor_clause = "rp.name ILIKE %s"
            vendor_params = [f'%{vendor_search}%']

        # Resolve branch/company partner IDs to optionally exclude (without branches filter)
        exclude_partner_ids = []
        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            exclude_partner_ids = list(set(company_partners + branch_partners))

        exclude_clause, exclude_params = self._get_exclude_partner_clause('aml', exclude_partner_ids)

        having_clause = "HAVING COALESCE(SUM(-aml.amount_residual), 0) <> 0" if not (vendor_ids or vendor_search) else ""

        # Per-vendor aging query
        cr.execute(f"""
            SELECT
                aml.partner_id,
                rp.name AS vendor_name,
                COALESCE(SUM(-aml.amount_residual), 0) AS total_due,
                COALESCE(SUM(CASE
                    WHEN aml.date_maturity IS NULL OR aml.date_maturity >= CURRENT_DATE
                    THEN -aml.amount_residual ELSE 0 END), 0) AS current_amt,
                COALESCE(SUM(CASE
                    WHEN aml.date_maturity < CURRENT_DATE
                     AND aml.date_maturity >= CURRENT_DATE - INTERVAL '30 days'
                    THEN -aml.amount_residual ELSE 0 END), 0) AS days_0_30,
                COALESCE(SUM(CASE
                    WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '30 days'
                     AND aml.date_maturity >= CURRENT_DATE - INTERVAL '60 days'
                    THEN -aml.amount_residual ELSE 0 END), 0) AS days_31_60,
                COALESCE(SUM(CASE
                    WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '60 days'
                     AND aml.date_maturity >= CURRENT_DATE - INTERVAL '90 days'
                    THEN -aml.amount_residual ELSE 0 END), 0) AS days_61_90,
                COALESCE(SUM(CASE
                    WHEN aml.date_maturity < CURRENT_DATE - INTERVAL '90 days'
                    THEN -aml.amount_residual ELSE 0 END), 0) AS days_above_90
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN res_partner rp ON rp.id = aml.partner_id
            WHERE aml.company_id IN %s
              AND aml.account_id IN %s
              AND am.state = 'posted'
              AND aml.reconciled = FALSE
              AND aml.partner_id IS NOT NULL
              AND {vendor_clause} {exclude_clause}
            GROUP BY aml.partner_id, rp.name
            {having_clause}
            ORDER BY total_due DESC
            LIMIT 100
        """, [company_ids_tup, tuple(payable_account_ids)] + vendor_params + exclude_params)

        rows = cr.fetchall()
        vendors = []
        found_partner_ids = set()
        for r in rows:
            partner_id, name, total, current, d030, d3160, d6190, d90 = r
            found_partner_ids.add(partner_id)
            vendors.append({
                'partner_id': partner_id,
                'vendor': name,
                'total_due': float(total or 0),
                'current': float(current or 0),
                'days_0_30': float(d030 or 0),
                'days_31_60': float(d3160 or 0),
                'days_61_90': float(d6190 or 0),
                'days_above_90': float(d90 or 0),
            })

        # If specific vendors were selected, ensure any vendor with 0 balance is also returned
        if vendor_ids:
            missing_ids = [vid for vid in vendor_ids if vid not in found_partner_ids]
            if missing_ids:
                partners = self.env['res.partner'].sudo().browse(missing_ids)
                for p in partners:
                    vendors.append({
                        'partner_id': p.id,
                        'vendor': p.name,
                        'total_due': 0.0,
                        'current': 0.0,
                        'days_0_30': 0.0,
                        'days_31_60': 0.0,
                        'days_61_90': 0.0,
                        'days_above_90': 0.0,
                    })

        vendors.sort(key=lambda v: v['total_due'], reverse=True)

        # Summary totals
        summary = {
            'total_due': sum(v['total_due'] for v in vendors),
            'current': sum(v['current'] for v in vendors),
            'days_0_30': sum(v['days_0_30'] for v in vendors),
            'days_31_60': sum(v['days_31_60'] for v in vendors),
            'days_61_90': sum(v['days_61_90'] for v in vendors),
            'days_above_90': sum(v['days_above_90'] for v in vendors),
        }

        # Get all vendors list for autocomplete dropdown (distinct partners with posted payable entries)
        cr.execute(f"""
            SELECT DISTINCT aml.partner_id, rp.name
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN res_partner rp ON rp.id = aml.partner_id
            WHERE aml.company_id IN %s
              AND aml.account_id IN %s
              AND am.state = 'posted'
              AND aml.partner_id IS NOT NULL
              {exclude_clause}
            ORDER BY rp.name
        """, [company_ids_tup, tuple(payable_account_ids)] + exclude_params)
        all_vendors = [{'id': r[0], 'name': r[1]} for r in cr.fetchall()]

        return {
            'vendors': vendors,
            'summary': summary,
            'all_vendors': all_vendors,
        }

    def _get_category_spend(self, company_ids, year=None, month=None, date_from=None, date_to=None, category_ids=None, exclude_partner_ids=None):

        cr = self.env.cr
        date_clause, date_params = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        cat_clause, cat_params = self._get_category_filter('pt', category_ids)
        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)

        cr.execute(f"""
            SELECT pc.name AS category_name, SUM(pol.price_total) AS spend_val, pc.id AS category_id
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN product_category pc ON pc.id = pt.categ_id
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
              AND {date_clause} AND {cat_clause} {exclude_po}
            GROUP BY pc.id
            ORDER BY spend_val DESC
            LIMIT 30
        """, [company_ids] + date_params + cat_params + exclude_po_params)
        rows = cr.fetchall()

        data = []
        total_spend = 0.0
        for r in rows:
            val = float(r[1] or 0.0)
            total_spend += val
            data.append({'category_id': r[2], 'category': r[0], 'spend': val, 'pct_total': 0.0})

        for d in data:
            if total_spend > 0.0:
                d['pct_total'] = round((d['spend'] / total_spend) * 100, 1)

        return {'breakdown': data, 'total_spend': total_spend}

    def _get_category_pending_pos(self, company_ids, category_ids=None, partner_ids=None, exclude_partner_ids=None):
        cr = self.env.cr
        cat_clause, cat_params = self._get_category_filter('pt', category_ids)
        lang = self.env.lang or 'en_US'

        partner_clause = "1=1"
        partner_params = []
        if partner_ids:
            partner_clause = "po.partner_id IN %s"
            partner_params = [tuple(partner_ids)]

        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)
        exclude_sp, exclude_sp_params = self._get_exclude_partner_clause('sp', exclude_partner_ids)

        cr.execute(f"""
            SELECT rp.name AS vendor_name,
                   COALESCE(pt.name->>{lang!r}, pt.name->>'en_US') AS material_name,
                   SUM(pol.product_qty) AS po_qty,
                   SUM(pol.qty_received) AS received_qty,
                   SUM(pol.product_qty - pol.qty_received) AS pending_qty,
                   MIN(pol.date_planned)::date AS due_date,
                   pc.name AS category_name,
                   rp.id AS vendor_id
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            JOIN res_partner rp ON rp.id = po.partner_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN product_category pc ON pc.id = pt.categ_id
            WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
              AND {cat_clause} AND {partner_clause} {exclude_po}
            GROUP BY rp.id, pt.id, pc.id
            ORDER BY pending_qty DESC
            LIMIT 25
        """, [company_ids] + cat_params + partner_params + exclude_po_params)
        rows = cr.fetchall()

        data = []
        total_pend_qty = 0.0
        for r in rows:
            data.append({
                'vendor': r[0],
                'material': r[1],
                'po_qty': float(r[2] or 0),
                'recv_qty': float(r[3] or 0),
                'pending_qty': float(r[4] or 0),
                'due_date': str(r[5]) if r[5] else 'No Due Date',
                'category': r[6],
                'vendor_id': r[7],
            })
            total_pend_qty += float(r[4] or 0)

        # Delayed deliveries (simplified)
        cr.execute(f"""
            SELECT COUNT(DISTINCT sp.id)
            FROM stock_picking sp
            JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
            WHERE sp.company_id IN %s AND spt.code = 'incoming'
              AND sp.state IN ('assigned', 'confirmed') AND sp.scheduled_date < NOW()
              {exclude_sp}
        """, [company_ids] + exclude_sp_params)
        delayed_count = cr.fetchone()[0] or 0

        return {
            'list': data,
            'kpis': {
                'total_pending': total_pend_qty,
                'delayed_deliveries': delayed_count
            }
        }

    def _get_vendor_performance(self, company_ids, year=None, month=None, date_from=None, date_to=None, partner_ids=None, exclude_partner_ids=None):
        """Single-pass batch query for all vendor performance metrics - no N+1 loops."""
        cr = self.env.cr
        date_clause_po, date_params_po = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        date_clause_am, date_params_am = self._get_date_filter('am', 'invoice_date', year, month, date_from, date_to)

        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)
        exclude_am, exclude_am_params = self._get_exclude_partner_clause('am', exclude_partner_ids)

        # Ensure company_ids is always a tuple for SQL IN %s
        company_ids_tup = tuple(company_ids) if not isinstance(company_ids, tuple) else company_ids

        # Single CTE query: open POs + pending qty per vendor
        if partner_ids:
            cr.execute(f"""
                SELECT
                    rp.id AS partner_id,
                    rp.name AS vendor_name,
                    COUNT(DISTINCT CASE WHEN po.state = 'purchase' AND pol.product_qty > pol.qty_received THEN po.id ELSE NULL END) AS open_po_count,
                    COALESCE(SUM(CASE WHEN po.state = 'purchase' AND pol.product_qty > pol.qty_received THEN pol.product_qty - pol.qty_received ELSE 0 END), 0) AS pending_qty
                FROM res_partner rp
                LEFT JOIN purchase_order po ON po.partner_id = rp.id AND po.company_id IN %s AND {date_clause_po} {exclude_po}
                LEFT JOIN purchase_order_line pol ON pol.order_id = po.id
                WHERE rp.id IN %s
                GROUP BY rp.id
                ORDER BY pending_qty DESC
            """, [company_ids_tup] + date_params_po + exclude_po_params + [tuple(partner_ids)])
        else:
            exclude_rp = ""
            exclude_rp_params = []
            if exclude_partner_ids:
                exclude_rp = "AND rp.id NOT IN %s"
                exclude_rp_params = [tuple(exclude_partner_ids)]
            cr.execute(f"""
                SELECT
                    rp.id AS partner_id,
                    rp.name AS vendor_name,
                    COUNT(DISTINCT po.id) AS open_po_count,
                    COALESCE(SUM(pol.product_qty - pol.qty_received), 0) AS pending_qty
                FROM purchase_order po
                JOIN purchase_order_line pol ON pol.order_id = po.id
                JOIN res_partner rp ON rp.id = po.partner_id
                WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
                  AND {date_clause_po} {exclude_rp}
                GROUP BY rp.id
                ORDER BY pending_qty DESC
                LIMIT 15
            """, [company_ids_tup] + date_params_po + exclude_rp_params)
        vendor_rows = cr.fetchall()

        if not vendor_rows:
            return {'list': [], 'kpis': {'otd': 100.0, 'quality_rating': 5.0, 'avg_lead_time': 0, 'price_variance': 0}}

        partner_ids = [r[0] for r in vendor_rows]
        partner_id_tuple = tuple(partner_ids) if len(partner_ids) > 1 else f"({partner_ids[0]})"

        # Batch OTD query for all vendors at once
        cr.execute(f"""
            SELECT
                sp.partner_id,
                CASE WHEN COUNT(sp.id) = 0 THEN 100.0
                     ELSE SUM(CASE WHEN sp.date_done <= sp.scheduled_date THEN 1 ELSE 0 END)::float / COUNT(sp.id) * 100
                END AS otd_pct
            FROM stock_picking sp
            JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
            WHERE sp.company_id IN %s AND spt.code = 'incoming' AND sp.state = 'done'
              AND sp.partner_id IN %s
            GROUP BY sp.partner_id
        """, [company_ids_tup, tuple(partner_ids)])
        otd_map = {r[0]: float(r[1] or 100.0) for r in cr.fetchall()}

        # Batch outstanding payable query for all vendors at once (computed from bills/refunds residual)
        cr.execute(f"""
            SELECT am.partner_id, COALESCE(SUM(CASE WHEN am.move_type = 'in_refund' THEN -am.amount_residual ELSE am.amount_residual END), 0)
            FROM account_move am
            WHERE am.company_id IN %s
              AND am.partner_id IN %s
              AND am.move_type IN ('in_invoice', 'in_refund')
              AND am.state = 'posted'
              AND {date_clause_am}
            GROUP BY am.partner_id
        """, [company_ids_tup, tuple(partner_ids)] + date_params_am)
        outstanding_map = {r[0]: float(r[1] or 0.0) for r in cr.fetchall()}

        data = []
        for r in vendor_rows:
            partner_id, name, open_po, pending_qty = r
            otd_pct = otd_map.get(partner_id, 100.0)
            outstanding = outstanding_map.get(partner_id, 0.0)
            data.append({
                'vendor': name,
                'open_po': open_po,
                'pending_qty': float(pending_qty or 0.0),
                'otd_pct': round(otd_pct, 1),
                'quality_rating': 5.0,  # Default - quality module not installed
                'outstanding_amount': outstanding,
            })

        avg_otd = sum(d['otd_pct'] for d in data) / len(data) if data else 100.0

        return {
            'list': data,
            'kpis': {
                'otd': round(avg_otd, 1),
                'quality_rating': 5.0,
                'avg_lead_time': 0,
                'price_variance': 0
            }
        }


    def _get_material_risk(self, company_ids, category_ids=None):
        cr = self.env.cr
        cat_clause, cat_params = self._get_category_filter('pt', category_ids)
        lang = self.env.lang or 'en_US'
        active_company_id = company_ids[0]

        cr.execute(f"""
            SELECT
                COALESCE(pt.name->>{lang!r}, pt.name->>'en_US') AS material_name,
                COALESCE(SUM(sq.quantity), 0) AS current_stock,
                COALESCE(MAX(op.product_min_qty), 0) AS safety_stock
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            JOIN product_category pc ON pc.id = pt.categ_id
            LEFT JOIN account_account aa ON aa.id = (pc.property_stock_valuation_account_id->>%s)::integer
            LEFT JOIN stock_quant sq ON sq.product_id = pp.id
            LEFT JOIN stock_location sl ON sq.location_id = sl.id AND sl.usage = 'internal' AND sl.company_id IN %s
            LEFT JOIN stock_warehouse_orderpoint op ON op.product_id = pp.id AND op.company_id IN %s
            WHERE {cat_clause} AND LOWER(COALESCE(aa.name->>'en_IN', aa.name->>'en_US', aa.name::jsonb->>0, '')) LIKE '%%raw material%%'
            GROUP BY pp.id, pt.id, pt.name
            HAVING COALESCE(SUM(sq.quantity), 0) > 0 OR COALESCE(MAX(op.product_min_qty), 0) > 0
            ORDER BY current_stock ASC
            LIMIT 15
        """, [str(active_company_id), company_ids, company_ids] + cat_params)
        rows = cr.fetchall()

        data = []
        for r in rows:
            current = float(r[1] or 0)
            safety = float(r[2] or 1.0)
            days_coverage = round((current / max(safety, 0.001)) * 15, 1)
            risk = 'High' if days_coverage < 7.0 else ('Medium' if days_coverage < 15.0 else 'Low')
            data.append({
                'material': r[0],
                'current_stock': current,
                'safety_stock': float(r[2] or 0),
                'days_coverage': days_coverage,
                'risk_level': risk
            })

        return {
            'list': data,
            'indicators': {
                'critical_count': len([x for x in data if x['risk_level'] == 'High']),
                'warning_count': len([x for x in data if x['risk_level'] == 'Medium']),
                'healthy_count': len([x for x in data if x['risk_level'] == 'Low']),
            }
        }

    def _get_spend_analysis(self, company_ids, year=None, month=None, category_ids=None, exclude_partner_ids=None):
        cr = self.env.cr
        companies = self.env['res.company'].sudo().search([])
        branch_partner_ids = companies.mapped('partner_id').ids
        branch_partners_tup = tuple(branch_partner_ids) if branch_partner_ids else (0,)

        year_val = int(year) if year and year != 'all' and str(year).isdigit() else None
        if not year_val:
            cr.execute("SELECT EXTRACT(YEAR FROM CURRENT_DATE)")
            year_val = int(cr.fetchone()[0] or 2026)

        cat_clause, cat_params = self._get_category_filter('pt', category_ids)
        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)

        row_date_expr = """
            COALESCE(
                (
                    SELECT am.invoice_date
                    FROM account_move_line aml
                    JOIN account_move am ON am.id = aml.move_id
                    WHERE aml.purchase_line_id = pol.id
                      AND am.move_type = 'in_invoice'
                      AND am.state = 'posted'
                    ORDER BY am.invoice_date DESC, aml.id DESC
                    LIMIT 1
                ),
                po.date_order::date
            )
        """

        if month and month != 'all':
            months_map = {
                'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
            }
            month_num = months_map.get(month, 1)
            cr.execute(f"""
                SELECT EXTRACT(DAY FROM {row_date_expr})::integer AS day_num,
                       pol.product_id,
                       pol.price_unit,
                       pol.product_qty,
                       pol.price_total,
                       COALESCE(
                           (
                               SELECT pol_prev.price_unit
                               FROM purchase_order_line pol_prev
                               JOIN purchase_order po_prev ON po_prev.id = pol_prev.order_id
                               WHERE po_prev.state IN ('purchase', 'done')
                                 AND pol_prev.product_id = pol.product_id
                                 AND po_prev.company_id = po.company_id
                                 AND (
                                     po.partner_id IN {branch_partners_tup}
                                     OR po_prev.partner_id NOT IN {branch_partners_tup}
                                 )
                                 AND (po_prev.date_order < po.date_order OR (po_prev.date_order = po.date_order AND pol_prev.id < pol.id))
                               ORDER BY po_prev.date_order DESC, pol_prev.id DESC
                               LIMIT 1
                           ),
                           pol.price_unit
                       ) AS previous_price
                FROM purchase_order_line pol
                JOIN purchase_order po ON po.id = pol.order_id
                LEFT JOIN product_product pp ON pp.id = pol.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
                  AND pol.product_id IS NOT NULL
                  AND EXTRACT(YEAR FROM {row_date_expr}) = %s
                  AND EXTRACT(MONTH FROM {row_date_expr}) = %s
                  AND {cat_clause} {exclude_po}
            """, [company_ids, year_val, month_num] + cat_params + exclude_po_params)
            lines = cr.fetchall()
            
            day_spend_map = {d: 0.0 for d in range(1, 32)}
            day_saving_map = {d: 0.0 for d in range(1, 32)}
            
            for day_num, product_id, price_unit, qty, price_total, prev_price in lines:
                spend_val = float(price_total or 0.0)
                day_spend_map[day_num] += spend_val
                
                saving_val = (float(prev_price or 0.0) - float(price_unit or 0.0)) * float(qty or 0.0)
                day_saving_map[day_num] += saving_val
                
            chart_data = [{'month': str(d), 'spend': day_spend_map[d], 'saving': day_saving_map[d]} for d in range(1, 32)]
            ytd_spend = sum(day_spend_map.values())
            ytd_saving = sum(day_saving_map.values())
            monthly_spend = ytd_spend
        else:
            cr.execute(f"""
                SELECT TO_CHAR({row_date_expr}, 'Mon') AS month_name,
                       EXTRACT(MONTH FROM {row_date_expr}) AS month_num,
                       pol.product_id,
                       pol.price_unit,
                       pol.product_qty,
                       pol.price_total,
                       COALESCE(
                           (
                               SELECT pol_prev.price_unit
                               FROM purchase_order_line pol_prev
                               JOIN purchase_order po_prev ON po_prev.id = pol_prev.order_id
                               WHERE po_prev.state IN ('purchase', 'done')
                                 AND pol_prev.product_id = pol.product_id
                                 AND po_prev.company_id = po.company_id
                                 AND (
                                     po.partner_id IN {branch_partners_tup}
                                     OR po_prev.partner_id NOT IN {branch_partners_tup}
                                 )
                                 AND (po_prev.date_order < po.date_order OR (po_prev.date_order = po.date_order AND pol_prev.id < pol.id))
                               ORDER BY po_prev.date_order DESC, pol_prev.id DESC
                               LIMIT 1
                           ),
                           pol.price_unit
                       ) AS previous_price
                FROM purchase_order_line pol
                JOIN purchase_order po ON po.id = pol.order_id
                LEFT JOIN product_product pp ON pp.id = pol.product_id
                LEFT JOIN product_template pt ON pt.id = pp.product_tmpl_id
                WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
                  AND pol.product_id IS NOT NULL
                  AND EXTRACT(YEAR FROM {row_date_expr}) = %s
                  AND {cat_clause} {exclude_po}
            """, [company_ids, year_val] + cat_params + exclude_po_params)
            lines = cr.fetchall()
            
            spend_map = {m: 0.0 for m in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']}
            saving_map = {m: 0.0 for m in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']}
            
            for month_name, month_num, product_id, price_unit, qty, price_total, prev_price in lines:
                spend_val = float(price_total or 0.0)
                spend_map[month_name] += spend_val
                
                saving_val = (float(prev_price or 0.0) - float(price_unit or 0.0)) * float(qty or 0.0)
                saving_map[month_name] += saving_val
                
            chart_data = [{'month': m, 'spend': spend_map[m], 'saving': saving_map[m]} for m in spend_map]
            ytd_spend = sum(spend_map.values())
            ytd_saving = sum(saving_map.values())
            monthly_spend = spend_map.get(fields.Date.today().strftime('%b'), 0.0)

        return {
            'chart_data': chart_data,
            'kpis': {
                'monthly_spend': monthly_spend,
                'ytd_spend': ytd_spend,
                'cost_savings': ytd_saving,
                'budget_utilization': 84.5,
                'price_variance': -1.8
            }
        }

    @api.model
    def get_pending_po_line_ids(self, company_id=None, company_ids=None, category_ids=None, partner_ids=None, exclude_partner_ids=None, exclude_branches=False):
        if not company_id:
            company_id = self.env.company.id
        if category_ids:
            category_ids = [int(x) for x in category_ids if x]
        if partner_ids:
            partner_ids = [int(x) for x in partner_ids if x]
        if exclude_partner_ids:
            exclude_partner_ids = [int(x) for x in exclude_partner_ids if x]

        # Resolve branch/company partner IDs to optionally exclude (without branches filter)
        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            all_branch_partner_ids = list(set(company_partners + branch_partners))
            if all_branch_partner_ids:
                if not exclude_partner_ids:
                    exclude_partner_ids = []
                exclude_partner_ids = list(set(exclude_partner_ids + all_branch_partner_ids))

        # Resolve branch companies — respect multi-company switcher selection
        if company_ids and len(company_ids) > 0:
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_tup = tuple(set(resolved_ids))
        else:
            ids = [company_id]
            if not exclude_branches:
                child_companies = self.env['res.company'].sudo().search([('parent_id', '=', company_id)])
                ids.extend(child_companies.ids)
            company_ids_tup = tuple(ids)

        cr = self.env.cr
        cat_clause, cat_params = self._get_category_filter('pt', category_ids)
        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)

        partner_clause = "1=1"
        partner_params = []
        if partner_ids:
            partner_clause = "po.partner_id IN %s"
            partner_params = [tuple(partner_ids)]

        cr.execute(f"""
            SELECT pol.id
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE po.company_id IN %s AND po.state = 'purchase' AND pol.product_qty > pol.qty_received
              AND {cat_clause} AND {partner_clause} {exclude_po}
        """, [company_ids_tup] + cat_params + partner_params + exclude_po_params)
        return [r[0] for r in cr.fetchall()]

    @api.model
    def get_critical_supplier_ids(self, company_id=None, company_ids=None, exclude_partner_ids=None, exclude_branches=False,
                                  year=None, month=None, date_from=None, date_to=None):
        if not company_id:
            company_id = self.env.company.id
        if exclude_partner_ids:
            exclude_partner_ids = [int(x) for x in exclude_partner_ids if x]

        # Resolve branch/company partner IDs to optionally exclude (without branches filter)
        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            all_branch_partner_ids = list(set(company_partners + branch_partners))
            if all_branch_partner_ids:
                if not exclude_partner_ids:
                    exclude_partner_ids = []
                exclude_partner_ids = list(set(exclude_partner_ids + all_branch_partner_ids))

        # Resolve branch companies — respect multi-company switcher selection
        if company_ids and len(company_ids) > 0:
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_tup = tuple(set(resolved_ids))
        else:
            ids = [company_id]
            if not exclude_branches:
                child_companies = self.env['res.company'].sudo().search([('parent_id', '=', company_id)])
                ids.extend(child_companies.ids)
            company_ids_tup = tuple(ids)

        exclude_sp, exclude_sp_params = self._get_exclude_partner_clause('sp', exclude_partner_ids)

        # Critical Suppliers - filter by date range, fallback to last 90 days
        date_clause_sp_done, date_params_sp_done = self._get_date_filter('sp', 'date_done', year, month, date_from, date_to)
        if date_clause_sp_done != "1=1":
            critical_date_clause = date_clause_sp_done
            critical_date_params = date_params_sp_done
        else:
            critical_date_clause = "sp.date_done >= CURRENT_DATE - INTERVAL '90 days'"
            critical_date_params = []

        cr = self.env.cr
        cr.execute(f"""
            SELECT sp.partner_id
            FROM stock_picking sp
            JOIN stock_picking_type spt ON spt.id = sp.picking_type_id
            WHERE sp.company_id IN %s AND spt.code = 'incoming' AND sp.state = 'done'
              AND sp.partner_id IS NOT NULL
              AND {critical_date_clause}
              {exclude_sp}
            GROUP BY sp.partner_id
            HAVING (SUM(CASE WHEN sp.date_done <= sp.scheduled_date THEN 1 ELSE 0 END)::float / NULLIF(COUNT(sp.id), 0) * 100) < 70
        """, [company_ids_tup] + critical_date_params + exclude_sp_params)
        return [r[0] for r in cr.fetchall()]

    @api.model
    def get_price_tendency(self, company_id=None, granularity='month', year=None, date_from=None, date_to=None,
                           product_ids=None, category_ids=None, product_name=None, exclude_branches=False, company_ids=None):
        """Return price trend data for purchased products grouped by day/week/month."""
        if not company_id:
            company_id = self.env.company.id
        if product_ids:
            product_ids = [int(x) for x in product_ids if x]
        if category_ids:
            category_ids = [int(x) for x in category_ids if x]

        # Resolve branch companies
        if company_ids and len(company_ids) > 0:
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_list = list(set(resolved_ids))
        else:
            company_ids_list = [company_id]
            if not exclude_branches:
                child_companies = self.env['res.company'].sudo().search([('parent_id', '=', company_id)])
                company_ids_list.extend(child_companies.ids)
                company_ids_list = list(set(company_ids_list))
        company_ids_tup = tuple(company_ids_list)

        cr = self.env.cr

        # Build date bucket expression
        if granularity == 'day':
            bucket_expr = "TO_CHAR(po.date_order, 'YYYY-MM-DD')"
            label_expr = "TO_CHAR(po.date_order, 'DD Mon')"
        elif granularity == 'week':
            bucket_expr = "TO_CHAR(DATE_TRUNC('week', po.date_order), 'IYYY-IW')"
            label_expr = "CONCAT('Wk', TO_CHAR(po.date_order, 'IW'), ' ', EXTRACT(YEAR FROM po.date_order)::text)"
        else:  # month (default)
            bucket_expr = "TO_CHAR(po.date_order, 'YYYY-MM')"
            label_expr = "TO_CHAR(po.date_order, 'Mon YYYY')"

        # Build date range filter - always default to last 12 months when no specific filter
        date_clauses = []
        date_params = []
        if date_from:
            date_clauses.append("po.date_order >= %s")
            date_params.append(date_from)
        if date_to:
            date_clauses.append("po.date_order <= %s")
            date_params.append(date_to)
        if not date_from and not date_to:
            if year and year != 'all' and str(year).isdigit():
                date_clauses.append("EXTRACT(YEAR FROM po.date_order) = %s")
                date_params.append(int(year))
            else:
                # default: last 12 months to ensure always shows data
                date_clauses.append("po.date_order >= CURRENT_DATE - INTERVAL '12 months'")
        date_clause = " AND ".join(date_clauses) if date_clauses else "1=1"

        # Build product filter - product_ids, category_ids, or product name search
        extra_clauses = []
        extra_params = []

        if product_ids:
            extra_clauses.append("pol.product_id IN %s")
            extra_params.append(tuple(product_ids))
        if category_ids:
            expanded = self.env['product.category'].sudo().search([('id', 'child_of', category_ids)]).ids
            if expanded:
                extra_clauses.append("pt2.categ_id IN %s")
                extra_params.append(tuple(list(set(expanded))))
        if product_name and product_name.strip():
            name_pattern = f'%{product_name.strip().lower()}%'
            extra_clauses.append(
                "LOWER(COALESCE(pt2.name->>'en_IN', pt2.name->>'en_US', pt2.name::jsonb->>0, pt2.name::text)) LIKE %s"
            )
            extra_params.append(name_pattern)

        product_clause = " AND ".join(extra_clauses) if extra_clauses else "1=1"

        # Branch exclusion clause
        branch_clause = "1=1"
        branch_params = []
        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            all_branch_partners = list(set(company_partners + branch_partners))
            if all_branch_partners:
                branch_clause = "po.partner_id NOT IN %s"
                branch_params.append(tuple(all_branch_partners))

        cr.execute(f"""
            SELECT
                {bucket_expr} AS bucket,
                {label_expr} AS label,
                pt2.name AS product_name,
                ROUND(AVG(pol.price_unit)::numeric, 2) AS avg_price,
                ROUND(MIN(pol.price_unit)::numeric, 2) AS min_price,
                ROUND(MAX(pol.price_unit)::numeric, 2) AS max_price,
                COUNT(pol.id) AS order_count
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            JOIN product_product pp2 ON pp2.id = pol.product_id
            JOIN product_template pt2 ON pt2.id = pp2.product_tmpl_id
            WHERE po.company_id IN %s
              AND po.state IN ('purchase', 'done')
              AND {date_clause}
              AND {product_clause}
              AND {branch_clause}
              AND pol.price_unit > 0
            GROUP BY bucket, label, pt2.id
            ORDER BY bucket ASC
            LIMIT 500
        """, [company_ids_tup] + date_params + extra_params + branch_params)
        rows = cr.fetchall()

        products_seen = {}
        chart_points = []
        lang_key = self.env.lang.replace('_', '_') if self.env.lang else 'en_US'

        for r in rows:
            bucket, label, prod_name, avg_p, min_p, max_p, cnt = r
            if isinstance(prod_name, dict):
                prod_name_str = prod_name.get(lang_key) or prod_name.get('en_IN') or prod_name.get('en_US') or list(prod_name.values())[0]
            else:
                prod_name_str = str(prod_name)
            chart_points.append({
                'bucket': bucket,
                'label': label,
                'product': prod_name_str,
                'avg_price': float(avg_p or 0),
                'min_price': float(min_p or 0),
                'max_price': float(max_p or 0),
                'order_count': int(cnt or 0),
            })
            products_seen[prod_name_str] = products_seen.get(prod_name_str, 0) + int(cnt or 0)

        # Top 10 products by order count
        top_products = [p[0] for p in sorted(products_seen.items(), key=lambda x: -x[1])[:10]]

        # Build per-product series keyed by label
        series = {}
        all_labels_ordered = []
        all_buckets_ordered = []
        seen_labels = set()
        for pt in chart_points:
            if pt['product'] not in top_products:
                continue
            lbl = pt['label']
            bkt = pt['bucket']
            if lbl not in seen_labels:
                all_labels_ordered.append(lbl)
                all_buckets_ordered.append(bkt)
                seen_labels.add(lbl)
            series.setdefault(pt['product'], {})[lbl] = pt['avg_price']

        colors = [
            '#4f46e5', '#10b981', '#f59e0b', '#ef4444', '#3b82f6',
            '#8b5cf6', '#06b6d4', '#84cc16', '#f97316', '#ec4899'
        ]
        datasets = []
        for i, prod in enumerate(top_products):
            data_vals = [series.get(prod, {}).get(lbl, None) for lbl in all_labels_ordered]
            datasets.append({'label': prod, 'data': data_vals, 'color': colors[i % len(colors)]})

        if chart_points:
            overall_avg = round(sum(p['avg_price'] for p in chart_points) / len(chart_points), 2)
            overall_min = round(min(p['min_price'] for p in chart_points), 2)
            overall_max = round(max(p['max_price'] for p in chart_points), 2)
        else:
            overall_avg = overall_min = overall_max = 0.0

        return {
            'labels': all_labels_ordered,
            'buckets': all_buckets_ordered,
            'datasets': datasets,
            'kpis': {
                'avg_price': overall_avg,
                'min_price': overall_min,
                'max_price': overall_max,
                'products_tracked': len(top_products),
            }
        }

    @api.model
    def get_purchasable_products(self, company_id=None, search='', exclude_branches=False, company_ids=None):
        """Return products that have been purchased (have confirmed PO lines)."""
        if not company_id:
            company_id = self.env.company.id

        # Resolve branch companies
        if company_ids and len(company_ids) > 0:
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_list = list(set(resolved_ids))
        else:
            company_ids_list = [company_id]
            if not exclude_branches:
                child_companies = self.env['res.company'].sudo().search([('parent_id', '=', company_id)])
                company_ids_list.extend(child_companies.ids)
                company_ids_list = list(set(company_ids_list))
        company_ids_tup = tuple(company_ids_list)

        cr = self.env.cr

        branch_clause = "1=1"
        branch_params = []
        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            all_branch_partners = list(set(company_partners + branch_partners))
            if all_branch_partners:
                branch_clause = "po.partner_id NOT IN %s"
                branch_params.append(tuple(all_branch_partners))

        search_clause = "1=1"
        search_params = [company_ids_tup]
        if search and search.strip():
            search_clause = "LOWER(COALESCE(pt.name->>'en_IN', pt.name->>'en_US', pt.name::jsonb->>0, pt.name::text)) LIKE %s"
            pattern = f'%{search.strip().lower()}%'
            search_params.append(pattern)

        cr.execute(f"""
            SELECT DISTINCT pp.id AS product_id,
                   COALESCE(pt.name->>'en_IN', pt.name->>'en_US', (pt.name::jsonb->>0)) AS product_name
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            JOIN product_product pp ON pp.id = pol.product_id
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE po.company_id IN %s AND po.state IN ('purchase', 'done')
              AND {search_clause}
              AND {branch_clause}
            ORDER BY product_name
            LIMIT 200
        """, search_params + branch_params)
        return [{'id': r[0], 'name': r[1] or ''} for r in cr.fetchall()]

    @api.model
    def get_gate_entry_done_grn_pending_picking_ids(self, company_ids=None, year=None, month=None, date_from=None, date_to=None, exclude_partner_ids=None, exclude_branches=False):
        if not company_ids:
            company_ids = [self.env.company.id]
        
        # Resolve branches for children companies if not excluded
        company_ids_list = list(company_ids)
        if not exclude_branches:
            for cid in list(company_ids_list):
                children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                company_ids_list.extend(children.ids)
            company_ids_list = list(set(company_ids_list))
        company_ids = company_ids_list

        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            all_branch_partner_ids = list(set(company_partners + branch_partners))
            if not exclude_partner_ids:
                exclude_partner_ids = []
            exclude_partner_ids = list(set(exclude_partner_ids + all_branch_partner_ids))

        cr = self.env.cr
        date_clause, date_params = self._get_date_filter('po', 'date_order', year, month, date_from, date_to)
        exclude_po, exclude_po_params = self._get_exclude_partner_clause('po', exclude_partner_ids)

        cr.execute(f"""
            SELECT DISTINCT sp.id
            FROM stock_picking sp
            JOIN gate_entry_picking_rel rel ON rel.picking_id = sp.id
            JOIN gate_entry ge ON ge.id = rel.gate_entry_id
            JOIN stock_move sm ON sm.picking_id = sp.id
            JOIN purchase_order_line pol ON pol.id = sm.purchase_line_id
            JOIN purchase_order po ON po.id = pol.order_id
            WHERE sp.company_id IN %s
              AND sp.state != 'done'
              AND ge.state = 'confirm'
              AND NOT EXISTS (
                  SELECT 1 FROM stock_picking ret
                  WHERE ret.return_id = sp.id AND ret.state = 'done'
              )
              AND {date_clause} {exclude_po}
        """, [tuple(company_ids)] + date_params + exclude_po_params)
        return [row[0] for row in cr.fetchall()]

    @api.model
    def get_products_by_category(self, company_id=None, category_id=None, company_ids=None):
        if not category_id:
            return []
        categ_ids = self.env['product.category'].sudo().search([('id', 'child_of', int(category_id))]).ids
        # Find active products in these categories
        products = self.env['product.product'].sudo().search_read(
            [('categ_id', 'in', categ_ids), ('active', '=', True)],
            ['id', 'name', 'default_code']
        )
        # Format names to include default_code
        res = []
        for p in products:
            name = p['name']
            if isinstance(name, dict):
                lang_key = self.env.lang or 'en_US'
                name = name.get(lang_key) or name.get('en_US') or list(name.values())[0]
            code = p['default_code']
            display_name = f"[{code}] {name}" if code else name
            res.append({'id': p['id'], 'name': display_name})
        # Sort by name
        res.sort(key=lambda x: x['name'].lower())
        return res

    @api.model
    def get_vendor_price_comparison(self, category_id=None, product_ids=None, company_id=None, company_ids=None, exclude_branches=False, year=None, month=None, date_from=None, date_to=None, exclude_partner_ids=None):
        if not company_id:
            company_id = self.env.company.id
        if product_ids:
            product_ids = [int(x) for x in product_ids if x]
        
        # Resolve branch companies
        if company_ids and len(company_ids) > 0:
            resolved_ids = [int(c) for c in company_ids]
            if not exclude_branches:
                for cid in list(resolved_ids):
                    children = self.env['res.company'].sudo().search([('parent_id', '=', cid)])
                    resolved_ids.extend(children.ids)
            company_ids_list = list(set(resolved_ids))
        else:
            company_ids_list = [company_id]
            if not exclude_branches:
                child_companies = self.env['res.company'].sudo().search([('parent_id', '=', company_id)])
                company_ids_list.extend(child_companies.ids)
                company_ids_list = list(set(company_ids_list))
        company_ids_tup = tuple(company_ids_list)

        # Resolve products to compare
        product_ids_list = []
        if product_ids:
            product_ids_list = product_ids
        elif category_id:
            categ_ids = self.env['product.category'].sudo().search([('id', 'child_of', int(category_id))]).ids
            product_ids_list = self.env['product.product'].sudo().search([('categ_id', 'in', categ_ids), ('active', '=', True)]).ids
            # Limit products if not filtered to avoid memory limit issues
            product_ids_list = product_ids_list[:100]

        if not product_ids_list:
            return {'vendors': [], 'rows': []}

        cr = self.env.cr

        # Fetch product details
        lang = self.env.lang or 'en_US'
        cr.execute(f"""
            SELECT pp.id, COALESCE(pt.name->>{lang!r}, pt.name->>'en_US') AS name, pp.default_code
            FROM product_product pp
            JOIN product_template pt ON pt.id = pp.product_tmpl_id
            WHERE pp.id IN %s
        """, [tuple(product_ids_list)])
        products = {}
        for pid, name, code in cr.fetchall():
            display_name = f"[{code}] {name}" if code else name
            products[pid] = {
                'id': pid,
                'name': display_name,
                'code': code or ''
            }

        # Resolve branch/company partner IDs to optionally exclude
        if exclude_branches:
            company_partners = self.env['res.company'].sudo().search([]).mapped('partner_id').ids
            branch_partners = []
            if 'res.branch' in self.env:
                branch_partners = self.env['res.branch'].sudo().search([]).mapped('partner_id').ids
            all_branch_partner_ids = list(set(company_partners + branch_partners))
            if all_branch_partner_ids:
                if not exclude_partner_ids:
                    exclude_partner_ids = []
                exclude_partner_ids = list(set(exclude_partner_ids + all_branch_partner_ids))

        # Build exclude vendor clause
        exclude_clause = ""
        exclude_params = []
        if exclude_partner_ids:
            exclude_clause = "AND rp.id NOT IN %s"
            exclude_params.append(tuple(exclude_partner_ids))

        # Build date range filters for PO lines and Bill lines
        date_clauses = []
        date_params = []
        date_clauses_bill = []
        date_params_bill = []
        if date_from:
            date_clauses.append("po.date_order >= %s")
            date_params.append(date_from)
            date_clauses_bill.append("am.invoice_date >= %s")
            date_params_bill.append(date_from)
        if date_to:
            date_clauses.append("po.date_order <= %s")
            date_params.append(date_to)
            date_clauses_bill.append("am.invoice_date <= %s")
            date_params_bill.append(date_to)
        if not date_from and not date_to:
            if year and year != 'all' and str(year).isdigit():
                date_clauses.append("EXTRACT(YEAR FROM po.date_order) = %s")
                date_params.append(int(year))
                date_clauses_bill.append("EXTRACT(YEAR FROM am.invoice_date) = %s")
                date_params_bill.append(int(year))
                if month and month != 'all':
                    months_map = {
                        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                    }
                    month_num = months_map.get(month)
                    if month_num:
                        date_clauses.append("EXTRACT(MONTH FROM po.date_order) = %s")
                        date_params.append(month_num)
                        date_clauses_bill.append("EXTRACT(MONTH FROM am.invoice_date) = %s")
                        date_params_bill.append(month_num)
        date_clause = " AND ".join(date_clauses) if date_clauses else "1=1"
        date_clause_bill = " AND ".join(date_clauses_bill) if date_clauses_bill else "1=1"

        # Query account.move.line (Latest Billed Price)
        cr.execute(f"""
            SELECT DISTINCT ON (aml.product_id, am.partner_id)
                aml.product_id,
                am.partner_id,
                rp.name AS partner_name,
                aml.price_unit AS last_bill_price
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            JOIN res_partner rp ON rp.id = am.partner_id
            WHERE aml.product_id IN %s
              AND am.company_id IN %s
              AND am.move_type = 'in_invoice'
              AND am.state = 'posted'
              AND {date_clause_bill}
              {exclude_clause}
            ORDER BY aml.product_id, am.partner_id, am.invoice_date DESC, aml.id DESC
        """, [tuple(product_ids_list), company_ids_tup] + date_params_bill + exclude_params)
        bill_rows = cr.fetchall()

        # Query purchase.order.line (Purchase History)
        cr.execute(f"""
            SELECT DISTINCT ON (pol.product_id, po.partner_id)
                pol.product_id,
                po.partner_id,
                rp.name AS partner_name,
                pol.price_unit AS last_po_price
            FROM purchase_order_line pol
            JOIN purchase_order po ON po.id = pol.order_id
            JOIN res_partner rp ON rp.id = po.partner_id
            WHERE pol.product_id IN %s
              AND po.company_id IN %s
              AND po.state IN ('purchase', 'done')
              AND {date_clause}
              {exclude_clause}
            ORDER BY pol.product_id, po.partner_id, po.date_order DESC
        """, [tuple(product_ids_list), company_ids_tup] + date_params + exclude_params)
        po_rows = cr.fetchall()

        # Merge prices
        # matrix[product_id][partner_id] = {last_bill, last_po}
        matrix = {}
        vendors = {}

        for pid, partner_id, partner_name, price in bill_rows:
            if pid not in matrix:
                matrix[pid] = {}
            if partner_id not in matrix[pid]:
                matrix[pid][partner_id] = {'last_bill': None, 'last_po': None}
            matrix[pid][partner_id]['last_bill'] = float(price or 0.0)
            vendors[partner_id] = partner_name

        for pid, partner_id, partner_name, price in po_rows:
            if pid not in matrix:
                matrix[pid] = {}
            if partner_id not in matrix[pid]:
                matrix[pid][partner_id] = {'last_bill': None, 'last_po': None}
            matrix[pid][partner_id]['last_po'] = float(price or 0.0)
            vendors[partner_id] = partner_name

        # Format sorted list of vendors
        sorted_vendor_ids = sorted(vendors.keys(), key=lambda x: vendors[x].lower())
        vendors_list = [{'id': vid, 'name': vendors[vid]} for vid in sorted_vendor_ids]

        # Format rows for QWeb
        rows = []
        for pid in sorted(products.keys(), key=lambda x: products[x]['name'].lower()):
            p_data = products[pid]
            row_cells = []
            min_price = None

            for vid in sorted_vendor_ids:
                cell = matrix.get(pid, {}).get(vid, None)
                effective_price = None
                if cell:
                    effective_price = cell['last_bill'] if cell['last_bill'] is not None else cell['last_po']
                
                if effective_price is not None:
                    if min_price is None or effective_price < min_price:
                        min_price = effective_price

                row_cells.append({
                    'vendor_id': vid,
                    'last_bill': cell['last_bill'] if cell else None,
                    'last_po': cell['last_po'] if cell else None,
                    'effective_price': effective_price,
                })

            rows.append({
                'product': p_data,
                'cells': row_cells,
                'min_price': min_price
            })

        return {
            'vendors': vendors_list,
            'rows': rows
        }


class PurchaseSavingsReport(models.Model):
    _name = 'purchase.savings.report'
    _description = 'Procurement Cost Savings Report'
    _auto = False
    _order = 'invoice_date desc'

    move_id = fields.Many2one('purchase.order', string='Latest PO', readonly=True)
    latest_bill_id = fields.Many2one('account.move', string='Latest Bill', readonly=True)
    latest_bill_ref = fields.Char(string='Latest Bill No', readonly=True)
    invoice_date = fields.Date(string='Order Date', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', readonly=True)
    quantity = fields.Float(string='Quantity', readonly=True)
    current_price = fields.Float(string='PO Unit Price', readonly=True)
    baseline_price = fields.Float(string='Previous PO Unit Price', readonly=True)
    prev_po_id = fields.Many2one('purchase.order', string='Previous PO', readonly=True)
    prev_bill_id = fields.Many2one('account.move', string='Previous Bill', readonly=True)
    prev_bill_ref = fields.Char(string='Previous Bill No', readonly=True)
    saving_amount = fields.Float(string='Savings', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)

    def get_formview_action(self, access_uid=None):
        self.ensure_one()
        if self.move_id:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'res_id': self.move_id.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return super().get_formview_action(access_uid=access_uid)

    def init(self):
        companies = self.env['res.company'].search([])
        branch_partner_ids = companies.mapped('partner_id').ids
        branch_partners_tup = tuple(branch_partner_ids) if branch_partner_ids else (0,)

        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    inner_data.id,
                    inner_data.move_id,
                    inner_data.latest_bill_id,
                    inner_data.latest_bill_ref,
                    inner_data.invoice_date,
                    inner_data.product_id,
                    inner_data.partner_id,
                    inner_data.quantity,
                    inner_data.current_price,
                    inner_data.company_id,
                    -- Only show prev data when the previous PO has a bill in the same month
                    CASE WHEN inner_data.prev_bill_id IS NOT NULL
                         THEN inner_data.prev_po_id ELSE NULL END AS prev_po_id,
                    inner_data.prev_bill_id,
                    inner_data.prev_bill_ref,
                    CASE WHEN inner_data.prev_bill_id IS NOT NULL
                         THEN inner_data.baseline_price ELSE NULL END AS baseline_price,
                    CASE WHEN inner_data.prev_bill_id IS NOT NULL
                         THEN (inner_data.baseline_price - inner_data.current_price) * inner_data.quantity
                         ELSE 0 END AS saving_amount
                FROM (
                    SELECT
                        pol.id AS id,
                        po.id AS move_id,
                        (
                            SELECT am.id
                            FROM account_move_line aml
                            JOIN account_move am ON am.id = aml.move_id
                            WHERE aml.purchase_line_id = pol.id
                              AND am.move_type = 'in_invoice'
                              AND am.state = 'posted'
                            ORDER BY am.invoice_date DESC, aml.id DESC
                            LIMIT 1
                        ) AS latest_bill_id,
                        (
                            SELECT am.ref
                            FROM account_move_line aml
                            JOIN account_move am ON am.id = aml.move_id
                            WHERE aml.purchase_line_id = pol.id
                              AND am.move_type = 'in_invoice'
                              AND am.state = 'posted'
                            ORDER BY am.invoice_date DESC, aml.id DESC
                            LIMIT 1
                        ) AS latest_bill_ref,
                        COALESCE(
                            (
                                SELECT am.invoice_date
                                FROM account_move_line aml
                                JOIN account_move am ON am.id = aml.move_id
                                WHERE aml.purchase_line_id = pol.id
                                  AND am.move_type = 'in_invoice'
                                  AND am.state = 'posted'
                                ORDER BY am.invoice_date DESC, aml.id DESC
                                LIMIT 1
                            ),
                            po.date_order::date
                        ) AS invoice_date,
                        pol.product_id AS product_id,
                        po.partner_id AS partner_id,
                        pol.product_qty AS quantity,
                        pol.price_unit AS current_price,
                        po.company_id AS company_id,
                        COALESCE(prev.prev_price, pol.price_unit) AS baseline_price,
                        prev.prev_po_id AS prev_po_id,
                        (
                            SELECT am.id
                            FROM account_move_line aml
                            JOIN account_move am ON am.id = aml.move_id
                            WHERE aml.purchase_line_id = prev.prev_line_id
                              AND am.move_type = 'in_invoice'
                              AND am.state = 'posted'
                              AND EXTRACT(YEAR FROM am.invoice_date) = EXTRACT(YEAR FROM COALESCE(
                                  (
                                      SELECT am2.invoice_date
                                      FROM account_move_line aml2
                                      JOIN account_move am2 ON am2.id = aml2.move_id
                                      WHERE aml2.purchase_line_id = pol.id
                                        AND am2.move_type = 'in_invoice'
                                        AND am2.state = 'posted'
                                      ORDER BY am2.invoice_date DESC, aml2.id DESC
                                      LIMIT 1
                                  ),
                                  po.date_order::date
                              ))
                              AND EXTRACT(MONTH FROM am.invoice_date) = EXTRACT(MONTH FROM COALESCE(
                                  (
                                      SELECT am2.invoice_date
                                      FROM account_move_line aml2
                                      JOIN account_move am2 ON am2.id = aml2.move_id
                                      WHERE aml2.purchase_line_id = pol.id
                                        AND am2.move_type = 'in_invoice'
                                        AND am2.state = 'posted'
                                      ORDER BY am2.invoice_date DESC, aml2.id DESC
                                      LIMIT 1
                                  ),
                                  po.date_order::date
                              ))
                            ORDER BY am.invoice_date DESC, aml.id DESC
                            LIMIT 1
                        ) AS prev_bill_id,
                        (
                            SELECT am.ref
                            FROM account_move_line aml
                            JOIN account_move am ON am.id = aml.move_id
                            WHERE aml.purchase_line_id = prev.prev_line_id
                              AND am.move_type = 'in_invoice'
                              AND am.state = 'posted'
                              AND EXTRACT(YEAR FROM am.invoice_date) = EXTRACT(YEAR FROM COALESCE(
                                  (
                                      SELECT am2.invoice_date
                                      FROM account_move_line aml2
                                      JOIN account_move am2 ON am2.id = aml2.move_id
                                      WHERE aml2.purchase_line_id = pol.id
                                        AND am2.move_type = 'in_invoice'
                                        AND am2.state = 'posted'
                                      ORDER BY am2.invoice_date DESC, aml2.id DESC
                                      LIMIT 1
                                  ),
                                  po.date_order::date
                              ))
                              AND EXTRACT(MONTH FROM am.invoice_date) = EXTRACT(MONTH FROM COALESCE(
                                  (
                                      SELECT am2.invoice_date
                                      FROM account_move_line aml2
                                      JOIN account_move am2 ON am2.id = aml2.move_id
                                      WHERE aml2.purchase_line_id = pol.id
                                        AND am2.move_type = 'in_invoice'
                                        AND am2.state = 'posted'
                                      ORDER BY am2.invoice_date DESC, aml2.id DESC
                                      LIMIT 1
                                  ),
                                  po.date_order::date
                              ))
                            ORDER BY am.invoice_date DESC, aml.id DESC
                            LIMIT 1
                        ) AS prev_bill_ref
                    FROM purchase_order_line pol
                    JOIN purchase_order po ON po.id = pol.order_id
                    LEFT JOIN LATERAL (
                        SELECT pol_prev.id AS prev_line_id,
                               pol_prev.price_unit AS prev_price,
                               po_prev.id AS prev_po_id
                        FROM purchase_order_line pol_prev
                        JOIN purchase_order po_prev ON po_prev.id = pol_prev.order_id
                        WHERE po_prev.state IN ('purchase', 'done')
                          AND pol_prev.product_id = pol.product_id
                          AND po_prev.company_id = po.company_id
                          AND (
                              po.partner_id IN {branch_partners_tup}
                              OR po_prev.partner_id NOT IN {branch_partners_tup}
                          )
                          AND (po_prev.date_order < po.date_order OR (po_prev.date_order = po.date_order AND pol_prev.id < pol.id))
                        ORDER BY po_prev.date_order DESC, pol_prev.id DESC
                        LIMIT 1
                    ) prev ON TRUE
                    WHERE po.state IN ('purchase', 'done')
                      AND pol.product_id IS NOT NULL
                ) inner_data
            )
        """)




