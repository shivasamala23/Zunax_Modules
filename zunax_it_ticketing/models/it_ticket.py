# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class ItTicket(models.Model):
    _name = 'it.ticket'
    _description = 'IT Support Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Subject', required=True, tracking=True)
    ticket_number = fields.Char(
        string='Ticket Number',
        readonly=True,
        copy=False,
        default=lambda self: _('New'),
        tracking=True
    )
    
    subject_id = fields.Many2one(
        'it.ticket.subject',
        string='Subject Selection',
        tracking=True,
        help='Select a predefined subject for your IT request'
    )
    
    @api.model
    def _default_employee_id(self):
        return self.env['hr.employee.public'].sudo().search([('user_id', '=', self.env.uid)], limit=1)

    employee_id = fields.Many2one(
        'hr.employee.public',
        string='Employee',
        default=_default_employee_id,
        tracking=True,
        help='The employee raising the ticket'
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Contact/Partner',
        tracking=True,
        help='The partner/contact associated with the ticket (used for communications)'
    )
    
    email = fields.Char(string='Email', tracking=True)
    phone = fields.Char(string='Mobile/Phone', tracking=True)
    
    department_id = fields.Many2one(
        'it.department',
        string='IT Department',
        required=True,
        tracking=True,
        help='The support department responsible for this issue'
    )
    
    assigned_user_id = fields.Many2one(
        'res.users',
        string='Assigned To',
        tracking=True,
        domain="[('share', '=', False)]",
        help='The support team member assigned to resolve this ticket'
    )
    
    is_support_staff = fields.Boolean(
        compute='_compute_is_support_staff',
        string='Is Support Staff'
    )
    
    priority = fields.Selection([
        ('0', 'Low'),
        ('1', 'Medium'),
        ('2', 'High'),
        ('3', 'Urgent')
    ], string='Priority', default='1', tracking=True)
    
    stage = fields.Selection([
        ('draft', 'Draft'),
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('resolved', 'Resolved'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    description = fields.Html(string='Issue Description')
    resolution_notes = fields.Html(
        string='Resolution Notes',
        help='Add comments explaining how the issue was resolved'
    )
    
    cancellation_reason = fields.Text(
        string='Cancellation Reason',
        tracking=True,
        help='Reason for cancelling the ticket'
    )

    date_resolved = fields.Datetime(
        string='Resolution Date',
        readonly=True,
        tracking=True
    )
    
    resolution_time = fields.Float(
        string='Resolution Time (Hours)',
        compute='_compute_resolution_time',
        store=True,
        group_operator='avg',
        help='Average time in hours taken to resolve this ticket'
    )

    def _compute_is_support_staff(self):
        is_staff = self.env.user.has_group('zunax_it_ticketing.group_it_support_staff')
        for record in self:
            record.is_support_staff = is_staff

    @api.depends('create_date', 'date_resolved')
    def _compute_resolution_time(self):
        for record in self:
            if record.create_date and record.date_resolved:
                diff = record.date_resolved - record.create_date
                record.resolution_time = diff.total_seconds() / 3600.0
            else:
                record.resolution_time = 0.0

    @api.model
    def default_get(self, fields_list):
        res = super(ItTicket, self).default_get(fields_list)
        if 'employee_id' in fields_list and res.get('employee_id'):
            employee = self.env['hr.employee.public'].sudo().browse(res['employee_id'])
            partner = employee.user_partner_id
            if not partner and hasattr(employee, 'work_contact_id'):
                partner = getattr(employee, 'work_contact_id')
            if not partner and employee.work_email:
                partner = self.env['res.partner'].sudo().search([('email', '=', employee.work_email)], limit=1)
            
            if not partner:
                partner = self.env['res.partner'].sudo().create({
                    'name': employee.name,
                    'email': employee.work_email,
                    'mobile': employee.mobile_phone or employee.work_phone,
                    'type': 'contact',
                })
            
            if 'partner_id' in fields_list:
                res['partner_id'] = partner.id
            if 'email' in fields_list:
                res['email'] = employee.work_email
            if 'phone' in fields_list:
                res['phone'] = employee.mobile_phone or employee.work_phone

        # Pre-populate Default Assigned User from clicked Department Board context
        if 'department_id' in fields_list and res.get('department_id') and 'assigned_user_id' in fields_list and not res.get('assigned_user_id'):
            dept = self.env['it.department'].sudo().browse(res['department_id'])
            if dept.assigned_employee_id and dept.assigned_employee_id.sudo().user_id:
                res['assigned_user_id'] = dept.assigned_employee_id.sudo().user_id.id
        return res

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        """Auto-populate contact, email, and phone when employee is selected"""
        if self.employee_id:
            employee = self.employee_id.sudo()
            partner = employee.user_partner_id
            if not partner and hasattr(employee, 'work_contact_id'):
                partner = getattr(employee, 'work_contact_id')
            
            if not partner and employee.work_email:
                partner = self.env['res.partner'].sudo().search([('email', '=', employee.work_email)], limit=1)
            
            if not partner:
                partner = self.env['res.partner'].sudo().create({
                    'name': employee.name,
                    'email': employee.work_email,
                    'mobile': employee.mobile_phone or employee.work_phone,
                    'type': 'contact',
                })
            
            self.partner_id = partner
            self.email = employee.work_email
            self.phone = employee.mobile_phone or employee.work_phone

    @api.onchange('subject_id')
    def _onchange_subject_id(self):
        """Update ticket name and department when predefined subject is selected"""
        if self.subject_id:
            self.name = self.subject_id.name
            if self.subject_id.department_id:
                self.department_id = self.subject_id.department_id

    @api.onchange('department_id')
    def _onchange_department_id(self):
        """Auto-populate default assigned user when department is changed in form view"""
        if self.department_id:
            dept = self.department_id.sudo()
            if dept.assigned_employee_id and dept.assigned_employee_id.sudo().user_id:
                self.assigned_user_id = dept.assigned_employee_id.sudo().user_id

    @api.model
    def _get_auto_assigned_user_id(self, dept):
        """Determine assigned user for department using priority: Default Employee -> Least Loaded Member -> Manager"""
        if not dept:
            return False
        dept = dept.sudo()
        if dept.assigned_employee_id and dept.assigned_employee_id.sudo().user_id:
            return dept.assigned_employee_id.sudo().user_id.id
        elif dept.member_ids:
            active_tickets = self.env['it.ticket'].sudo().read_group(
                [('assigned_user_id', 'in', dept.member_ids.ids), ('stage', 'in', ['new', 'in_progress'])],
                ['assigned_user_id'], ['assigned_user_id']
            )
            ticket_counts = {t['assigned_user_id'][0]: t['assigned_user_id_count'] for t in active_tickets if t['assigned_user_id']}
            for member in dept.member_ids:
                if member.id not in ticket_counts:
                    ticket_counts[member.id] = 0
            return min(ticket_counts, key=ticket_counts.get)
        elif dept.manager_id:
            return dept.manager_id.id
        return False

    def action_submit(self):
        """Submit the ticket: generate sequence number and perform auto-routing assignment"""
        self.ensure_one()
        if self.stage != 'draft':
            return
            
        vals = {
            'stage': 'new',
        }
        if self.ticket_number == _('New') or not self.ticket_number:
            vals['ticket_number'] = self.env['ir.sequence'].next_by_code('it.ticket.sequence') or _('New')
            
        # Perform routing if not already assigned
        if not self.assigned_user_id and self.department_id:
            auto_user_id = self._get_auto_assigned_user_id(self.department_id)
            if auto_user_id:
                vals['assigned_user_id'] = auto_user_id
                
        self.write(vals)
        self._notify_staff_on_creation()

    def action_start_progress(self):
        self.ensure_one()
        self.write({'stage': 'in_progress'})

    def action_resolve(self):
        self.ensure_one()
        if not self.resolution_notes:
            raise ValidationError(_("Please provide resolution notes before resolving this ticket."))
        self.write({'stage': 'resolved'})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 0. Populate ticket name and department from subject if present
            if vals.get('subject_id'):
                subject = self.env['it.ticket.subject'].sudo().browse(vals['subject_id'])
                if not vals.get('name'):
                    vals['name'] = subject.name
                if not vals.get('department_id') and subject.department_id:
                    vals['department_id'] = subject.department_id.id

            # If stage is set to 'new' directly (e.g. from portal/incoming email), we generate sequence and route
            if vals.get('stage', 'draft') == 'new':
                if vals.get('ticket_number', _('New')) == _('New'):
                    vals['ticket_number'] = self.env['ir.sequence'].next_by_code('it.ticket.sequence') or _('New')
                
                # Automatic routing to default assignee or least loaded member of selected department
                if vals.get('department_id') and not vals.get('assigned_user_id'):
                    dept = self.env['it.department'].sudo().browse(vals['department_id'])
                    auto_user_id = self._get_auto_assigned_user_id(dept)
                    if auto_user_id:
                        vals['assigned_user_id'] = auto_user_id

            # If stage is resolved directly on create
            if vals.get('stage') == 'resolved':
                vals['date_resolved'] = fields.Datetime.now()

            # Fallback/Sudo to resolve initial creation partner info
            if vals.get('employee_id') and not vals.get('partner_id'):
                employee = self.env['hr.employee.public'].sudo().browse(vals['employee_id'])
                partner = employee.user_partner_id
                if not partner and hasattr(employee, 'work_contact_id'):
                    partner = getattr(employee, 'work_contact_id')
                if not partner and employee.work_email:
                    partner = self.env['res.partner'].sudo().search([('email', '=', employee.work_email)], limit=1)
                if not partner:
                    partner = self.env['res.partner'].sudo().create({
                        'name': employee.name,
                        'email': employee.work_email,
                        'mobile': employee.mobile_phone or employee.work_phone,
                    })
                vals['partner_id'] = partner.id
                vals['email'] = employee.work_email
                vals['phone'] = employee.mobile_phone or employee.work_phone

        tickets = super(ItTicket, self).create(vals_list)
        
        # Send alert emails to Support Staff and Managers for non-draft tickets
        for ticket in tickets:
            if ticket.stage == 'new':
                ticket._notify_staff_on_creation()
            
        return tickets

    def write(self, vals):
        # 1. Enforce access restrictions based on user groups
        is_support_staff = self.env.user.has_group('zunax_it_ticketing.group_it_support_staff')
        is_manager = self.env.user.has_group('zunax_it_ticketing.group_it_support_manager')
        is_admin = self.env.su or self.env.user._is_admin()
        
        # User (End User) Check:
        if not (is_support_staff or is_manager or is_admin):
            for record in self:
                # Standard users cannot modify anything on submitted tickets except cancelling with a reason
                if record.stage != 'draft':
                    modified_fields = set(vals.keys())
                    allowed_fields = {'stage', 'cancellation_reason'}
                    if not modified_fields.issubset(allowed_fields):
                        raise ValidationError(_("As a standard user, you cannot modify a ticket once it has been submitted. You can only cancel it using the Cancel wizard."))
                    if 'stage' in vals:
                        if vals['stage'] != 'cancelled':
                            raise ValidationError(_("As a standard user, you can only change the status of this ticket to 'Cancelled'."))
                        if not vals.get('cancellation_reason') and not record.cancellation_reason:
                            raise ValidationError(_("You must provide a cancellation reason to cancel this ticket."))

        # Support Staff Check:
        if is_support_staff and not (is_manager or is_admin):
            if 'stage' in vals and vals['stage'] == 'cancelled':
                raise ValidationError(_("Support staff members are not allowed to cancel tickets. Only the manager or the raising employee can cancel a ticket."))

        # Manage resolution timestamp
        if 'stage' in vals:
            if vals['stage'] == 'resolved':
                vals['date_resolved'] = fields.Datetime.now()
            else:
                vals['date_resolved'] = False

        # 2. Track original stage for transitions
        stage_before = {record.id: record.stage for record in self}
        res = super(ItTicket, self).write(vals)
        
        # 3. Check if the stage has transitioned to resolved
        if 'stage' in vals and vals['stage'] == 'resolved':
            for record in self:
                if stage_before.get(record.id) != 'resolved':
                    # Send Email and WhatsApp notifications on resolution
                    record._send_resolution_email()
                    record._send_resolution_whatsapp()
        return res

    def _get_staff_manager_emails(self):
        """Get a comma-separated list of emails of all users in Support Staff and Manager groups"""
        group_staff = self.env.ref('zunax_it_ticketing.group_it_support_staff', raise_if_not_found=False).sudo()
        group_manager = self.env.ref('zunax_it_ticketing.group_it_support_manager', raise_if_not_found=False).sudo()
        emails = []
        if group_staff:
            emails.extend(group_staff.users.mapped('email'))
        if group_manager:
            emails.extend(group_manager.users.mapped('email'))
        # Filter out empty emails and duplicates
        unique_emails = list(set(filter(None, emails)))
        return ",".join(unique_emails)

    def _notify_staff_on_creation(self):
        """Send notification email to support staff and manager groups upon ticket creation"""
        self.ensure_one()
        template = self.env.ref('zunax_it_ticketing.email_template_ticket_created_staff', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
            _logger.info("IT Ticket creation alert sent to support staff/managers for ticket: %s", self.ticket_number)

    def _send_resolution_email(self):
        """Trigger Odoo mail template to send resolution email to employee"""
        self.ensure_one()
        template = self.env.ref('zunax_it_ticketing.email_template_ticket_resolved', raise_if_not_found=False)
        if template:
            template.send_mail(self.id, force_send=True)
            _logger.info("IT Ticket resolution email sent to employee for ticket: %s", self.ticket_number)
        else:
            _logger.warning("Resolution email template not found.")

    def _send_resolution_whatsapp(self):
        """Send WhatsApp message using Odoo standard WhatsApp templates or fallback URL log"""
        self.ensure_one()
        phone_number = self.phone or (self.partner_id.mobile or self.partner_id.phone)
        if not phone_number:
            _logger.warning("No phone/mobile number available for employee. Skipping WhatsApp alert.")
            return

        whatsapp_template = self.env.ref('zunax_it_ticketing.whatsapp_template_ticket_resolved', raise_if_not_found=False)
        if whatsapp_template and hasattr(self.env, 'whatsapp.composer'):
            try:
                composer = self.env['whatsapp.composer'].with_context(
                    active_model='it.ticket',
                    active_id=self.id
                ).create({
                    'wa_template_id': whatsapp_template.id,
                })
                composer.action_send_whatsapp()
                _logger.info("WhatsApp notification triggered via standard Odoo module for ticket: %s", self.ticket_number)
                return
            except Exception as e:
                _logger.error("Failed sending standard WhatsApp notification: %s", str(e))

        _logger.info("Triggering Fallback WhatsApp Notification to: %s for ticket: %s", phone_number, self.ticket_number)
