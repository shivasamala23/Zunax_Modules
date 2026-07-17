import sys
sys.path.append('C:\\odoo\\odoo')
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

# Initialize Odoo
odoo.tools.config.parse_config(['-c', 'C:\\odoo\\odoo\\debian\\odoo.conf'])
registry = Registry('zunax3')

with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Call the exact SQL query
    partner_ids = [24242]
    query = """
        SELECT 
            rp.id,
            rc.name AS branch_name,
            rp.global_credit_limit,
            rp.credit_limit,
            rp.bank_check_status,
            rp.property_payment_term_id
        FROM res_partner rp
        LEFT JOIN res_company rc ON rp.branch_id = rc.id
        WHERE rp.id IN %s
    """
    cr.execute(query, (tuple(partner_ids),))
    enrich_rows = cr.dictfetchall()
    print("ENRICH ROWS:", enrich_rows)
    
    for row in enrich_rows:
        pid = row['id']
        limit_val = 0.0
        if row.get('global_credit_limit'):
            limit_val = float(row['global_credit_limit'])
        elif row.get('credit_limit'):
            limit_val = float(row['credit_limit'])
        
        bcs = row.get('bank_check_status') or 'no'
        bank_check_status = 'Yes' if bcs == 'yes' else 'No'
        
        print(f"PID: {pid}, LIMIT: {limit_val}, BCS: {bank_check_status}")
