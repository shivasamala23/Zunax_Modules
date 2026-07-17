# -*- coding: utf-8 -*-
import io
import json
import xlsxwriter
from odoo import http
from odoo.http import request


class InventoryDashboardController(http.Controller):

    @http.route('/inventory_dashboard/export_xlsx', type='http', auth='user')
    def export_xlsx(self, company_ids=None, warehouse_ids=None, date_from=None, date_to=None,
                    category_ids=None, product_ids=None, partner_ids=None, **kwargs):
        """Generates a high-fidelity formatted Excel workbook containing all 4 inventory reports."""
        
        # 1. Parse and extract input parameters
        parsed_company_ids = []
        if company_ids:
            parsed_company_ids = [int(x) for x in company_ids.split(',') if x.strip().isdigit()]

        parsed_warehouse_ids = []
        if warehouse_ids:
            parsed_warehouse_ids = [int(x) for x in warehouse_ids.split(',') if x.strip().isdigit()]

        parsed_category_ids = []
        if category_ids:
            parsed_category_ids = [int(x) for x in category_ids.split(',') if x.strip().isdigit()]

        parsed_product_ids = []
        if product_ids:
            parsed_product_ids = [int(x) for x in product_ids.split(',') if x.strip().isdigit()]

        parsed_partner_ids = []
        if partner_ids:
            parsed_partner_ids = [int(x) for x in partner_ids.split(',') if x.strip().isdigit()]

        # 2. Fetch the reports data from model
        dashboard_model = request.env['inventory.dashboard']
        data = dashboard_model.get_dashboard_data(
            company_ids=parsed_company_ids,
            warehouse_ids=parsed_warehouse_ids,
            date_from=date_from or None,
            date_to=date_to or None,
            category_ids=parsed_category_ids,
            product_ids=parsed_product_ids,
            partner_ids=parsed_partner_ids
        )

        reports = data.get('reports', {})

        # 3. Create the workbook and define custom formats
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Styling definitions (Premium theme matching reference photos)
        title_format = workbook.add_format({
            'bold': True, 'font_size': 12, 'font_name': 'Segoe UI', 'bg_color': '#FFFF00',
            'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        info_format = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI',
            'border': 1, 'align': 'left', 'valign': 'vcenter'
        })
        header_format = workbook.add_format({
            'bold': True, 'font_size': 10, 'font_name': 'Segoe UI', 'bg_color': '#F2F2F2',
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True
        })
        data_format = workbook.add_format({
            'font_size': 10, 'font_name': 'Segoe UI', 'border': 1, 'align': 'left', 'valign': 'vcenter'
        })
        num_format = workbook.add_format({
            'font_size': 10, 'font_name': 'Segoe UI', 'border': 1, 'align': 'right',
            'valign': 'vcenter', 'num_format': '#,##0.00'
        })
        qty_format = workbook.add_format({
            'font_size': 10, 'font_name': 'Segoe UI', 'border': 1, 'align': 'right',
            'valign': 'vcenter', 'num_format': '#,##0.00'
        })
        qty_int_format = workbook.add_format({
            'font_size': 10, 'font_name': 'Segoe UI', 'border': 1, 'align': 'right',
            'valign': 'vcenter', 'num_format': '#,##0'
        })

        # --- SHEET 1: Inventory Status Report ---
        sheet1 = workbook.add_worksheet('Inventory Status')
        sheet1.set_column('A:A', 15)
        sheet1.set_column('B:B', 35)
        sheet1.set_column('C:J', 15)

        # Title Block
        sheet1.merge_range('A1:J1', 'Inventory Status Report', title_format)
        sheet1.set_row(0, 24)

        # Unit & Date Info
        company_names = ", ".join(request.env['res.company'].browse(data['filters']['company_ids']).mapped('name'))
        sheet1.write('A2', f"Unit: {company_names}", info_format)
        sheet1.merge_range('B2:J2', f"From {data['filters']['date_from']} To {data['filters']['date_to']}", info_format)
        sheet1.set_row(1, 20)

        # Columns Headers
        headers1 = [
            'Item Code', 'Item Description', 'Opening Qty', 'Opening Value',
            'Receipt Qty', 'Receipt Value', 'Issue Qty', 'Issue Value',
            'Closing Qty', 'Closing Value'
        ]
        for col_idx, text in enumerate(headers1):
            sheet1.write(2, col_idx, text, header_format)
        sheet1.set_row(2, 22)

        # Data rows
        row_idx = 3
        for item in reports.get('inventory_status', []):
            sheet1.write(row_idx, 0, item.get('item_code') or 'N/A', data_format)
            sheet1.write(row_idx, 1, item.get('item_name') or '', data_format)
            sheet1.write(row_idx, 2, item.get('opening_qty', 0.0), qty_format)
            sheet1.write(row_idx, 3, item.get('opening_val', 0.0), num_format)
            sheet1.write(row_idx, 4, item.get('receipt_qty', 0.0), qty_format)
            sheet1.write(row_idx, 5, item.get('receipt_val', 0.0), num_format)
            sheet1.write(row_idx, 6, item.get('issue_qty', 0.0), qty_format)
            sheet1.write(row_idx, 7, item.get('issue_val', 0.0), num_format)
            sheet1.write(row_idx, 8, item.get('closing_qty', 0.0), qty_format)
            sheet1.write(row_idx, 9, item.get('closing_val', 0.0), num_format)
            sheet1.set_row(row_idx, 18)
            row_idx += 1

        # --- SHEET 2: Stock Ledger Report ---
        sheet2 = workbook.add_worksheet('Stock Ledger')
        sheet2.set_column('A:A', 15)
        sheet2.set_column('B:B', 35)
        sheet2.set_column('C:C', 20)
        sheet2.set_column('D:E', 25)
        sheet2.set_column('F:J', 15)

        # Title Block
        sheet2.merge_range('A1:J1', 'Stock Ledger Report (supplier wise/item wise)', title_format)
        sheet2.set_row(0, 24)

        sheet2.write('A2', f"Unit: {company_names}", info_format)
        sheet2.merge_range('B2:J2', f"From {data['filters']['date_from']} To {data['filters']['date_to']}", info_format)
        sheet2.set_row(1, 20)

        # Headers
        headers2 = [
            'Item Code', 'Item Description', 'Reference', 'Partner', 'Lot/Serial Number', 'Opening Qty',
            'Receipt Qty', 'Issue Qty', 'Closing Qty', 'Value'
        ]
        for col_idx, text in enumerate(headers2):
            sheet2.write(2, col_idx, text, header_format)
        sheet2.set_row(2, 22)

        row_idx = 3
        for item in reports.get('stock_ledger', []):
            sheet2.write(row_idx, 0, item.get('item_code') or 'N/A', data_format)
            sheet2.write(row_idx, 1, item.get('item_name') or '', data_format)
            sheet2.write(row_idx, 2, item.get('reference') or '', data_format)
            sheet2.write(row_idx, 3, item.get('partner') or '', data_format)
            sheet2.write(row_idx, 4, item.get('lot_name') or '', data_format)
            sheet2.write(row_idx, 5, item.get('opening_qty', 0.0), qty_format)
            sheet2.write(row_idx, 6, item.get('receipt_qty', 0.0), qty_format)
            sheet2.write(row_idx, 7, item.get('issue_qty', 0.0), qty_format)
            sheet2.write(row_idx, 8, item.get('closing_qty', 0.0), qty_format)
            sheet2.write(row_idx, 9, item.get('value', 0.0), num_format)
            sheet2.set_row(row_idx, 18)
            row_idx += 1

        # --- SHEET 3: Ageing Analysis ---
        sheet3 = workbook.add_worksheet('Ageing Analysis')
        sheet3.set_column('A:A', 15)
        sheet3.set_column('B:B', 35)
        sheet3.set_column('C:T', 11)

        # Title Block
        sheet3.merge_range('A1:T1', 'Ageing Analysis', title_format)
        sheet3.set_row(0, 24)

        sheet3.write('A2', f"Unit: {company_names}", info_format)
        sheet3.merge_range('B2:T2', f"As on {data['filters']['date_to']}", info_format)
        sheet3.set_row(1, 20)

        # Multi-row Headers
        # Row 1 (Header titles)
        sheet3.merge_range('A3:A4', 'Item Code', header_format)
        sheet3.merge_range('B3:B4', 'Item Description', header_format)
        sheet3.merge_range('C3:D3', 'Total', header_format)
        sheet3.merge_range('E3:F3', '30 Days', header_format)
        sheet3.merge_range('G3:H3', '60 Days', header_format)
        sheet3.merge_range('I3:J3', '90 Days', header_format)
        sheet3.merge_range('K3:L3', '120 Days', header_format)
        sheet3.merge_range('M3:N3', '150 Days', header_format)
        sheet3.merge_range('O3:P3', '180 Days', header_format)
        sheet3.merge_range('Q3:R3', '360 Days', header_format)
        sheet3.merge_range('S3:T3', 'Above 360 Days', header_format)
        sheet3.set_row(2, 20)

        # Row 2 (Qty, Value labels)
        for i in range(2, 20, 2):
            sheet3.write(3, i, 'Qty', header_format)
            sheet3.write(3, i+1, 'Value', header_format)
        sheet3.set_row(3, 20)

        row_idx = 4
        for item in reports.get('ageing_analysis', []):
            sheet3.write(row_idx, 0, item.get('item_code') or 'N/A', data_format)
            sheet3.write(row_idx, 1, item.get('item_name') or '', data_format)
            
            sheet3.write(row_idx, 2, item.get('total_qty', 0.0), qty_format)
            sheet3.write(row_idx, 3, item.get('total_val', 0.0), num_format)
            
            sheet3.write(row_idx, 4, item.get('qty_30', 0.0), qty_format)
            sheet3.write(row_idx, 5, item.get('val_30', 0.0), num_format)
            
            sheet3.write(row_idx, 6, item.get('qty_60', 0.0), qty_format)
            sheet3.write(row_idx, 7, item.get('val_60', 0.0), num_format)
            
            sheet3.write(row_idx, 8, item.get('qty_90', 0.0), qty_format)
            sheet3.write(row_idx, 9, item.get('val_90', 0.0), num_format)
            
            sheet3.write(row_idx, 10, item.get('qty_120', 0.0), qty_format)
            sheet3.write(row_idx, 11, item.get('val_120', 0.0), num_format)
            
            sheet3.write(row_idx, 12, item.get('qty_150', 0.0), qty_format)
            sheet3.write(row_idx, 13, item.get('val_150', 0.0), num_format)
            
            sheet3.write(row_idx, 14, item.get('qty_180', 0.0), qty_format)
            sheet3.write(row_idx, 15, item.get('val_180', 0.0), num_format)
            
            sheet3.write(row_idx, 16, item.get('qty_360', 0.0), qty_format)
            sheet3.write(row_idx, 17, item.get('val_360', 0.0), num_format)
            
            sheet3.write(row_idx, 18, item.get('qty_above', 0.0), qty_format)
            sheet3.write(row_idx, 19, item.get('val_above', 0.0), num_format)
            
            sheet3.set_row(row_idx, 18)
            row_idx += 1

        # --- SHEET 4: Pending PO Status ---
        sheet4 = workbook.add_worksheet('Pending POs')
        sheet4.set_column('A:A', 15)
        sheet4.set_column('B:B', 25)
        sheet4.set_column('C:C', 35)
        sheet4.set_column('D:E', 15)

        # Title Block
        sheet4.merge_range('A1:E1', 'Pending Purchase Order Status Report (supplier wise/item wise)', title_format)
        sheet4.set_row(0, 24)

        sheet4.write('A2', f"Unit: {company_names}", info_format)
        sheet4.merge_range('B2:E2', f"From {data['filters']['date_from']} To {data['filters']['date_to']}", info_format)
        sheet4.set_row(1, 20)

        # Headers
        headers4 = [
            'Item Code', 'Supplier/Vendor Name', 'Item Description', 'PO Qty', 'Balance PO Qty'
        ]
        for col_idx, text in enumerate(headers4):
            sheet4.write(2, col_idx, text, header_format)
        sheet4.set_row(2, 22)

        row_idx = 3
        for item in reports.get('pending_po', []):
            sheet4.write(row_idx, 0, item.get('item_code') or 'N/A', data_format)
            sheet4.write(row_idx, 1, item.get('partner_name') or '', data_format)
            sheet4.write(row_idx, 2, item.get('item_description') or '', data_format)
            sheet4.write(row_idx, 3, item.get('po_qty', 0.0), qty_int_format)
            sheet4.write(row_idx, 4, item.get('balance_po_qty', 0.0), qty_int_format)
            sheet4.set_row(row_idx, 18)
            row_idx += 1

        workbook.close()
        output.seek(0)

        # Response headers
        response = http.request.make_response(
            output.getvalue(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename=inventory_report_dashboard.xlsx;')
            ]
        )
        return response
