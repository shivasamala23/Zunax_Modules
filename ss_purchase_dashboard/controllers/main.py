# -*- coding: utf-8 -*-
import io
import xlsxwriter
from odoo import http, fields
from odoo.http import request

class PurchaseDashboardController(http.Controller):
    @http.route('/purchase_dashboard/export_xlsx', type='http', auth='user')
    def export_xlsx(self, company_id=None, company_ids=None, year=None, month=None, date_from=None, date_to=None, category_ids=None, partner_ids=None, exclude_partner_ids=None, **kwargs):
        if not company_id:
            company_id = request.env.company.id
        else:
            company_id = int(company_id)

        parsed_company_ids = []
        if company_ids:
            parsed_company_ids = [int(x) for x in company_ids.split(',') if x.strip().isdigit()]

        parsed_category_ids = []
        if category_ids:
            parsed_category_ids = [int(x) for x in category_ids.split(',') if x.strip().isdigit()]

        parsed_partner_ids = []
        if partner_ids:
            parsed_partner_ids = [int(x) for x in partner_ids.split(',') if x.strip().isdigit()]

        parsed_exclude_partner_ids = []
        if exclude_partner_ids:
            parsed_exclude_partner_ids = [int(x) for x in exclude_partner_ids.split(',') if x.strip().isdigit()]

        exclude_branches = kwargs.get('exclude_branches') == 'true'
        # Fetch the data
        dashboard = request.env['purchase.dashboard']
        data = dashboard.get_dashboard_data(
            company_id=company_id,
            company_ids=parsed_company_ids,
            year=year,
            month=month,
            date_from=date_from or None,
            date_to=date_to or None,
            category_ids=parsed_category_ids,
            partner_ids=parsed_partner_ids,
            exclude_partner_ids=parsed_exclude_partner_ids,
            exclude_branches=exclude_branches
        )

        # Create in-memory file
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Common formats
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_name': 'Segoe UI', 'font_color': '#4F46E5', 'align': 'left'
        })
        header_format = workbook.add_format({
            'bold': True, 'font_name': 'Segoe UI', 'bg_color': '#4F46E5', 'font_color': 'white', 'border': 1, 'align': 'center'
        })
        sub_header_format = workbook.add_format({
            'bold': True, 'font_name': 'Segoe UI', 'bg_color': '#F1F5F9', 'border': 1, 'align': 'left'
        })
        data_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'left'
        })
        num_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'right', 'num_format': '#,##0.00'
        })
        qty_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'right', 'num_format': '#,##0'
        })
        
        # --- SHEET 1: KPIs & Spend Analysis ---
        sheet1 = workbook.add_worksheet('Overview & Spend')
        sheet1.merge_range('A1:C1', 'Procurement & Purchase Dashboard Overview', title_format)
        
        # Write KPIs
        sheet1.write('A3', 'KPI Metric', sub_header_format)
        sheet1.write('B3', 'Value', sub_header_format)
        
        kpi_data = [
            ('RFQ Pending', data['kpis'].get('rfq_pending', 0)),
            ('Open PO Value (₹)', data['kpis'].get('open_po_value', 0.0)),
            ('Outstanding Liabilities (₹)', data['liabilities'].get('outstanding_amount', 0.0)),
            ('Delayed Deliveries', data['kpis'].get('delayed_deliveries', 0)),
            ('Critical Suppliers (OTD < 70%)', data['kpis'].get('critical_suppliers', 0)),
        ]
        
        row = 3
        for label, val in kpi_data:
            sheet1.write(row, 0, label, data_format)
            if isinstance(val, float):
                sheet1.write(row, 1, val, num_format)
            else:
                sheet1.write(row, 1, val, qty_format)
            row += 1
            
        # Write Monthly Spend
        row += 2
        sheet1.write(row, 0, 'Monthly Procurement Spend Analysis', sub_header_format)
        sheet1.write(row+1, 0, 'Month/Day', header_format)
        sheet1.write(row+1, 1, 'Spend (₹)', header_format)
        sheet1.write(row+1, 2, 'Savings (₹)', header_format)
        
        row += 2
        for spend_item in data['spend_analysis'].get('chart_data', []):
            sheet1.write(row, 0, spend_item.get('month'), data_format)
            sheet1.write(row, 1, spend_item.get('spend', 0.0), num_format)
            sheet1.write(row, 2, spend_item.get('saving', 0.0), num_format)
            row += 1
            
        # --- SHEET 2: Category Analysis ---
        sheet2 = workbook.add_worksheet('Category Breakdown')
        sheet2.merge_range('A1:C1', 'Category-Wise Spend Breakdown', title_format)
        sheet2.write('A3', 'Category', header_format)
        sheet2.write('B3', 'Spend Value (₹)', header_format)
        sheet2.write('C3', '% of Total Spend', header_format)
        
        row = 3
        for item in data['category_spend'].get('breakdown', []):
            sheet2.write(row, 0, item.get('category'), data_format)
            sheet2.write(row, 1, item.get('spend', 0.0), num_format)
            sheet2.write(row, 2, item.get('pct_total', 0.0) / 100.0, num_format)
            row += 1
            
        # Category Pending POs
        row += 2
        sheet2.merge_range(f'A{row+1}:F{row+1}', 'Category-Wise Pending POs List', title_format)
        row += 1
        sheet2.write(row, 0, 'Vendor', header_format)
        sheet2.write(row, 1, 'Material', header_format)
        sheet2.write(row, 2, 'Category', header_format)
        sheet2.write(row, 3, 'PO Qty', header_format)
        sheet2.write(row, 4, 'Received Qty', header_format)
        sheet2.write(row, 5, 'Pending Qty', header_format)
        
        row += 1
        for pending_item in data['category_pending_pos'].get('list', []):
            sheet2.write(row, 0, pending_item.get('vendor'), data_format)
            sheet2.write(row, 1, pending_item.get('material'), data_format)
            sheet2.write(row, 2, pending_item.get('category'), data_format)
            sheet2.write(row, 3, pending_item.get('po_qty', 0.0), qty_format)
            sheet2.write(row, 4, pending_item.get('recv_qty', 0.0), qty_format)
            sheet2.write(row, 5, pending_item.get('pending_qty', 0.0), qty_format)
            row += 1

        # --- SHEET 3: Vendor Performance & Material Risk ---
        sheet3 = workbook.add_worksheet('Vendor & Material Risk')
        sheet3.merge_range('A1:F1', 'Vendor Performance Dashboard', title_format)
        sheet3.write('A3', 'Vendor', header_format)
        sheet3.write('B3', 'Open POs', header_format)
        sheet3.write('C3', 'Pending Qty', header_format)
        sheet3.write('D3', 'On-Time Delivery %', header_format)
        sheet3.write('E3', 'Quality Rating', header_format)
        sheet3.write('F3', 'Outstanding Amount (₹)', header_format)
        
        row = 3
        for vend in data['vendor_performance'].get('list', []):
            sheet3.write(row, 0, vend.get('vendor'), data_format)
            sheet3.write(row, 1, vend.get('open_po', 0), qty_format)
            sheet3.write(row, 2, vend.get('pending_qty', 0.0), qty_format)
            sheet3.write(row, 3, vend.get('otd_pct', 0.0), num_format)
            sheet3.write(row, 4, vend.get('quality_rating', 0.0), num_format)
            sheet3.write(row, 5, vend.get('outstanding_amount', 0.0), num_format)
            row += 1
            
        # Material Availability Risk
        row += 2
        sheet3.merge_range(f'A{row+1}:E{row+1}', 'Material Availability Risk Analysis', title_format)
        row += 1
        sheet3.write(row, 0, 'Material', header_format)
        sheet3.write(row, 1, 'Current Stock', header_format)
        sheet3.write(row, 2, 'Safety Stock', header_format)
        sheet3.write(row, 3, 'Coverage (Days)', header_format)
        sheet3.write(row, 4, 'Risk Level', header_format)
        
        row += 1
        for risk in data['material_risk'].get('list', []):
            sheet3.write(row, 0, risk.get('material'), data_format)
            sheet3.write(row, 1, risk.get('current_stock', 0.0), qty_format)
            sheet3.write(row, 2, risk.get('safety_stock', 0.0), qty_format)
            sheet3.write(row, 3, risk.get('days_coverage', 0.0), num_format)
            sheet3.write(row, 4, risk.get('risk_level'), data_format)
            row += 1

        # --- SHEET 4: Aged Payables (Vendor Aging) ---
        sheet4 = workbook.add_worksheet('Aged Payables')
        sheet4.merge_range('A1:G1', 'Procurement Liability Aging Report (Aged Payables)', title_format)
        sheet4.write('A3', 'Vendor', header_format)
        sheet4.write('B3', 'Current (₹)', header_format)
        sheet4.write('C3', '0-30 Days (₹)', header_format)
        sheet4.write('D3', '31-60 Days (₹)', header_format)
        sheet4.write('E3', '61-90 Days (₹)', header_format)
        sheet4.write('F3', 'Above 90 Days (₹)', header_format)
        sheet4.write('G3', 'Total Due (₹)', header_format)

        aging_data = dashboard.get_aging_report(
            company_id=company_id,
            company_ids=parsed_company_ids,
            exclude_branches=exclude_branches,
            vendor_ids=parsed_partner_ids
        )

        row = 3
        vendors_list = aging_data.get('vendors', [])
        for v in vendors_list:
            sheet4.write(row, 0, v.get('vendor'), data_format)
            sheet4.write(row, 1, v.get('current', 0.0), num_format)
            sheet4.write(row, 2, v.get('days_0_30', 0.0), num_format)
            sheet4.write(row, 3, v.get('days_31_60', 0.0), num_format)
            sheet4.write(row, 4, v.get('days_61_90', 0.0), num_format)
            sheet4.write(row, 5, v.get('days_above_90', 0.0), num_format)
            sheet4.write(row, 6, v.get('total_due', 0.0), num_format)
            row += 1

        if vendors_list:
            sheet4.write(row, 0, 'Total', sub_header_format)
            sheet4.write(row, 1, sum(v.get('current', 0.0) for v in vendors_list), num_format)
            sheet4.write(row, 2, sum(v.get('days_0_30', 0.0) for v in vendors_list), num_format)
            sheet4.write(row, 3, sum(v.get('days_31_60', 0.0) for v in vendors_list), num_format)
            sheet4.write(row, 4, sum(v.get('days_61_90', 0.0) for v in vendors_list), num_format)
            sheet4.write(row, 5, sum(v.get('days_above_90', 0.0) for v in vendors_list), num_format)
            sheet4.write(row, 6, sum(v.get('total_due', 0.0) for v in vendors_list), num_format)

        # Adjust columns width
        for ws in [sheet1, sheet2, sheet3, sheet4]:
            ws.set_column('A:A', 25)
            ws.set_column('B:B', 20)
            ws.set_column('C:C', 20)
            ws.set_column('D:D', 20)
            ws.set_column('E:E', 20)
            ws.set_column('F:F', 20)
            if ws == sheet4:
                ws.set_column('A:A', 30)
                ws.set_column('B:G', 18)

        workbook.close()
        output.seek(0)
        
        response = request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename=purchase_dashboard_report.xlsx;')
            ]
        )
        return response

    @http.route('/purchase_dashboard/export_pc_xlsx', type='http', auth='user')
    def export_pc_xlsx(self, company_id=None, company_ids=None, category_id=None, product_ids=None, exclude_branches=None, year=None, month=None, date_from=None, date_to=None, exclude_partner_ids=None, **kwargs):
        if not company_id:
            company_id = request.env.company.id
        else:
            company_id = int(company_id)

        parsed_company_ids = []
        if company_ids:
            parsed_company_ids = [int(x) for x in company_ids.split(',') if x.strip().isdigit()]

        parsed_product_ids = []
        if product_ids:
            parsed_product_ids = [int(x) for x in product_ids.split(',') if x.strip().isdigit()]

        parsed_exclude_partner_ids = []
        if exclude_partner_ids:
            parsed_exclude_partner_ids = [int(x) for x in exclude_partner_ids.split(',') if x.strip().isdigit()]

        parsed_category_id = int(category_id) if category_id and category_id.strip().isdigit() else None

        exclude_branches = exclude_branches == 'true'

        # Fetch comparison data
        dashboard = request.env['purchase.dashboard']
        data = dashboard.get_vendor_price_comparison(
            category_id=parsed_category_id,
            product_ids=parsed_product_ids,
            company_id=company_id,
            company_ids=parsed_company_ids,
            exclude_branches=exclude_branches,
            year=year,
            month=month,
            date_from=date_from or None,
            date_to=date_to or None,
            exclude_partner_ids=parsed_exclude_partner_ids
        )

        # Create workbook
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Styling
        title_format = workbook.add_format({
            'bold': True, 'font_size': 14, 'font_name': 'Segoe UI', 'font_color': '#4F46E5', 'align': 'left'
        })
        header_format = workbook.add_format({
            'bold': True, 'font_name': 'Segoe UI', 'bg_color': '#4F46E5', 'font_color': 'white', 'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        product_header_format = workbook.add_format({
            'bold': True, 'font_name': 'Segoe UI', 'bg_color': '#4F46E5', 'font_color': 'white', 'border': 1, 'align': 'left', 'valign': 'vcenter'
        })
        data_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'left', 'valign': 'vcenter'
        })
        price_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True
        })
        best_price_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'center', 'valign': 'vcenter', 'bg_color': '#DCFCE7', 'text_wrap': True
        })
        info_label_format = workbook.add_format({
            'bold': True, 'font_name': 'Segoe UI', 'align': 'left'
        })
        info_val_format = workbook.add_format({
            'font_name': 'Segoe UI', 'align': 'left'
        })

        sheet = workbook.add_worksheet('Price Comparison')
        sheet.merge_range('A1:D1', 'Vendor Product Price Comparison', title_format)

        # Info metadata
        sheet.write('A3', 'Category:', info_label_format)
        category_name = 'All'
        if parsed_category_id:
            cat = request.env['product.category'].browse(parsed_category_id)
            if cat.exists():
                category_name = cat.complete_name or cat.name
        sheet.write('B3', category_name, info_val_format)

        sheet.write('A4', 'Date Filter:', info_label_format)
        date_filter_str = 'All'
        if date_from or date_to:
            date_filter_str = f"{date_from or ''} to {date_to or ''}"
        elif year and year != 'all':
            date_filter_str = str(year)
        sheet.write('B4', date_filter_str, info_val_format)

        # Table headers
        row_idx = 6
        sheet.write(row_idx, 0, 'Product', product_header_format)
        sheet.write(row_idx, 1, 'Best Price', header_format)
        
        vendors = data.get('vendors', [])
        col_idx = 1
        for col_idx, vendor in enumerate(vendors, start=2):
            sheet.write(row_idx, col_idx, vendor['name'], header_format)

        sheet.set_row(row_idx, 28)

        # Data rows
        row_idx += 1
        for row in data.get('rows', []):
            product_name = row['product']['name']
            min_price = row['min_price']
            
            sheet.write(row_idx, 0, product_name, data_format)
            if min_price is not None:
                sheet.write(row_idx, 1, min_price, workbook.add_format({'font_name': 'Segoe UI', 'border': 1, 'align': 'right', 'num_format': '₹#,##0.00', 'bold': True}))
            else:
                sheet.write(row_idx, 1, '-', data_format)

            for col_idx, cell in enumerate(row['cells'], start=2):
                last_bill = cell.get('last_bill')
                last_po = cell.get('last_po')
                effective = cell.get('effective_price')
                
                parts = []
                if last_bill is not None:
                    parts.append(f"Bill: ₹{last_bill:,.2f}")
                if last_po is not None:
                    parts.append(f"PO: ₹{last_po:,.2f}")
                
                cell_text = "\n".join(parts) if parts else "-"
                
                cell_fmt = price_format
                if effective is not None and effective == min_price:
                    cell_fmt = best_price_format
                
                sheet.write(row_idx, col_idx, cell_text, cell_fmt)
            
            # Wrap text row height
            sheet.set_row(row_idx, 32)
            row_idx += 1

        sheet.set_column('A:A', 35)
        sheet.set_column('B:B', 15)
        if vendors:
            sheet.set_column(2, col_idx, 20)

        workbook.close()
        output.seek(0)

        response = request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename=vendor_price_comparison_{fields.Date.today()}.xlsx;')
            ]
        )
        return response

