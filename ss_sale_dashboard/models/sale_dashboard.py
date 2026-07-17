# -*- coding: utf-8 -*-
import calendar
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)

MONTHS_MAP = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
    'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
}
MONTHS_ORDER = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


class SaleDashboard(models.AbstractModel):
    _name = 'sale.dashboard'
    _description = 'Sales and Collection Dashboard'

    # ------------------------------------------------------------------
    # Helper: date-filter clause builder
    # ------------------------------------------------------------------
    def _get_date_filter(self, table_prefix, date_field,
                         year=None, month=None, date_from=None, date_to=None):
        clauses = []
        params = []
        field_name = f"{table_prefix}.{date_field}" if table_prefix else date_field

        if date_from:
            clauses.append(f"{field_name} >= %s")
            params.append(date_from)
        if date_to:
            clauses.append(f"{field_name} <= %s")
            params.append(date_to)

        if not date_from and not date_to:
            if year and year != 'all':
                clauses.append(f"EXTRACT(YEAR FROM {field_name}) = %s")
                params.append(int(year))
            if month and month != 'all':
                if month in MONTHS_MAP:
                    clauses.append(f"EXTRACT(MONTH FROM {field_name}) = %s")
                    params.append(MONTHS_MAP[month])
                elif str(month).isdigit():
                    clauses.append(f"EXTRACT(MONTH FROM {field_name}) = %s")
                    params.append(int(month))

        return (" AND ".join(clauses) if clauses else "1=1"), params

    # ------------------------------------------------------------------
    # Helper: resolve company + branch partner IDs (shared logic)
    # ------------------------------------------------------------------
    def _resolve_companies(self, company_id=None, company_ids=None):
        """Return (company_ids_tup, main_company_ids, all_branch_partner_ids)."""
        cr = self.env.cr

        if not company_id:
            company_id = self.env.company.id

        if company_ids:
            resolved_ids = [int(c) for c in company_ids]
        else:
            resolved_ids = [company_id]

        main_company_ids = [cid for cid in resolved_ids if cid in self.env.companies.ids]
        if not main_company_ids:
            main_company_ids = [self.env.company.id]

        # Include direct child companies (one level)
        if resolved_ids:
            cr.execute(
                "SELECT id FROM res_company WHERE parent_id IN %s",
                (tuple(resolved_ids),)
            )
            resolved_ids = list(set(resolved_ids + [r[0] for r in cr.fetchall()]))

        # Filter to allowed active companies
        allowed = self.env.companies.ids
        resolved_ids = [cid for cid in resolved_ids if cid in allowed]
        if not resolved_ids:
            resolved_ids = [self.env.company.id]

        company_ids_tup = tuple(resolved_ids)

        # Company + branch partner IDs (single query using UNION ALL)
        if 'res.branch' in self.env:
            cr.execute("""
                SELECT partner_id FROM res_company  WHERE partner_id IS NOT NULL
                UNION ALL
                SELECT partner_id FROM res_branch   WHERE partner_id IS NOT NULL
            """)
        else:
            cr.execute("SELECT partner_id FROM res_company WHERE partner_id IS NOT NULL")
        all_branch_partner_ids = list({r[0] for r in cr.fetchall()})

        return company_ids_tup, main_company_ids, all_branch_partner_ids

    # ------------------------------------------------------------------
    # Helper: resolve product category IDs via raw SQL (avoids ORM query)
    # ------------------------------------------------------------------
    def _resolve_category_ids(self, categ_ids=None, categ_id=None):
        """Return flat list of matching category IDs (including children)."""
        c_ids = []
        if categ_ids:
            c_ids = [int(c) for c in categ_ids if str(c).isdigit() or isinstance(c, int)]
        elif categ_id and str(categ_id).isdigit():
            c_ids = [int(categ_id)]

        if not c_ids:
            return []

        self.env.cr.execute("""
            WITH RECURSIVE cat_tree AS (
                SELECT id FROM product_category WHERE id IN %s
                UNION ALL
                SELECT pc.id
                FROM   product_category pc
                JOIN   cat_tree ct ON pc.parent_id = ct.id
            )
            SELECT DISTINCT id FROM cat_tree
        """, (tuple(c_ids),))
        return [r[0] for r in self.env.cr.fetchall()]

    # ------------------------------------------------------------------
    # Static data (customers + categories) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â called once, not per filter
    # ------------------------------------------------------------------
    @api.model
    def get_static_data(self, exclude_branches=False, company_id=None, company_ids=None):
        """Return customers and product categories for dropdown population.
        This is separated from get_dashboard_data so it is only fetched once
        per dashboard session, not on every filter change."""
        cr = self.env.cr

        _, _, all_branch_partner_ids = self._resolve_companies(company_id, company_ids)

        # Customer list ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â raw SQL bypasses ORM overhead for 15,000 records
        if all_branch_partner_ids:
            cr.execute("""
                SELECT id, name, ref
                FROM res_partner
                WHERE active = true
                  AND parent_id IS NULL
                  AND id NOT IN %s
                ORDER BY name ASC
                LIMIT 15000
            """, (tuple(all_branch_partner_ids),))
        else:
            cr.execute("""
                SELECT id, name, ref
                FROM res_partner
                WHERE active = true
                  AND parent_id IS NULL
                ORDER BY name ASC
                LIMIT 15000
            """)
        customers = cr.dictfetchall()

        # Category list - all categories
        all_categories = self.env['product.category'].search([])
        categories = [{
            'id': c.id,
            'name': c.name,
            'complete_name': c.complete_name
        } for c in all_categories]
        categories = sorted(categories, key=lambda x: x['name'] or '')

        return {
            'customers': customers,
            'categories': categories,
            'branch_partner_ids': all_branch_partner_ids,
        }

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, company_id=None, company_ids=None,
                           year=None, month=None,
                           date_from=None, date_to=None,
                           exclude_branches=False, partner_id=None, partner_ids=None,
                           tds_filter='without_tds', categ_id=None, categ_ids=None):
        """Fetch aggregated sales and collections dashboard statistics."""
        cr = self.env.cr

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 1. Resolve companies ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        company_ids_tup, main_company_ids, all_branch_partner_ids = \
            self._resolve_companies(company_id, company_ids)
        active_company_ids = list(company_ids_tup)

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 2. Resolve product category IDs ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        category_ids = self._resolve_category_ids(categ_ids, categ_id)

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 3. Branch exclusion & partner filter ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        exclude_partner_ids = all_branch_partner_ids if (exclude_branches and all_branch_partner_ids) else []

        p_ids = []
        if partner_ids:
            p_ids = [int(p) for p in partner_ids if str(p).isdigit() or isinstance(p, int)]
        elif partner_id and str(partner_id).isdigit():
            p_ids = [int(partner_id)]

        def _exclude_clause(alias):
            if exclude_partner_ids:
                return f"AND {alias}.partner_id NOT IN %s", (tuple(exclude_partner_ids),)
            return "", ()

        def _partner_clause(alias):
            if p_ids:
                return f"AND {alias}.partner_id IN %s", (tuple(p_ids),)
            return "", ()

        am_exclude, am_exclude_params = _exclude_clause('am')
        am_part,    am_part_params    = _partner_clause('am')

        today = fields.Date.today()

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 4. Date filter clauses ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        am_date_clause, am_date_params = self._get_date_filter(
            'am', 'invoice_date', year, month, date_from, date_to
        )

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 5. Category subquery ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        if category_ids:
            cat_subquery = (
                "AND EXISTS (SELECT 1 FROM account_move_line aml_c "
                "JOIN product_product pp_c ON aml_c.product_id = pp_c.id "
                "JOIN product_template pt_c ON pp_c.product_tmpl_id = pt_c.id "
                "WHERE aml_c.move_id = am.id AND pt_c.categ_id IN %s)"
            )
            cat_params = (tuple(category_ids),)
        else:
            cat_subquery = ""
            cat_params = ()

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 6. CONSOLIDATED KPI query (sales + outstanding + overdue) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        # Three aggregates in one pass over account_move.
        # IMPORTANT: base_cond uses %s for company_id (WHERE clause).
        # The overdue CASE uses %s for today (SELECT clause).
        # PostgreSQL binds %s left-to-right across the entire SQL string,
        # so SELECT-clause params come before WHERE-clause params.
        # We therefore put today FIRST, then company_ids_tup.
        base_cond = f"""
            am.move_type = 'out_invoice'
            AND am.state   = 'posted'
            AND am.company_id IN %s
        """
        kpi_params_base = (company_ids_tup,)

        kpi_query = f"""
            SELECT
                COALESCE(SUM(am.amount_total), 0)                                          AS sales,
                COALESCE(SUM(CASE WHEN am.payment_state IN ('not_paid','partial')
                                  THEN am.amount_residual ELSE 0 END), 0)                  AS outstanding,
                COALESCE(SUM(CASE WHEN am.payment_state IN ('not_paid','partial')
                                       AND am.invoice_date_due < %s
                                  THEN am.amount_residual ELSE 0 END), 0)                  AS overdue_outstanding
            FROM account_move am
            WHERE {base_cond}
              AND {am_date_clause}
              {am_exclude}
              {am_part}
              {cat_subquery}
        """
        # Param order matches SQL left-to-right:
        # 1. today  ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ SELECT CASE: invoice_date_due < %s
        # 2. company_ids_tup ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ WHERE base_cond: company_id IN %s
        # 3. am_date_params  ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ WHERE am_date_clause
        # 4. am_exclude_params, am_part_params, cat_params
        cr.execute(
            kpi_query,
            (today,) + kpi_params_base + tuple(am_date_params) + am_exclude_params + am_part_params + cat_params
        )
        kpi_row = cr.fetchone()
        sales               = kpi_row[0]
        outstanding         = kpi_row[1]
        overdue_outstanding = kpi_row[2]

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 7. Collection (reconciled payment portion) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        collection_clauses = ["inv.move_type = 'out_invoice'", "inv.state = 'posted'", "inv.company_id IN %s"]
        collection_params  = [company_ids_tup]

        col_date_clause, col_date_params = self._get_date_filter(
            'cred', 'date', year, month, date_from, date_to
        )
        collection_clauses.append(col_date_clause)
        collection_params.extend(col_date_params)

        if exclude_partner_ids:
            collection_clauses.append("inv.partner_id NOT IN %s")
            collection_params.append(tuple(exclude_partner_ids))

        if p_ids:
            collection_clauses.append("inv.partner_id IN %s")
            collection_params.append(tuple(p_ids))

        if category_ids:
            collection_clauses.append(
                "EXISTS (SELECT 1 FROM account_move_line aml_c "
                "JOIN product_product pp_c ON aml_c.product_id = pp_c.id "
                "JOIN product_template pt_c ON pp_c.product_tmpl_id = pt_c.id "
                "WHERE aml_c.move_id = inv.id AND pt_c.categ_id IN %s)"
            )
            collection_params.append(tuple(category_ids))

        if tds_filter == 'with_tds':
            collection_clauses.append(
                "(aj.type IN ('bank', 'cash') OR (aj.type = 'general' AND "
                "(aj.name->>'en_US' ILIKE %s OR aj.code ILIKE %s OR "
                " aj.name->>'en_US' ILIKE %s OR aj.code ILIKE %s)))"
            )
            collection_params.extend(['%tds%', '%tds%', '%tcs%', '%tcs%'])
        else:
            collection_clauses.append("aj.type IN ('bank', 'cash')")

        collection_query = f"""
            SELECT COALESCE(SUM(c.credit), 0)
            FROM (
                SELECT DISTINCT cred.id, cred.credit
                FROM account_partial_reconcile apr
                JOIN account_move_line deb ON apr.debit_move_id  = deb.id
                JOIN account_move      inv ON deb.move_id        = inv.id
                JOIN account_move_line cred ON apr.credit_move_id = cred.id
                JOIN account_journal   aj   ON cred.journal_id   = aj.id
                WHERE {" AND ".join(collection_clauses)}
            ) c
        """
        cr.execute(collection_query, tuple(collection_params))
        collection = cr.fetchone()[0]

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 8. CONSOLIDATED Bank KPI query ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        br_date_clause, br_date_params = self._get_date_filter(
            'am', 'date', year, month, date_from, date_to
        )
        bank_query = f"""
            SELECT
                COALESCE(SUM(aml.debit), 0)                                             AS bank_received,
                COALESCE(SUM(CASE WHEN aml.partner_id IS NOT NULL
                                  THEN aml.debit ELSE 0 END), 0)                        AS bank_partner_received,
                COALESCE(SUM(CASE WHEN st.id IS NULL OR st.is_reconciled = true
                                  THEN aml.debit ELSE 0 END), 0)                        AS bank_reconciled
            FROM account_move_line aml
            JOIN account_move am ON aml.move_id = am.id
            JOIN account_journal aj ON aml.journal_id = aj.id
            LEFT JOIN account_bank_statement_line st ON st.move_id = am.id
            WHERE aj.type = 'bank'
              AND aml.account_id = aj.default_account_id
              AND aml.debit > 0
              AND am.state = 'posted'
              AND am.company_id IN %s
              AND {br_date_clause}
        """
        cr.execute(bank_query, (company_ids_tup,) + tuple(br_date_params))
        brow = cr.fetchone()
        bank_received        = brow[0]
        bank_partner_received = brow[1]
        bank_reconciled      = brow[2]

        # Suspense (separate ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã…â€œ different table)
        br_suspense_query = f"""
            SELECT COALESCE(SUM(st.amount), 0)
            FROM account_bank_statement_line st
            JOIN account_move am ON st.move_id = am.id
            JOIN account_journal aj ON st.journal_id = aj.id
            WHERE aj.type = 'bank'
              AND am.state = 'posted'
              AND am.company_id IN %s
              AND st.amount > 0
              AND st.is_reconciled = false
              AND {br_date_clause}
        """
        cr.execute(br_suspense_query, (company_ids_tup,) + tuple(br_date_params))
        bank_suspense = cr.fetchone()[0]

        bank_reconciled_pct = (float(bank_reconciled) / float(bank_received) * 100.0) if bank_received else 0.0

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 9. Targets ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        target_company_tup = tuple(main_company_ids) if exclude_branches else company_ids_tup
        target_clauses = ["company_id IN %s"]
        target_params  = [target_company_tup]

        if year and year != 'all':
            target_clauses.append("year = %s")
            target_params.append(str(year))
        if month and month != 'all':
            target_clauses.append("month = %s")
            target_params.append(str(month))

        cr.execute(
            f"SELECT COALESCE(SUM(target_amount), 0) FROM sale_target WHERE {' AND '.join(target_clauses)}",
            target_params
        )
        total_target    = cr.fetchone()[0]
        achievement_pct = (float(sales) / float(total_target) * 100.0) if total_target else 0.0

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 10. Region-wise Sales ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        cr.execute(
            f"""SELECT COALESCE(rcs.name, 'Unknown') AS region,
                       COALESCE(SUM(am.amount_total), 0) AS amount
               FROM account_move am
               JOIN res_partner rp ON am.partner_id = rp.id
               LEFT JOIN res_partner cp  ON rp.commercial_partner_id = cp.id
               LEFT JOIN res_country_state rcs
                      ON COALESCE(rp.state_id, cp.state_id) = rcs.id
               WHERE {base_cond} AND {am_date_clause} {am_exclude} {am_part} {cat_subquery}
               GROUP BY rcs.name
               ORDER BY amount DESC""",
            kpi_params_base + tuple(am_date_params) + am_exclude_params + am_part_params + cat_params
        )
        region_sales = [{'region': r[0], 'amount': r[1]} for r in cr.fetchall()]

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 11. Product-wise + Segment + Category queries (line-level) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        prod_cat_clause = "AND pt.categ_id IN %s" if category_ids else ""
        prod_cat_params = (tuple(category_ids),) if category_ids else ()

        line_base = f"""
            FROM account_move_line aml
            JOIN account_move     am ON aml.move_id = am.id
            JOIN product_product  pp ON aml.product_id = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            WHERE {base_cond} AND aml.display_type = 'product'
                  AND {am_date_clause} {am_exclude} {am_part} {prod_cat_clause}
        """
        line_params = kpi_params_base + tuple(am_date_params) + am_exclude_params + am_part_params + prod_cat_params

        # Product-wise (Top 10)
        cr.execute(
            f"""SELECT pp.id,
                       COALESCE(pt.name->>'en_US', pt.name::text, 'Unknown'),
                       COALESCE(SUM(aml.quantity), 0),
                       COALESCE(SUM(aml.price_subtotal), 0)
                {line_base}
                GROUP BY pp.id, pt.id
                ORDER BY 4 DESC
                LIMIT 10""",
            line_params
        )
        product_sales = [
            {'product_id': r[0], 'product': r[1], 'qty': r[2], 'amount': r[3]}
            for r in cr.fetchall()
        ]

        # Segment-wise (partner segment)
        cr.execute(
            f"""SELECT COALESCE(ps.name, 'No Segment') AS segment,
                       COALESCE(SUM(aml.price_subtotal), 0) AS amount
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                JOIN res_partner rp ON am.partner_id = rp.id
                LEFT JOIN partner_segment_res_partner_rel rel ON rp.id = rel.res_partner_id
                LEFT JOIN partner_segment ps ON rel.partner_segment_id = ps.id
                JOIN product_product pp ON aml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                WHERE {base_cond} AND aml.display_type = 'product'
                  AND {am_date_clause} {am_exclude} {am_part} {prod_cat_clause}
                GROUP BY ps.name
                ORDER BY amount DESC""",
            line_params
        )
        segment_sales = [{'segment': r[0], 'amount': float(r[1])} for r in cr.fetchall()]

        # Product segment (category-name bucketing)
        cr.execute(
            f"""SELECT CASE
                    WHEN pc.name ILIKE '%%PLATE%%'   THEN 'PLATE'
                    WHEN pc.name ILIKE '%%TW%%' OR pc.name ILIKE '%%VRLA%%' THEN '2W+VRLA'
                    WHEN pc.name ILIKE '%%IB%%'      THEN 'IB'
                    WHEN pc.name ILIKE '%%HUPS%%'    THEN 'HUPS'
                    WHEN pc.name ILIKE '%%SPGS%%'    THEN 'PANEL'
                    WHEN pc.name ILIKE '%%LITHIUM%%' OR pc.name ILIKE '%%LI-ION%%'
                      OR pc.name ILIKE '%%LI_ION%%'  OR pc.name ILIKE '%%Lithium%%' THEN 'LITHIUM'
                    WHEN pc.name ILIKE '%%AM%%'      THEN 'AM'
                    WHEN pc.name ILIKE '%%ER%%'      THEN 'ER'
                    ELSE 'Other'
                END AS prod_segment,
                COALESCE(SUM(aml.price_subtotal), 0) AS amount
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                JOIN product_product pp ON aml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                JOIN product_category pc ON pt.categ_id = pc.id
                WHERE {base_cond} AND aml.display_type = 'product'
                  AND {am_date_clause} {am_exclude} {am_part} {prod_cat_clause}
                GROUP BY 1
                ORDER BY amount DESC""",
            line_params
        )
        product_segment_sales = [{'segment': r[0], 'amount': float(r[1])} for r in cr.fetchall()]

        # Category-wise (Top 10)
        cr.execute(
            f"""SELECT COALESCE(pc.name, 'No Category') AS category,
                       COALESCE(SUM(aml.price_subtotal), 0) AS amount
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                JOIN product_product pp ON aml.product_id = pp.id
                JOIN product_template pt ON pp.product_tmpl_id = pt.id
                JOIN product_category pc ON pt.categ_id = pc.id
                WHERE {base_cond} AND aml.display_type = 'product'
                  AND {am_date_clause} {am_exclude} {am_part} {prod_cat_clause}
                GROUP BY pc.name
                ORDER BY amount DESC
                LIMIT 10""",
            line_params
        )
        category_sales = [{'category': r[0], 'amount': float(r[1])} for r in cr.fetchall()]

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 12. Sales Trend ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        if month == 'all':
            trend_clause, trend_params = self._get_date_filter(
                'am', 'invoice_date', year, 'all', date_from, date_to
            )
            cr.execute(
                f"""SELECT TO_CHAR(am.invoice_date, 'Mon'),
                           EXTRACT(MONTH FROM am.invoice_date),
                           COALESCE(SUM(am.amount_total), 0)
                    FROM account_move am
                    WHERE {base_cond} AND {trend_clause} {am_exclude} {am_part} {cat_subquery}
                    GROUP BY 1, 2
                    ORDER BY 2""",
                kpi_params_base + tuple(trend_params) + am_exclude_params + am_part_params + cat_params
            )
            data_map = {m: 0.0 for m in MONTHS_ORDER}
            for label, _, amount in cr.fetchall():
                if label in data_map:
                    data_map[label] = float(amount)
            trend_sales = [{'month': m, 'amount': data_map[m]} for m in MONTHS_ORDER]
        else:
            trend_clause, trend_params = self._get_date_filter(
                'am', 'invoice_date', year, month, date_from, date_to
            )
            cr.execute(
                f"""SELECT EXTRACT(DAY FROM am.invoice_date)::integer,
                           COALESCE(SUM(am.amount_total), 0)
                    FROM account_move am
                    WHERE {base_cond} AND {trend_clause} {am_exclude} {am_part} {cat_subquery}
                    GROUP BY 1
                    ORDER BY 1""",
                kpi_params_base + tuple(trend_params) + am_exclude_params + am_part_params + cat_params
            )
            m_num  = MONTHS_MAP.get(month, 1) if month in MONTHS_MAP else 1
            y_num  = int(year) if (year and str(year).isdigit()) else today.year
            _, num_days = calendar.monthrange(y_num, m_num)
            data_map = {d: 0.0 for d in range(1, num_days + 1)}
            for day, amount in cr.fetchall():
                if day in data_map:
                    data_map[day] = float(amount)
            trend_sales = [{'month': str(d), 'amount': data_map[d]} for d in range(1, num_days + 1)]

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 13. Overdue Invoice List (Top 15) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        cr.execute(
            f"""SELECT rp.id, rp.name,
                       COUNT(am.id),
                       COALESCE(SUM(am.amount_total), 0),
                       COALESCE(SUM(am.amount_residual), 0)
                FROM account_move am
                JOIN res_partner rp ON am.partner_id = rp.id
                WHERE {base_cond} AND am.payment_state IN ('not_paid','partial')
                      AND am.invoice_date_due < %s
                      AND {am_date_clause} {am_exclude} {am_part} {cat_subquery}
                GROUP BY rp.id, rp.name
                ORDER BY 5 DESC
                LIMIT 15""",
            kpi_params_base + (today,) + tuple(am_date_params) + am_exclude_params + am_part_params + cat_params
        )
        overdue_list = [
            {'partner_id': r[0], 'customer': r[1], 'invoice_count': r[2],
             'amount_total': r[3], 'amount_residual': r[4]}
            for r in cr.fetchall()
        ]

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 14. COMBINED Aged Receivables (detail + summary in one pass) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        aged_base_cond = f"""
            am.move_type = 'out_invoice'
            AND am.state = 'posted'
            AND am.payment_state IN ('not_paid','partial')
            AND am.company_id IN %s
            {am_exclude}
            {am_part}
        """
        aged_params_base = (company_ids_tup,) + am_exclude_params + am_part_params

        bucket_cases = """
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) >= %s
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s
                               AND  COALESCE(am.invoice_date_due, am.invoice_date) >= %s - INTERVAL '30 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s - INTERVAL '30 days'
                               AND  COALESCE(am.invoice_date_due, am.invoice_date) >= %s - INTERVAL '60 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s - INTERVAL '60 days'
                               AND  COALESCE(am.invoice_date_due, am.invoice_date) >= %s - INTERVAL '90 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s - INTERVAL '90 days'
                               AND  COALESCE(am.invoice_date_due, am.invoice_date) >= %s - INTERVAL '120 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s - INTERVAL '120 days'
                               AND  COALESCE(am.invoice_date_due, am.invoice_date) >= %s - INTERVAL '150 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s - INTERVAL '150 days'
                               AND  COALESCE(am.invoice_date_due, am.invoice_date) >= %s - INTERVAL '180 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN COALESCE(am.invoice_date_due, am.invoice_date) <  %s - INTERVAL '180 days'
                               THEN am.amount_residual ELSE 0 END), 0),
            COALESCE(SUM(am.amount_residual), 0)
        """
        today_params = (today,) * 14

        # Detail rows (top 100 by outstanding) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â bucket_cases %s binds to today_params,
        # aged_params_base binds to WHERE aged_base_cond placeholders.
        aged_detail_query = f"""
            SELECT
                rp.id, rp.name, rp.ref,
                MAX(am.date), MAX(am.invoice_date),
                {bucket_cases}
            FROM account_move am
            JOIN res_partner rp ON am.partner_id = rp.id
            WHERE {aged_base_cond}
            GROUP BY rp.id
            HAVING SUM(am.amount_residual) > 0
            ORDER BY SUM(am.amount_residual) DESC
            LIMIT 100
        """
        cr.execute(aged_detail_query, today_params + aged_params_base)
        aged_rows = cr.fetchall()

        # Summary totals using conditional aggregation WITHOUT a GROUP BY
        # (single scan, no second join)
        aged_summary_query = f"""
            SELECT {bucket_cases}
            FROM account_move am
            WHERE {aged_base_cond}
        """
        cr.execute(aged_summary_query, today_params + aged_params_base)
        s = cr.fetchone()
        ar_total_summary = {
            'not_due':        float(s[0]),
            'bucket_1_30':    float(s[1]),
            'bucket_31_60':   float(s[2]),
            'bucket_61_90':   float(s[3]),
            'bucket_91_120':  float(s[4]),
            'bucket_121_150': float(s[5]),
            'bucket_151_180': float(s[6]),
            'bucket_older':   float(s[7]),
            'total':          float(s[8]),
            'dues':           sum(float(s[i]) for i in range(1, 8)),
        }

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 15. Partner enrichment (single SQL, no ORM) ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        partner_ids_aged = [r[0] for r in aged_rows]
        partner_info = {}
        if partner_ids_aged:
            cr.execute(
                """SELECT rp.id,
                          rcs.name          AS branch_name,
                          ru_part.name      AS owner_name,
                          rp.global_credit_limit,
                          rp.bank_check_status,
                          rp.property_payment_term_id
                   FROM res_partner rp
                   LEFT JOIN res_partner cp ON rp.commercial_partner_id = cp.id
                   LEFT JOIN res_country_state rcs ON rp.state_id = rcs.id
                   LEFT JOIN res_users    ru       ON COALESCE(rp.user_id, cp.user_id) = ru.id
                   LEFT JOIN res_partner  ru_part  ON ru.partner_id = ru_part.id
                   WHERE rp.id IN %s""",
                (tuple(partner_ids_aged),)
            )
            enrich_rows = cr.dictfetchall()

            term_ids = []
            company_id_str = str(self.env.company.id)
            for row in enrich_rows:
                term_val = row.get('property_payment_term_id')
                term_id  = None
                if isinstance(term_val, dict):
                    term_id = (term_val.get(company_id_str)
                               or term_val.get(self.env.company.id))
                elif isinstance(term_val, int):
                    term_id = term_val
                row['_term_id'] = term_id
                if term_id:
                    term_ids.append(term_id)

            credit_days_map = {}
            if term_ids:
                cr.execute(
                    """SELECT payment_id, MIN(nb_days)
                       FROM account_payment_term_line
                       WHERE payment_id IN %s
                       GROUP BY payment_id""",
                    (tuple(set(term_ids)),)
                )
                credit_days_map = {r[0]: r[1] or 0 for r in cr.fetchall()}

            for row in enrich_rows:
                pid       = row['id']
                limit_val = float(row.get('global_credit_limit') or 0.0)
                bcs       = row.get('bank_check_status') or 'no'
                term_id   = row['_term_id']
                partner_info[pid] = {
                    'branch_name':       row.get('branch_name') or '',
                    'owner':             row.get('owner_name') or '',
                    'credit_limit':      limit_val,
                    'credit_days':       credit_days_map.get(term_id, 0) if term_id else 0,
                    'bank_check_status': 'Yes' if bcs == 'yes' else 'No',
                }

        # ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ 16. Build aged-receivables list ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚ÂÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬
        aged_receivables_list = []
        for r in aged_rows:
            (pid, cname, cref, acc_date, inv_date,
             not_due, b1_30, b31_60, b61_90, b91_120,
             b121_150, b151_180, b_older, total) = r
            dues = (float(b1_30) + float(b31_60) + float(b61_90)
                    + float(b91_120) + float(b121_150)
                    + float(b151_180) + float(b_older))
            pinfo     = partner_info.get(pid, {})
            limit_val = pinfo.get('credit_limit', 0.0)
            if limit_val > 0:
                limit_status = 'Within Limit' if float(total) <= limit_val else 'Without Limit'
            else:
                limit_status = 'ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â'
            aged_receivables_list.append({
                'partner_id':        pid,
                'customer':          cname or '',
                'customer_ref':      cref or '',
                'accounting_date':   str(acc_date) if acc_date else '',
                'invoice_date':      str(inv_date) if inv_date else '',
                'at_date':           str(today),
                'branch_name':       pinfo.get('branch_name', ''),
                'owner':             pinfo.get('owner', ''),
                'credit_days':       pinfo.get('credit_days', 0),
                'credit_limit':      limit_val,
                'limit_status':      limit_status,
                'bank_check_status': pinfo.get('bank_check_status', 'No'),
                'not_due':           float(not_due),
                'bucket_1_30':       float(b1_30),
                'bucket_31_60':      float(b31_60),
                'bucket_61_90':      float(b61_90),
                'bucket_91_120':     float(b91_120),
                'bucket_121_150':    float(b121_150),
                'bucket_151_180':    float(b151_180),
                'bucket_older':      float(b_older),
                'total':             float(total),
                'dues':              dues,
            })

        return {
            'company_ids':              active_company_ids,
            'kpis': {
                'sales':                float(sales),
                'target':               float(total_target),
                'achievement_pct':      achievement_pct,
                'collection':           float(collection),
                'outstanding':          float(outstanding),
                'overdue_outstanding':  float(overdue_outstanding),
                'bank_received':        float(bank_received),
                'bank_partner_received': float(bank_partner_received),
                'bank_reconciled':      float(bank_reconciled),
                'bank_suspense':        float(bank_suspense),
                'bank_reconciled_pct':  float(bank_reconciled_pct),
            },
            'aged_receivables_list':    aged_receivables_list,
            'aged_receivables_summary': ar_total_summary,
            'at_date':                  str(today),
            'region_sales':             region_sales,
            'product_sales':            product_sales,
            'trend_sales':              trend_sales,
            'overdue_list':             overdue_list,
            'segment_sales':            segment_sales,
            'product_segment_sales':    product_segment_sales,
            'category_sales':           category_sales,
            # NOTE: customers, categories, branch_partner_ids are no longer
            # returned here ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â call get_static_data() once at dashboard load.
        }

    @api.model
    def get_collection_line_ids(self, company_id=None, company_ids=None,
                                year=None, month=None,
                                date_from=None, date_to=None,
                                exclude_branches=False, partner_id=None, partner_ids=None,
                                tds_filter='without_tds', categ_id=None, categ_ids=None):
        cr = self.env.cr

        company_ids_tup, _, all_branch_partner_ids = self._resolve_companies(company_id, company_ids)

        exclude_partner_ids = all_branch_partner_ids if exclude_branches else []

        p_ids = []
        if partner_ids:
            p_ids = [int(p) for p in partner_ids if str(p).isdigit() or isinstance(p, int)]
        elif partner_id and str(partner_id).isdigit():
            p_ids = [int(partner_id)]

        category_ids = self._resolve_category_ids(categ_ids, categ_id)

        collection_clauses = ["inv.move_type = 'out_invoice'", "inv.state = 'posted'", "inv.company_id IN %s"]
        collection_params  = [company_ids_tup]

        col_date_clause, col_date_params = self._get_date_filter(
            'cred', 'date', year, month, date_from, date_to
        )
        collection_clauses.append(col_date_clause)
        collection_params.extend(col_date_params)

        if exclude_partner_ids:
            collection_clauses.append("inv.partner_id NOT IN %s")
            collection_params.append(tuple(exclude_partner_ids))

        if p_ids:
            collection_clauses.append("inv.partner_id IN %s")
            collection_params.append(tuple(p_ids))

        if category_ids:
            collection_clauses.append(
                "EXISTS (SELECT 1 FROM account_move_line aml_c "
                "JOIN product_product pp_c ON aml_c.product_id = pp_c.id "
                "JOIN product_template pt_c ON pp_c.product_tmpl_id = pt_c.id "
                "WHERE aml_c.move_id = inv.id AND pt_c.categ_id IN %s)"
            )
            collection_params.append(tuple(category_ids))

        if tds_filter == 'with_tds':
            collection_clauses.append(
                "(aj.type IN ('bank', 'cash') OR (aj.type = 'general' AND "
                "(aj.name->>'en_US' ILIKE %s OR aj.code ILIKE %s OR "
                " aj.name->>'en_US' ILIKE %s OR aj.code ILIKE %s)))"
            )
            collection_params.extend(['%tds%', '%tds%', '%tcs%', '%tcs%'])
        else:
            collection_clauses.append("aj.type IN ('bank', 'cash')")

        query = f"""
            SELECT DISTINCT cred.id
            FROM account_partial_reconcile apr
            JOIN account_move_line deb ON apr.debit_move_id  = deb.id
            JOIN account_move      inv ON deb.move_id        = inv.id
            JOIN account_move_line cred ON apr.credit_move_id = cred.id
            JOIN account_journal   aj   ON cred.journal_id   = aj.id
            WHERE {" AND ".join(collection_clauses)}
        """
        cr.execute(query, tuple(collection_params))
        return [r[0] for r in cr.fetchall()]

    @api.model
    def get_bank_kpi_line_ids(self, kpi_type, company_id=None, company_ids=None,
                              year=None, month=None,
                              date_from=None, date_to=None,
                              exclude_branches=False, partner_id=None, partner_ids=None):
        cr = self.env.cr

        company_ids_tup, _, all_branch_partner_ids = self._resolve_companies(company_id, company_ids)

        exclude_partner_ids = all_branch_partner_ids if (exclude_branches and all_branch_partner_ids) else []

        p_ids = []
        if partner_ids:
            p_ids = [int(p) for p in partner_ids if str(p).isdigit() or isinstance(p, int)]
        elif partner_id and str(partner_id).isdigit():
            p_ids = [int(partner_id)]

        def _exclude_clause(alias):
            if exclude_partner_ids:
                return f"AND {alias}.partner_id NOT IN %s", (tuple(exclude_partner_ids),)
            return "", ()

        def _partner_clause(alias):
            if p_ids:
                return f"AND {alias}.partner_id IN %s", (tuple(p_ids),)
            return "", ()

        am_exclude, am_exclude_params = _exclude_clause('am')
        am_part,    am_part_params    = _partner_clause('am')

        br_date_clause, br_date_params = self._get_date_filter(
            'am', 'date', year, month, date_from, date_to
        )

        query = ""
        if kpi_type == 'received':
            query = f"""
                SELECT aml.id
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                JOIN account_journal aj ON aml.journal_id = aj.id
                WHERE aj.type = 'bank'
                  AND aml.account_id = aj.default_account_id
                  AND aml.debit > 0
                  AND am.state = 'posted'
                  AND am.company_id IN %s
                  AND {br_date_clause}
            """
        elif kpi_type == 'partner_received':
            query = f"""
                SELECT aml.id
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                JOIN account_journal aj ON aml.journal_id = aj.id
                WHERE aj.type = 'bank'
                  AND aml.account_id = aj.default_account_id
                  AND aml.debit > 0
                  AND am.state = 'posted'
                  AND aml.partner_id IS NOT NULL
                  AND am.company_id IN %s
                  AND {br_date_clause}
            """
        elif kpi_type == 'reconciled':
            query = f"""
                SELECT aml.id
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                JOIN account_journal aj ON aml.journal_id = aj.id
                LEFT JOIN account_bank_statement_line st ON st.move_id = am.id
                WHERE aj.type = 'bank'
                  AND aml.account_id = aj.default_account_id
                  AND aml.debit > 0
                  AND am.state = 'posted'
                  AND am.company_id IN %s
                  AND (st.id IS NULL OR st.is_reconciled = true)
                  AND {br_date_clause}
            """
        elif kpi_type == 'suspense':
            query = f"""
                SELECT st.id
                FROM account_bank_statement_line st
                JOIN account_move am ON st.move_id = am.id
                JOIN account_journal aj ON st.journal_id = aj.id
                WHERE aj.type = 'bank'
                  AND am.state = 'posted'
                  AND am.company_id IN %s
                  AND st.amount > 0
                  AND st.is_reconciled = false
                  AND {br_date_clause}
            """

        if not query:
            return []

        params = (company_ids_tup,) + tuple(br_date_params)
        cr.execute(query, params)
        return [r[0] for r in cr.fetchall()]
    @api.model
    def get_segment_branch_data(self, company_id=None, company_ids=None,
                                year=None, compare_year=None, exclude_branches=False):
        """Return product-segment × branch × month sales data for two years.

        This method powers the "Segment Performance" dashboard tab.
        """
        cr = self.env.cr
        today = fields.Date.today()

        # -- Year resolution ------------------------------------------------
        cur_year  = int(year)        if (year and str(year).isdigit())         else today.year
        cmp_year  = int(compare_year) if (compare_year and str(compare_year).isdigit()) else cur_year - 1

        # -- Resolve companies ------------------------------------------------
        company_ids_tup, _, all_branch_partner_ids = self._resolve_companies(company_id, company_ids)

        # -- Find Finished Goods & Trade categories and their children --------
        finished_goods_cat = self.env['product.category'].search([('name', '=', 'FINISHED GOODS')], limit=1)
        trade_cat = self.env['product.category'].search([('name', '=', 'TRADE')], limit=1)
        parent_ids = []
        if finished_goods_cat:
            parent_ids.append(finished_goods_cat.id)
        if trade_cat:
            parent_ids.append(trade_cat.id)

        if parent_ids:
            valid_cats = self.env['product.category'].search([
                ('id', 'child_of', parent_ids),
                ('name', 'not ilike', 'replacement')
            ])
            valid_cat_ids = set(valid_cats.ids)
        else:
            valid_cats = self.env['product.category'].search([
                ('name', 'not ilike', 'replacement')
            ])
            valid_cat_ids = set(valid_cats.ids)

        if not valid_cat_ids:
            valid_cat_ids = {-1}

        user_tz = self.env.context.get('tz') or 'Asia/Kolkata'

        exclude_partner_ids = all_branch_partner_ids if (exclude_branches and all_branch_partner_ids) else []
        exclude_clause = ""
        actuals_params = [user_tz, user_tz, company_ids_tup, user_tz, (cur_year, cmp_year), tuple(valid_cat_ids)]
        if exclude_partner_ids:
            exclude_clause = "AND so.partner_id NOT IN %s"
            actuals_params.append(tuple(exclude_partner_ids))

        # -- Actual sales query: fetch raw confirmed / invoiced order lines for the two years --
        has_branch = 'res.branch' in self.env
        if has_branch:
            branch_expr = "COALESCE(rb.name, rc.name)"
            branch_join = """
                LEFT JOIN res_branch rb ON sol.branch_id = rb.id
                JOIN res_company    rc ON so.company_id  = rc.id
            """
        else:
            branch_expr = "rc.name"
            branch_join = "JOIN res_company rc ON so.company_id = rc.id"

        has_mrp = 'mrp.bom' in self.env
        mrp_kit_clause = ""
        if has_mrp:
            mrp_kit_clause = """
                OR EXISTS (
                    SELECT 1 FROM mrp_bom b
                    WHERE (b.product_id = pp.id OR (b.product_id IS NULL AND b.product_tmpl_id = pt.id))
                      AND b.type = 'phantom'
                      AND b.active = true
                )
            """

        actuals_query = f"""
            SELECT
                sol.id,
                sol.product_id,
                pc.name                                       AS category_name,
                {branch_expr}                                 AS branch,
                EXTRACT(YEAR  FROM (so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s))::int        AS yr,
                TO_CHAR((so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s), 'Mon')                 AS mon,
                COALESCE(sol.qty_invoiced, 0)                 AS qty
            FROM sale_order_line sol
            JOIN sale_order      so  ON sol.order_id    = so.id
            JOIN product_product pp  ON sol.product_id  = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            JOIN product_category pc ON pt.categ_id     = pc.id
            {branch_join}
            WHERE so.state IN ('sale', 'done')
              AND so.company_id IN %s
              AND EXTRACT(YEAR FROM (so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)) IN %s
              AND sol.qty_delivered > 0
              AND EXISTS (
                  SELECT 1
                  FROM sale_order_line_invoice_rel rel
                  JOIN account_move_line aml ON rel.invoice_line_id = aml.id
                  JOIN account_move am ON aml.move_id = am.id
                  WHERE rel.order_line_id = sol.id
                    AND am.move_type = 'out_invoice'
                    AND am.state = 'posted'
              )
              AND (
                  pc.id IN %s
                  {mrp_kit_clause}
              )
              {exclude_clause}
        """

        cr.execute(actuals_query, tuple(actuals_params))
        actuals_rows = cr.fetchall()

        # Prefetch boms for batch optimization
        product_ids = {row[1] for row in actuals_rows}
        products = self.env['product.product'].browse(list(product_ids))
        boms_map = {}
        if has_mrp and products:
            boms_map = self.env['mrp.bom']._bom_find(products, bom_type='phantom')

        def get_segment_for_category(cat_id, cat_name):
            if cat_id not in valid_cat_ids:
                return None
            if not cat_name or 'replacement' in cat_name.lower():
                return None
            cat_name_lower = cat_name.lower()
            if any(x in cat_name_lower for x in ('tw', 'vrla', '2w', 'two wheel', 'two-wheel')):
                return '2W'
            if 'hups' in cat_name_lower:
                return 'HUPS'
            if 'ib' in cat_name_lower:
                return 'IB'
            if any(x in cat_name_lower for x in ('spgs', 'solar', 'panel')):
                return 'PANEL'
            if any(x in cat_name_lower for x in ('lithium', 'li-ion', 'li_ion', 'essm')):
                return 'LITHIUM'
            if any(x in cat_name_lower for x in ('gti', 'hybrid')):
                return 'GTI'
            return None

        # Build actuals map with BOM explosion
        actuals = {}
        branches_set = set()

        for sol_id, product_id, category_name, branch, yr, mon, qty in actuals_rows:
            if not branch:
                continue
            
            product = self.env['product.product'].browse(product_id)
            bom = boms_map.get(product) if boms_map else None

            if bom:
                # Explode BOM Kit
                try:
                    _, lines_done = bom.explode(product, float(qty))
                    for bom_line, line_val in lines_done:
                        comp_product = bom_line.product_id
                        comp_qty = line_val['qty']
                        comp_seg = get_segment_for_category(comp_product.categ_id.id, comp_product.categ_id.name)
                        if comp_seg:
                            key = (comp_seg, branch, int(yr), mon)
                            actuals[key] = float(actuals.get(key, 0)) + float(comp_qty)
                            branches_set.add(branch)
                except Exception:
                    # Fallback to parent product category
                    parent_seg = get_segment_for_category(product.categ_id.id, category_name)
                    if parent_seg:
                        key = (parent_seg, branch, int(yr), mon)
                        actuals[key] = float(actuals.get(key, 0)) + float(qty)
                        branches_set.add(branch)
            else:
                # Normal product category
                parent_seg = get_segment_for_category(product.categ_id.id, category_name)
                if parent_seg:
                    key = (parent_seg, branch, int(yr), mon)
                    actuals[key] = float(actuals.get(key, 0)) + float(qty)
                    branches_set.add(branch)

        # -- AOP targets from sale.segment.target --
        aop_query = """
            SELECT segment, branch_name, month, year, COALESCE(SUM(target_qty), 0)
            FROM   sale_segment_target
            WHERE  company_id IN %s
              AND  year IN %s
            GROUP BY segment, branch_name, month, year
        """
        cr.execute(aop_query, (company_ids_tup, (str(cur_year), str(cmp_year))))
        aop_rows = cr.fetchall()

        ALL_SEGMENTS = ['HUPS', 'IB', '2W', 'VRLA', 'PANEL', 'GTI', 'LITHIUM']

        # aop: {(segment, branch, year, month): qty}
        aop: dict = {}
        for seg, branch, mon, yr, target_qty in aop_rows:
            if seg and branch:
                key = (seg, branch, int(yr), mon)
                aop[key] = int(aop.get(key, 0)) + int(target_qty)
                branches_set.add(branch)

        branches = sorted(branches_set)

        def _pct(num, den):
            return round(num / den * 100, 1) if den else 0.0

        # Build response data structures
        data = {}
        for seg in ALL_SEGMENTS:
            seg_cur_total  = 0.0
            seg_cmp_total  = 0.0
            seg_aop_total  = 0

            seg_months = {}
            for mon in MONTHS_ORDER:
                cur_q = sum(actuals.get((seg, br, cur_year, mon), 0) for br in branches)
                cmp_q = sum(actuals.get((seg, br, cmp_year, mon), 0) for br in branches)
                seg_months[mon] = {'cur': int(cur_q), 'cmp': int(cmp_q)}
                seg_cur_total += cur_q
                seg_cmp_total += cmp_q
                seg_aop_total += sum(aop.get((seg, br, cur_year, mon), 0) for br in branches)

            branch_data = {}
            for br in branches:
                br_cur  = 0.0
                br_cmp  = 0.0
                br_aop  = 0
                br_months = {}
                for mon in MONTHS_ORDER:
                    cur_q = actuals.get((seg, br, cur_year, mon), 0)
                    cmp_q = actuals.get((seg, br, cmp_year, mon), 0)
                    a_q   = aop.get((seg, br, cur_year, mon), 0)
                    br_months[mon] = {'cur': int(cur_q), 'cmp': int(cmp_q), 'aop': int(a_q)}
                    br_cur += cur_q
                    br_cmp += cmp_q
                    br_aop += a_q

                branch_data[br] = {
                    '_aop':        br_aop,
                    '_total_cmp':  int(br_cmp),
                    '_total_cur':  int(br_cur),
                    '_growth_pct': _pct(br_cur - br_cmp, br_cmp) if br_cmp else 0.0,
                    '_aop_ach_pct': _pct(br_cur, br_aop),
                    '_months':     br_months,
                }

            data[seg] = {
                '_total_cmp':   int(seg_cmp_total),
                '_total_cur':   int(seg_cur_total),
                '_growth_pct':  _pct(seg_cur_total - seg_cmp_total, seg_cmp_total) if seg_cmp_total else 0.0,
                '_aop_total':   seg_aop_total,
                '_aop_ach_pct': _pct(seg_cur_total, seg_aop_total),
                '_months':      seg_months,
                **branch_data,
            }

        return {
            'year':         str(cur_year),
            'compare_year': str(cmp_year),
            'months':       MONTHS_ORDER,
            'segments':     ALL_SEGMENTS,
            'branches':     branches,
            'data':         data,
        }

    @api.model
    def export_segment_performance_excel(self, company_id=None, company_ids=None,
                                         year=None, compare_year=None, exclude_branches=False):
        import io
        import base64
        from odoo.exceptions import UserError
        try:
            import xlsxwriter
        except ImportError:
            raise UserError("The xlsxwriter library is required to export to Excel.")

        # Get dashboard data
        res = self.get_segment_branch_data(
            company_id=company_id,
            company_ids=company_ids,
            year=year,
            compare_year=compare_year,
            exclude_branches=exclude_branches
        )
        
        cur_year = res['year']
        cmp_year = res['compare_year']
        months = res['months']
        segments = res['segments']
        branches = res['branches']
        data = res['data']

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Styles
        title_style = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center', 'valign': 'vcenter',
            'bg_color': '#1e3a8a', 'font_color': '#ffffff'
        })
        header_style = workbook.add_format({
            'bold': True, 'font_size': 11, 'align': 'center', 'valign': 'vcenter',
            'bg_color': '#2563eb', 'font_color': '#ffffff', 'border': 1
        })
        data_label_style = workbook.add_format({'bold': True, 'font_size': 10, 'border': 1})
        data_value_style = workbook.add_format({'font_size': 10, 'align': 'right', 'border': 1, 'num_format': '#,##0'})
        cmp_value_style = workbook.add_format({'font_size': 10, 'align': 'right', 'border': 1, 'num_format': '#,##0', 'font_color': '#475569'})
        
        pct_style = workbook.add_format({'font_size': 10, 'align': 'right', 'border': 1, 'num_format': '0.0%'})
        
        # Summary Sheet
        sheet1 = workbook.add_worksheet('Segment Summary')
        sheet1.merge_range('A1:AA1', f'Product Segment Performance (vs AOP) - Summary ({cur_year} vs {cmp_year})', title_style)
        sheet1.set_row(0, 30)
        
        headers = ['Segment', 'Year Type', 'AOP', f'Total {cmp_year}', f'Total {cur_year}', 'Growth %', 'AOP Ach %']
        for m in months:
            headers.append(f'{m} {cur_year}')
            headers.append(f'{m} {cmp_year}')
            
        sheet1.set_row(2, 25)
        for col_idx, h in enumerate(headers):
            sheet1.write(2, col_idx, h, header_style)
            
        row_num = 3
        for seg in segments:
            seg_data = data[seg]
            
            # Row 1: Current Year
            sheet1.write(row_num, 0, seg, data_label_style)
            sheet1.write(row_num, 1, f'Actuals {cur_year}', data_label_style)
            sheet1.write(row_num, 2, seg_data.get('_aop_total', 0), data_value_style)
            sheet1.write(row_num, 3, seg_data.get('_total_cmp', 0), data_value_style)
            sheet1.write(row_num, 4, seg_data.get('_total_cur', 0), data_value_style)
            # xlsxwriter requires fractional value for percentages
            sheet1.write(row_num, 5, seg_data.get('_growth_pct', 0) / 100.0, pct_style)
            sheet1.write(row_num, 6, seg_data.get('_aop_ach_pct', 0) / 100.0, pct_style)
            
            for m_idx, m in enumerate(months):
                val = seg_data.get('_months', {}).get(m, {})
                sheet1.write(row_num, 7 + 2*m_idx, val.get('cur', 0), data_value_style)
                sheet1.write(row_num, 8 + 2*m_idx, val.get('cmp', 0), cmp_value_style)
            
            row_num += 1
            
        # Adjust column widths
        sheet1.set_column('A:A', 20)
        sheet1.set_column('B:B', 15)
        sheet1.set_column('C:G', 12)
        sheet1.set_column('H:AA', 10)
        
        # Branch Sheet
        sheet2 = workbook.add_worksheet('Branch Breakdown')
        sheet2.merge_range('A1:AA1', f'Branch Performance Breakdown by Segment ({cur_year} vs {cmp_year})', title_style)
        sheet2.set_row(0, 30)
        
        branch_headers = ['Segment', 'Branch', 'Year Type', 'AOP', f'Total {cmp_year}', f'Total {cur_year}', 'Growth %', 'AOP Ach %']
        for m in months:
            branch_headers.append(f'{m} {cur_year}')
            branch_headers.append(f'{m} {cmp_year}')
            
        sheet2.set_row(2, 25)
        for col_idx, h in enumerate(branch_headers):
            sheet2.write(2, col_idx, h, header_style)
            
        row_num2 = 3
        for seg in segments:
            for br in branches:
                br_data = data[seg].get(br)
                if not br_data:
                    continue
                # Skip if no data at all
                if not br_data.get('_aop') and not br_data.get('_total_cmp') and not br_data.get('_total_cur'):
                    continue
                    
                # Current year row
                sheet2.write(row_num2, 0, seg, data_label_style)
                sheet2.write(row_num2, 1, br, data_label_style)
                sheet2.write(row_num2, 2, f'Actuals {cur_year}', data_label_style)
                sheet2.write(row_num2, 3, br_data.get('_aop', 0), data_value_style)
                sheet2.write(row_num2, 4, br_data.get('_total_cmp', 0), data_value_style)
                sheet2.write(row_num2, 5, br_data.get('_total_cur', 0), data_value_style)
                sheet2.write(row_num2, 6, br_data.get('_growth_pct', 0) / 100.0, pct_style)
                sheet2.write(row_num2, 7, br_data.get('_aop_ach_pct', 0) / 100.0, pct_style)
                
                for m_idx, m in enumerate(months):
                    val = br_data.get('_months', {}).get(m, {})
                    sheet2.write(row_num2, 8 + 2*m_idx, val.get('cur', 0), data_value_style)
                    sheet2.write(row_num2, 9 + 2*m_idx, val.get('cmp', 0), cmp_value_style)
                
                row_num2 += 1
                
        sheet2.set_column('A:A', 15)
        sheet2.set_column('B:B', 30)
        sheet2.set_column('C:C', 15)
        sheet2.set_column('D:H', 12)
        sheet2.set_column('I:AA', 10)
        
        workbook.close()
        output.seek(0)
        file_data = base64.b64encode(output.read()).decode('utf-8')
        output.close()
        
        return file_data

    # ------------------------------------------------------------------
    @api.model
    def get_segment_order_ids(self, segment, year=None, branch_name=None, month=None,
                              exclude_branches=False, company_id=None, company_ids=None):
        """Return sale.order.line IDs matching a product segment + year + optional branch + optional month.

        Called by the JS click handler so the frontend can open a filtered
        sale.report list view (showing: SO ref, product, qty, subtotal, customer).
        """
        cr = self.env.cr
        today = fields.Date.today()

        company_ids_tup, _, all_branch_partner_ids = self._resolve_companies(company_id, company_ids)
        cur_year = int(year) if (year and str(year).isdigit()) else today.year

        # -- Find Finished Goods & Trade categories and their children --------
        finished_goods_cat = self.env['product.category'].search([('name', '=', 'FINISHED GOODS')], limit=1)
        trade_cat = self.env['product.category'].search([('name', '=', 'TRADE')], limit=1)
        parent_ids = []
        if finished_goods_cat:
            parent_ids.append(finished_goods_cat.id)
        if trade_cat:
            parent_ids.append(trade_cat.id)

        if parent_ids:
            valid_cats = self.env['product.category'].search([
                ('id', 'child_of', parent_ids),
                ('name', 'not ilike', 'replacement')
            ])
            valid_cat_ids = set(valid_cats.ids)
        else:
            valid_cats = self.env['product.category'].search([
                ('name', 'not ilike', 'replacement')
            ])
            valid_cat_ids = set(valid_cats.ids)

        if not valid_cat_ids:
            valid_cat_ids = {-1}

        exclude_partner_ids = all_branch_partner_ids if (exclude_branches and all_branch_partner_ids) else []

        has_branch = 'res.branch' in self.env
        if has_branch:
            branch_expr = "COALESCE(rb.name, rc.name)"
            branch_join  = """
                LEFT JOIN res_branch rb ON sol.branch_id = rb.id
                JOIN res_company    rc ON so.company_id  = rc.id
            """
        else:
            branch_expr = "rc.name"
            branch_join  = "JOIN res_company rc ON so.company_id = rc.id"

        has_mrp = 'mrp.bom' in self.env
        mrp_kit_clause = ""
        if has_mrp:
            mrp_kit_clause = """
                OR EXISTS (
                    SELECT 1 FROM mrp_bom b
                    WHERE (b.product_id = pp.id OR (b.product_id IS NULL AND b.product_tmpl_id = pt.id))
                      AND b.type = 'phantom'
                      AND b.active = true
                )
            """

        user_tz = self.env.context.get('tz') or 'Asia/Kolkata'

        branch_filter  = ""
        month_filter   = ""
        exclude_clause = ""
        params = [company_ids_tup, user_tz, cur_year, tuple(valid_cat_ids)]
        if branch_name:
            branch_filter = f"AND {branch_expr} = %s"
            params.append(branch_name)
        if month:
            month_filter = "AND TO_CHAR((so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s), 'Mon') = %s"
            params.extend([user_tz, month])
        if exclude_partner_ids:
            exclude_clause = "AND so.partner_id NOT IN %s"
            params.append(tuple(exclude_partner_ids))

        # SELECT raw lines that match categories or kits
        query = f"""
            SELECT
                sol.id,
                sol.product_id,
                pc.name                                       AS category_name
            FROM sale_order_line sol
            JOIN sale_order      so  ON sol.order_id    = so.id
            JOIN product_product pp  ON sol.product_id  = pp.id
            JOIN product_template pt ON pp.product_tmpl_id = pt.id
            JOIN product_category pc ON pt.categ_id     = pc.id
            {branch_join}
            WHERE so.state IN ('sale', 'done')
              AND so.company_id IN %s
              AND EXTRACT(YEAR FROM (so.date_order AT TIME ZONE 'UTC' AT TIME ZONE %s)) = %s
              AND sol.qty_delivered > 0
              AND EXISTS (
                  SELECT 1
                  FROM sale_order_line_invoice_rel rel
                  JOIN account_move_line aml ON rel.invoice_line_id = aml.id
                  JOIN account_move am ON aml.move_id = am.id
                  WHERE rel.order_line_id = sol.id
                    AND am.move_type = 'out_invoice'
                    AND am.state = 'posted'
              )
              AND (
                  pc.id IN %s
                  {mrp_kit_clause}
              )
              {branch_filter}
              {month_filter}
              {exclude_clause}
        """
        cr.execute(query, params)
        rows = cr.fetchall()

        product_ids = {r[1] for r in rows}
        products = self.env['product.product'].browse(list(product_ids))
        boms_map = {}
        if has_mrp and products:
            boms_map = self.env['mrp.bom']._bom_find(products, bom_type='phantom')

        def get_segment_for_category(cat_id, cat_name):
            if cat_id not in valid_cat_ids:
                return None
            if not cat_name or 'replacement' in cat_name.lower():
                return None
            cat_name_lower = cat_name.lower()
            if any(x in cat_name_lower for x in ('tw', 'vrla', '2w', 'two wheel', 'two-wheel')):
                return '2W'
            if 'hups' in cat_name_lower:
                return 'HUPS'
            if 'ib' in cat_name_lower:
                return 'IB'
            if any(x in cat_name_lower for x in ('spgs', 'solar', 'panel')):
                return 'PANEL'
            if any(x in cat_name_lower for x in ('lithium', 'li-ion', 'li_ion', 'essm')):
                return 'LITHIUM'
            if any(x in cat_name_lower for x in ('gti', 'hybrid')):
                return 'GTI'
            return None

        matching_line_ids = []
        for sol_id, product_id, category_name in rows:
            product = self.env['product.product'].browse(product_id)
            bom = boms_map.get(product) if boms_map else None

            if bom:
                try:
                    _, lines_done = bom.explode(product, 1.0)
                    for bom_line, _ in lines_done:
                        comp_product = bom_line.product_id
                        comp_seg = get_segment_for_category(comp_product.categ_id.id, comp_product.categ_id.name)
                        if comp_seg == segment:
                            matching_line_ids.append(sol_id)
                            break
                except Exception:
                    parent_seg = get_segment_for_category(product.categ_id.id, category_name)
                    if parent_seg == segment:
                        matching_line_ids.append(sol_id)
            else:
                parent_seg = get_segment_for_category(product.categ_id.id, category_name)
                if parent_seg == segment:
                    matching_line_ids.append(sol_id)

        return {'ids': matching_line_ids, 'valid_cat_ids': list(valid_cat_ids)}


class SaleReport(models.Model):
    _inherit = 'sale.report'

    @api.model
    def web_search_read(self, domain, specification, offset=0, limit=None, order=None, count_limit=None):
        res = super(SaleReport, self).web_search_read(domain, specification, offset=offset, limit=limit, order=order, count_limit=count_limit)
        
        target_segment = self.env.context.get('target_segment')
        if target_segment and 'records' in res:
            finished_goods_cat = self.env['product.category'].search([('name', '=', 'FINISHED GOODS')], limit=1)
            trade_cat = self.env['product.category'].search([('name', '=', 'TRADE')], limit=1)
            parent_ids = []
            if finished_goods_cat: parent_ids.append(finished_goods_cat.id)
            if trade_cat: parent_ids.append(trade_cat.id)
            
            if parent_ids:
                valid_cats = self.env['product.category'].search([
                    ('id', 'child_of', parent_ids),
                    ('name', 'not ilike', 'replacement')
                ])
                valid_cat_ids = set(valid_cats.ids)
            else:
                valid_cat_ids = set()

            def get_segment_for_category(cat_id, cat_name):
                if cat_id not in valid_cat_ids:
                    return None
                if not cat_name or 'replacement' in cat_name.lower():
                    return None
                cat_name_lower = cat_name.lower()
                if any(x in cat_name_lower for x in ('tw', 'vrla', '2w', 'two wheel', 'two-wheel')):
                    return '2W'
                if 'hups' in cat_name_lower:
                    return 'HUPS'
                if 'ib' in cat_name_lower:
                    return 'IB'
                if any(x in cat_name_lower for x in ('spgs', 'solar', 'panel')):
                    return 'PANEL'
                if any(x in cat_name_lower for x in ('lithium', 'li-ion', 'li_ion', 'essm')):
                    return 'LITHIUM'
                if any(x in cat_name_lower for x in ('gti', 'hybrid')):
                    return 'GTI'
                return None

            product_ids = []
            for r in res['records']:
                p_id = r.get('product_id')
                if p_id:
                    if isinstance(p_id, dict) and 'id' in p_id:
                        product_ids.append(p_id['id'])
                    elif isinstance(p_id, (list, tuple)) and p_id:
                        product_ids.append(p_id[0])
                    elif isinstance(p_id, int):
                        product_ids.append(p_id)

            products = self.env['product.product'].browse(product_ids)
            boms_map = {}
            if 'mrp.bom' in self.env and products:
                boms_map = self.env['mrp.bom']._bom_find(products, bom_type='phantom')

            for record in res['records']:
                p_id = record.get('product_id')
                if not p_id:
                    continue
                actual_prod_id = None
                if isinstance(p_id, dict) and 'id' in p_id:
                    actual_prod_id = p_id['id']
                elif isinstance(p_id, (list, tuple)) and p_id:
                    actual_prod_id = p_id[0]
                elif isinstance(p_id, int):
                    actual_prod_id = p_id
                
                if not actual_prod_id:
                    continue
                    
                product = self.env['product.product'].browse(actual_prod_id)
                bom = boms_map.get(product) if boms_map else None
                if bom:
                    try:
                        _, lines_done = bom.explode(product, 1.0)
                        ratio = 0.0
                        for bom_line, line_val in lines_done:
                            comp_product = bom_line.product_id
                            comp_seg = get_segment_for_category(comp_product.categ_id.id, comp_product.categ_id.name)
                            if comp_seg == target_segment:
                                ratio += line_val['qty']
                        
                        if ratio > 0.0:
                            for qty_field in ('product_uom_qty', 'qty_delivered', 'qty_invoiced', 'qty_to_deliver', 'qty_to_invoice'):
                                if qty_field in record:
                                    record[qty_field] = record[qty_field] * ratio
                    except Exception:
                        pass
        return res

    @api.model
    def web_read_group(self, domain, fields, groupby, limit=None, offset=0, orderby=False, lazy=True):
        res = super(SaleReport, self).web_read_group(domain, fields, groupby, limit=limit, offset=offset, orderby=orderby, lazy=lazy)
        
        target_segment = self.env.context.get('target_segment')
        if target_segment and 'groups' in res:
            finished_goods_cat = self.env['product.category'].search([('name', '=', 'FINISHED GOODS')], limit=1)
            trade_cat = self.env['product.category'].search([('name', '=', 'TRADE')], limit=1)
            parent_ids = []
            if finished_goods_cat: parent_ids.append(finished_goods_cat.id)
            if trade_cat: parent_ids.append(trade_cat.id)
            
            if parent_ids:
                valid_cats = self.env['product.category'].search([
                    ('id', 'child_of', parent_ids),
                    ('name', 'not ilike', 'replacement')
                ])
                valid_cat_ids = set(valid_cats.ids)
            else:
                valid_cat_ids = set()

            def get_segment_for_category(cat_id, cat_name):
                if cat_id not in valid_cat_ids:
                    return None
                if not cat_name or 'replacement' in cat_name.lower():
                    return None
                cat_name_lower = cat_name.lower()
                if any(x in cat_name_lower for x in ('tw', 'vrla', '2w', 'two wheel', 'two-wheel')):
                    return '2W'
                if 'hups' in cat_name_lower:
                    return 'HUPS'
                if 'ib' in cat_name_lower:
                    return 'IB'
                if any(x in cat_name_lower for x in ('spgs', 'solar', 'panel')):
                    return 'PANEL'
                if any(x in cat_name_lower for x in ('lithium', 'li-ion', 'li_ion', 'essm')):
                    return 'LITHIUM'
                if any(x in cat_name_lower for x in ('gti', 'hybrid')):
                    return 'GTI'
                return None

            for group in res['groups']:
                group_domain = group.get('__domain')
                if not group_domain:
                    continue
                records = self.env['sale.report'].search(group_domain)
                if not records:
                    continue
                
                products = records.mapped('product_id')
                boms_map = {}
                if 'mrp.bom' in self.env and products:
                    boms_map = self.env['mrp.bom']._bom_find(products, bom_type='phantom')

                totals = {f: 0.0 for f in fields if f in ('product_uom_qty', 'qty_delivered', 'qty_invoiced', 'qty_to_deliver', 'qty_to_invoice')}
                
                for r in records:
                    bom = boms_map.get(r.product_id) if boms_map else None
                    ratio = 1.0
                    if bom:
                        try:
                            _, lines_done = bom.explode(r.product_id, 1.0)
                            ratio = 0.0
                            for bom_line, line_val in lines_done:
                                comp_product = bom_line.product_id
                                comp_seg = get_segment_for_category(comp_product.categ_id.id, comp_product.categ_id.name)
                                if comp_seg == target_segment:
                                    ratio += line_val['qty']
                        except Exception:
                            ratio = 1.0
                    
                    for f in totals:
                        val = getattr(r, f, 0.0) or 0.0
                        totals[f] += val * ratio

                for f, val in totals.items():
                    if f in group:
                        group[f] = val
        return res
