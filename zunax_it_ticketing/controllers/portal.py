# -*- coding: utf-8 -*-

from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
import logging

_logger = logging.getLogger(__name__)

class ITSupportPortal(CustomerPortal):

    def _prepare_portal_layout_values(self):
        """Add ticket count to the portal dashboard"""
        values = super(ITSupportPortal, self)._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        # Safely count tickets using sudo for multi-company portal users
        ticket_count = request.env['it.ticket'].sudo().search_count([
            ('partner_id', '=', partner.id)
        ])
        values['it_ticket_count'] = ticket_count
        return values

    def _prepare_home_portal_values(self, counters):
        """Odoo 18.0 portal dashboard dynamic counters"""
        values = super(ITSupportPortal, self)._prepare_home_portal_values(counters)
        if 'it_ticket_count' in counters:
            partner = request.env.user.partner_id
            values['it_ticket_count'] = request.env['it.ticket'].sudo().search_count([
                ('partner_id', '=', partner.id)
            ])
        return values

    @http.route(['/my/tickets', '/my/tickets/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_it_tickets(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        """Render the list of tickets in the employee's portal view"""
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        ItTicket = request.env['it.ticket'].sudo()
        
        domain = [('partner_id', '=', partner.id)]
        
        # Count for pager
        ticket_count = ItTicket.search_count(domain)
        pager = portal_pager(
            url="/my/tickets",
            total=ticket_count,
            page=page,
            step=10
        )
        
        # Fetch tickets
        tickets = ItTicket.search(domain, limit=10, offset=pager['offset'])
        
        values.update({
            'tickets': tickets,
            'page_name': 'it_ticket',
            'pager': pager,
            'default_url': '/my/tickets',
        })
        return request.render("zunax_it_ticketing.portal_my_tickets", values)

    @http.route(['/my/ticket/<int:ticket_id>'], type='http', auth="user", website=True)
    def portal_my_it_ticket_detail(self, ticket_id, **kw):
        """Render the detailed view of a single ticket in the portal, with chatter support"""
        try:
            # Leverage Odoo security rules; search will fail if the user is not allowed to access this ticket
            ticket = request.env['it.ticket'].sudo().search([('id', '=', ticket_id)], limit=1)
        except Exception:
            return request.redirect('/my/tickets')
            
        if not ticket:
            return request.redirect('/my/tickets')
            
        values = {
            'ticket': ticket,
            'page_name': 'it_ticket',
        }
        return request.render("zunax_it_ticketing.portal_my_ticket_detail", values)

    # Public route to raise tickets (Accessible on the local company network / Intranet)
    @http.route('/raise-ticket', type='http', auth='public', website=True, csrf=True)
    def raise_ticket_form(self, **kw):
        """Render a clean public-facing form for raising tickets"""
        departments = request.env['it.department'].sudo().search([])
        # Prepopulate email/name if user is logged in
        user = request.env.user
        values = {
            'departments': departments,
            'default_email': user.email if not user._is_public() else '',
            'default_name': user.name if not user._is_public() else '',
        }
        return request.render("zunax_it_ticketing.raise_ticket_public_form", values)

    @http.route('/raise-ticket/submit', type='http', auth='public', methods=['POST'], website=True, csrf=True)
    def raise_ticket_submit(self, **post):
        """Handle the public form submission, find/create the partner, and route the ticket"""
        email = post.get('email', '').strip()
        name = post.get('name', '').strip()
        subject = post.get('subject', '').strip()
        dept_id = int(post.get('department_id', 0))
        description = post.get('description', '').strip()
        phone = post.get('phone', '').strip()

        if not email or not subject or not dept_id:
            return request.render("zunax_it_ticketing.raise_ticket_public_form", {
                'error': _('Please fill in all required fields (Email, Subject, Department).'),
                'departments': request.env['it.department'].sudo().search([]),
                'post': post
            })

        # Match employee or partner based on email using recordset sudo() directly
        employee = request.env['hr.employee'].sudo().search([('work_email', '=ilike', email)], limit=1)
        partner = False
        
        if employee:
            partner = employee.user_partner_id or getattr(employee, 'work_contact_id', False)
        
        if not partner:
            partner = request.env['res.partner'].sudo().search([('email', '=ilike', email)], limit=1)
            
        if not partner:
            # Create a contact record for tracking discussions if it is a new employee/external partner
            partner = request.env['res.partner'].sudo().create({
                'name': name or email.split('@')[0],
                'email': email,
                'mobile': phone,
                'type': 'contact',
            })

        # Create the ticket record
        ticket_vals = {
            'name': subject,
            'partner_id': partner.id,
            'employee_id': employee.id if employee else False,
            'email': email,
            'phone': phone or (employee.mobile_phone if employee else ''),
            'department_id': dept_id,
            'description': f"<p>{description}</p>" if description else "",
            'stage': 'new',
        }
        
        new_ticket = request.env['it.ticket'].sudo().create(ticket_vals)

        # Log a chatter message notifying of creation via webform
        new_ticket.message_post(
            body=_("Ticket raised via Web Form from IP Address: %s") % request.httprequest.remote_addr,
            message_type='notification',
            subtype_xmlid='mail.mt_note'
        )

        return request.render("zunax_it_ticketing.raise_ticket_thankyou", {
            'ticket_number': new_ticket.ticket_number,
            'subject': new_ticket.name,
        })
