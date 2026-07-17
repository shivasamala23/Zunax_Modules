# -*- coding: utf-8 -*-
import math
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class ZunaxCustomerPortal(CustomerPortal):

    # ─── Counters for portal home ────────────────────────────────────────────

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        partner = request.env.user.partner_id.commercial_partner_id

        SaleOrder = request.env['sale.order'].sudo()

        if 'quotation_count' in counters:
            values['quotation_count'] = SaleOrder.search_count([
                ('partner_id', 'child_of', partner.id),
                ('state', 'in', ['draft', 'sent']),
            ])

        if 'order_count' in counters:
            values['order_count'] = SaleOrder.search_count([
                ('partner_id', 'child_of', partner.id),
                ('state', 'in', ['sale', 'done']),
            ])

        if 'ledger_count' in counters:
            # Count of posted move lines in receivable/payable accounts
            all_account_ids = self._get_ledger_account_ids()
            values['ledger_count'] = request.env['account.move.line'].sudo().search_count([
                ('parent_state', '=', 'posted'),
                ('partner_id', 'child_of', partner.id),
                ('account_id', 'in', all_account_ids),
            ])

        return values

    # ─── Helpers ────────────────────────────────────────────────────────────

    def _get_ledger_account_ids(self):
        """Return receivable + payable account IDs for the current company."""
        receivable = request.env['account.account'].sudo().search([
            ('account_type', '=', 'asset_receivable'),
        ]).ids
        payable = request.env['account.account'].sudo().search([
            ('account_type', '=', 'liability_payable'),
        ]).ids
        return receivable + payable

    def _get_partner(self):
        return request.env.user.partner_id.commercial_partner_id

    # ─── Customer Ledger ─────────────────────────────────────────────────────

    @http.route(['/my/ledger', '/my/ledger/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_ledger(self, page=1, **kw):
        partner = self._get_partner()
        all_account_ids = self._get_ledger_account_ids()

        MoveLineSudo = request.env['account.move.line'].sudo()
        domain = [
            ('parent_state', '=', 'posted'),
            ('partner_id', 'child_of', partner.id),
            ('account_id', 'in', all_account_ids),
        ]

        total_count = MoveLineSudo.search_count(domain)
        page_size = 20
        pager = portal_pager(
            url='/my/ledger',
            total=total_count,
            page=page,
            step=page_size,
        )

        move_lines = MoveLineSudo.search(
            domain,
            order='date asc, id asc',
            limit=page_size,
            offset=pager['offset'],
        )

        # Compute running balance up to the current page offset
        all_lines_before = MoveLineSudo.search(
            domain,
            order='date asc, id asc',
            limit=pager['offset'],
        )
        opening_balance = sum(l.debit - l.credit for l in all_lines_before)

        # Build rows with running balance
        rows = []
        running = opening_balance
        for line in move_lines:
            running += (line.debit - line.credit)
            rows.append({
                'line': line,
                'running_balance': running,
                'is_receivable': running >= 0,
            })

        # Summary totals (all lines)
        all_lines = MoveLineSudo.search(domain, order='date asc, id asc')
        total_debit = sum(l.debit for l in all_lines)
        total_credit = sum(l.credit for l in all_lines)
        final_balance = total_debit - total_credit

        # Get financial summary for sidebar
        financial_data = request.env['account.move'].get_portal_financial_summary(partner)

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'ledger',
            'partner': partner,
            'rows': rows,
            'pager': pager,
            'total_debit': total_debit,
            'total_credit': total_credit,
            'final_balance': final_balance,
            'financial_data': financial_data,
            'currency_symbol': financial_data.get('currency_symbol', '₹'),
        })
        return request.render('zunax_customer_portal.portal_my_ledger', values)

    # ─── Quotations List ─────────────────────────────────────────────────────

    @http.route(['/my/quotations', '/my/quotations/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_quotations(self, page=1, **kw):
        partner = self._get_partner()
        SaleOrder = request.env['sale.order'].sudo()

        domain = [
            ('partner_id', 'child_of', partner.id),
            ('state', 'in', ['draft', 'sent']),
        ]
        total = SaleOrder.search_count(domain)
        page_size = 10
        pager = portal_pager(
            url='/my/quotations',
            total=total,
            page=page,
            step=page_size,
        )
        quotations = SaleOrder.search(
            domain,
            order='date_order desc',
            limit=page_size,
            offset=pager['offset'],
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'quotations',
            'quotations': quotations,
            'pager': pager,
            'default_url': '/my/quotations',
        })
        return request.render('zunax_customer_portal.portal_my_quotations', values)

    # ─── Quotation Detail ────────────────────────────────────────────────────

    @http.route(['/my/quotations/<int:order_id>'],
                type='http', auth='user', website=True)
    def portal_quotation_detail(self, order_id, **kw):
        partner = self._get_partner()
        order = request.env['sale.order'].sudo().browse(order_id)

        # Security: must belong to the partner
        if not order.exists() or order.partner_id.commercial_partner_id.id != partner.id:
            return request.redirect('/my/quotations')

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'quotation_detail',
            'order': order,
            'currency_symbol': order.currency_id.symbol or '₹',
        })
        return request.render('zunax_customer_portal.portal_quotation_detail', values)

    # ─── New Quotation Request Form ──────────────────────────────────────────

    @http.route(['/my/quotations/new'],
                type='http', auth='user', website=True)
    def portal_new_quotation(self, **kw):
        partner = self._get_partner()
        products = partner.get_portal_products()

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'new_quotation',
            'partner': partner,
            'products': products,
            'error': kw.get('error', ''),
        })
        return request.render('zunax_customer_portal.portal_new_quotation', values)

    # ─── Submit Quotation Request (POST) ────────────────────────────────────

    @http.route(['/my/quotations/submit'],
                type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def portal_submit_quotation(self, **post):
        partner = self._get_partner()

        # Parse submitted lines: product_id_N, qty_N, note_N
        lines = []
        i = 1
        while f'product_id_{i}' in post:
            product_id = int(post.get(f'product_id_{i}', 0) or 0)
            qty = float(post.get(f'qty_{i}', 1) or 1)
            if product_id and qty > 0:
                product = request.env['product.product'].sudo().browse(product_id)
                if product.exists():
                    lines.append((0, 0, {
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'price_unit': product.lst_price,
                        'name': product.display_name,
                        'product_uom': product.uom_id.id,
                    }))
            i += 1

        if not lines:
            return request.redirect('/my/quotations/new?error=no_products')

        portal_note = post.get('portal_note', '').strip()

        # Create the draft sale order
        SaleOrder = request.env['sale.order'].sudo()
        order = SaleOrder.create({
            'partner_id': partner.id,
            'order_line': lines,
            'portal_note': portal_note,
            'note': portal_note,
            'origin': f'Portal Request by {request.env.user.name}',
        })

        return request.redirect(f'/my/quotations/{order.id}?success=1')

    # ─── Confirmed Orders List ───────────────────────────────────────────────

    @http.route(['/my/orders', '/my/orders/page/<int:page>'],
                type='http', auth='user', website=True)
    def portal_my_orders(self, page=1, **kw):
        partner = self._get_partner()
        SaleOrder = request.env['sale.order'].sudo()

        domain = [
            ('partner_id', 'child_of', partner.id),
            ('state', 'in', ['sale', 'done']),
        ]
        total = SaleOrder.search_count(domain)
        page_size = 10
        pager = portal_pager(
            url='/my/orders',
            total=total,
            page=page,
            step=page_size,
        )
        orders = SaleOrder.search(
            domain,
            order='date_order desc',
            limit=page_size,
            offset=pager['offset'],
        )

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'orders',
            'orders': orders,
            'pager': pager,
        })
        return request.render('zunax_customer_portal.portal_my_orders', values)

    # ─── Order + Shipment Tracking ───────────────────────────────────────────

    @http.route(['/my/orders/<int:order_id>/track'],
                type='http', auth='user', website=True)
    def portal_order_track(self, order_id, **kw):
        partner = self._get_partner()
        order = request.env['sale.order'].sudo().browse(order_id)

        if not order.exists() or order.partner_id.commercial_partner_id.id != partner.id:
            return request.redirect('/my/orders')

        # Outgoing pickings
        pickings = order.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing'
        ).sorted('id')

        values = self._prepare_portal_layout_values()
        values.update({
            'page_name': 'order_track',
            'order': order,
            'pickings': pickings,
            'currency_symbol': order.currency_id.symbol or '₹',
        })
        return request.render('zunax_customer_portal.portal_order_track', values)
