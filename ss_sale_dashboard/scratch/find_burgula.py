import sys
sys.path.append('C:\\odoo\\odoo')
import odoo
from odoo import api, SUPERUSER_ID
from odoo.modules.registry import Registry

# Initialize Odoo config
odoo.tools.config.parse_config(['-c', 'C:\\odoo\\odoo\\debian\\odoo.conf'])

# Connect to zunax_test database
registry = Registry('zunax_test')

with registry.cursor() as cr:
    env = api.Environment(cr, SUPERUSER_ID, {})
    
    # Instantiate or get the sale.dashboard model
    dashboard = env['sale.dashboard']
    
    print("Testing get_dashboard_data with Burgula (ID 2) and exclude_branches=True:")
    try:
        data = dashboard.get_dashboard_data(
            company_ids=[2],
            exclude_branches=True
        )
        print("SUCCESS! Data retrieved.")
        print("Active Company IDs in result:", data.get('company_ids'))
        print("Branch Partner IDs returned (should include more than just 35):", data.get('branch_partner_ids'))
        print("Number of branch partners:", len(data.get('branch_partner_ids', [])))
        print("Is partner 36 (Kothur) in branch partners?", 36 in data.get('branch_partner_ids', []))
        print("Is partner 37 (Ghaziabad) in branch partners?", 37 in data.get('branch_partner_ids', []))
    except Exception as e:
        print("Error calling get_dashboard_data:", e)
