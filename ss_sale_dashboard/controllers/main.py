# -*- coding: utf-8 -*-
import io
import xlsxwriter
from odoo import http, fields
from odoo.http import request

class SaleDashboardController(http.Controller):
    @http.route('/sale_dashboard/export_xlsx', type='http', auth='user')
    def export_xlsx(self, company_id=None, company_ids=None, year=None, month=None, date_from=None, date_to=None, **kwargs):
        if not company_id:
            company_id = request.env.company.id
        else:
            company_id = int(company_id)

        parsed_company_ids = []
        if company_ids:
            parsed_company_ids = [int(x) for x in company_ids.split(',') if x.strip().isdigit()]

        exclude_branches = kwargs.get('exclude_branches') == 'true'
        partner_id = kwargs.get('partner_id')
        partner_id_val = int(partner_id) if (partner_id and str(partner_id).isdigit()) else None
        partner_ids = kwargs.get('partner_ids')
        partner_ids_list = [int(x) for x in partner_ids.split(',') if x.strip().isdigit()] if partner_ids else None

        tds_filter = kwargs.get('tds_filter', 'without_tds')

        categ_id = kwargs.get('categ_id')
        categ_id_val = int(categ_id) if (categ_id and str(categ_id).isdigit()) else None
        categ_ids = kwargs.get('categ_ids')
        categ_ids_list = [int(x) for x in categ_ids.split(',') if x.strip().isdigit()] if categ_ids else None

        # Fetch dashboard data
        dashboard = request.env['sale.dashboard']
        data = dashboard.get_dashboard_data(
            company_id=company_id,
            company_ids=parsed_company_ids,
            year=year,
            month=month,
            date_from=date_from or None,
            date_to=date_to or None,
            exclude_branches=exclude_branches,
            partner_id=partner_id_val,
            partner_ids=partner_ids_list,
            tds_filter=tds_filter,
            categ_id=categ_id_val,
            categ_ids=categ_ids_list
        )

        # Create workbook
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        
        # Styles
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
        pct_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'right', 'num_format': '0.0%'
        })
        qty_format = workbook.add_format({
            'font_name': 'Segoe UI', 'border': 1, 'align': 'right', 'num_format': '#,##0'
        })
        
        # --- SHEET 1: KPIs & Trend ---
        sheet1 = workbook.add_worksheet('Overview')
        sheet1.merge_range('A1:C1', 'Sales & Collection Dashboard Overview', title_format)
        
        # Write KPIs
        sheet1.write('A3', 'KPI Metric', sub_header_format)
        sheet1.write('B3', 'Value', sub_header_format)
        
        kpi_data = [
            ('Sales (₹)', data['kpis'].get('sales', 0.0)),
            ('Monthly Sales Target (₹)', data['kpis'].get('target', 0.0)),
            ('Target Achievement (%)', data['kpis'].get('achievement_pct', 0.0) / 100.0),
            ('Collection (₹)', data['kpis'].get('collection', 0.0)),
            ('Total Outstanding (₹)', data['kpis'].get('outstanding', 0.0)),
            ('Overdue Outstanding (₹)', data['kpis'].get('overdue_outstanding', 0.0)),
            ('Partner Bank Received (₹)', data['kpis'].get('bank_partner_received', 0.0)),
            ('Bank Transfers Received (₹)', data['kpis'].get('bank_received', 0.0)),
            ('Reconciled Bank Amount (₹)', data['kpis'].get('bank_reconciled', 0.0)),
            ('Suspense Account Amount (₹)', data['kpis'].get('bank_suspense', 0.0)),
            ('Bank Reconciliation (%)', data['kpis'].get('bank_reconciled_pct', 0.0) / 100.0),
        ]
        
        row = 3
        for label, val in kpi_data:
            sheet1.write(row, 0, label, data_format)
            if 'Percentage' in label or '%' in label:
                sheet1.write(row, 1, val, pct_format)
            else:
                sheet1.write(row, 1, val, num_format)
            row += 1
            
        # Write Trend Analysis
        row += 2
        sheet1.write(row, 0, 'Monthly Sales Trend', sub_header_format)
        sheet1.write(row+1, 0, 'Month', header_format)
        sheet1.write(row+1, 1, 'Sales Value (₹)', header_format)
        
        row += 2
        for trend in data.get('trend_sales', []):
            sheet1.write(row, 0, trend.get('month'), data_format)
            sheet1.write(row, 1, trend.get('amount', 0.0), num_format)
            row += 1
            
        # --- SHEET 2: Region & Product Analysis ---
        sheet2 = workbook.add_worksheet('Breakdowns')
        sheet2.merge_range('A1:B1', 'Region-Wise Sales', title_format)
        sheet2.write('A3', 'Region', header_format)
        sheet2.write('B3', 'Sales (₹)', header_format)
        
        row = 3
        for region in data.get('region_sales', []):
            sheet2.write(row, 0, region.get('region'), data_format)
            sheet2.write(row, 1, region.get('amount', 0.0), num_format)
            row += 1
            
        # Product Sales
        row += 2
        sheet2.merge_range(f'D1:F1', 'Product-Wise Sales (Top 10)', title_format)
        sheet2.write('D3', 'Product', header_format)
        sheet2.write('E3', 'Qty Sold', header_format)
        sheet2.write('F3', 'Sales Amount (₹)', header_format)
        
        p_row = 3
        for prod in data.get('product_sales', []):
            sheet2.write(p_row, 3, prod.get('product'), data_format)
            sheet2.write(p_row, 4, prod.get('qty', 0.0), qty_format)
            sheet2.write(p_row, 5, prod.get('amount', 0.0), num_format)
            p_row += 1
            
        # Segment Sales
        sheet2.merge_range('H1:I1', 'Segment-Wise Sales', title_format)
        sheet2.write('H3', 'Segment', header_format)
        sheet2.write('I3', 'Sales Amount (₹)', header_format)
        s_row = 3
        for seg in data.get('segment_sales', []):
            sheet2.write(s_row, 7, seg.get('segment'), data_format)
            sheet2.write(s_row, 8, seg.get('amount', 0.0), num_format)
            s_row += 1

        # Product Segment Sales (Excel style)
        sheet2.merge_range('K1:L1', 'Product Segment-Wise Sales', title_format)
        sheet2.write('K3', 'Segment', header_format)
        sheet2.write('L3', 'Sales Amount (₹)', header_format)
        ps_row = 3
        for seg in data.get('product_segment_sales', []):
            sheet2.write(ps_row, 10, seg.get('segment'), data_format)
            sheet2.write(ps_row, 11, seg.get('amount', 0.0), num_format)
            ps_row += 1

        # Category Sales
        sheet2.merge_range('N1:O1', 'Category-Wise Sales (Top 10)', title_format)
        sheet2.write('N3', 'Category', header_format)
        sheet2.write('O3', 'Sales Amount (₹)', header_format)
        c_row = 3
        for cat in data.get('category_sales', []):
            sheet2.write(c_row, 13, cat.get('category'), data_format)
            sheet2.write(c_row, 14, cat.get('amount', 0.0), num_format)
            c_row += 1
            
        # --- SHEET 3: Overdue Invoices ---
        sheet3 = workbook.add_worksheet('Overdue Invoices')
        sheet3.merge_range('A1:D1', 'Overdue Outstanding Invoices by Customer', title_format)
        
        headers = ['Customer', 'Invoice Count', 'Total Invoice Amount (₹)', 'Total Overdue Outstanding (₹)']
        for col, h in enumerate(headers):
            sheet3.write(2, col, h, header_format)
            
        row = 3
        for inv in data.get('overdue_list', []):
            sheet3.write(row, 0, inv.get('customer'), data_format)
            sheet3.write(row, 1, inv.get('invoice_count', 0), data_format)
            sheet3.write(row, 2, inv.get('amount_total', 0.0), num_format)
            sheet3.write(row, 3, inv.get('amount_residual', 0.0), num_format)
            row += 1

        # Set column widths
        sheet1.set_column('A:A', 30)
        sheet1.set_column('B:B', 20)
        sheet2.set_column('A:A', 25)
        sheet2.set_column('B:B', 20)
        sheet2.set_column('D:D', 35)
        sheet2.set_column('E:F', 20)
        sheet2.set_column('H:H', 25)
        sheet2.set_column('I:I', 20)
        sheet2.set_column('K:K', 25)
        sheet2.set_column('L:L', 20)
        sheet2.set_column('N:N', 25)
        sheet2.set_column('O:O', 20)
        sheet3.set_column('A:A', 30)
        sheet3.set_column('B:B', 15)
        sheet3.set_column('C:D', 25)

        workbook.close()
        output.seek(0)
        
        response = http.request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename=sales_collection_dashboard.xlsx;')
            ]
        )
        return response

    @http.route('/sale_dashboard/export_segment_xlsx', type='http', auth='user')
    def export_segment_xlsx(self, company_id=None, company_ids=None, year=None, compare_year=None, **kwargs):
        if not company_id:
            company_id = request.env.company.id
        else:
            company_id = int(company_id)

        parsed_company_ids = []
        if company_ids:
            parsed_company_ids = [int(x) for x in company_ids.split(',') if x.strip().isdigit()]

        exclude_branches = kwargs.get('exclude_branches') == 'true'

        # Get segment dashboard data
        dashboard = request.env['sale.dashboard']
        res = dashboard.export_segment_performance_excel(
            company_id=company_id,
            company_ids=parsed_company_ids,
            year=year,
            compare_year=compare_year,
            exclude_branches=exclude_branches
        )
        
        import base64
        file_content = base64.b64decode(res)

        response = http.request.make_response(
            file_content,
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', f'attachment; filename="product_segment_performance_{year}_vs_{compare_year}.xlsx"')
            ]
        )
        return response
