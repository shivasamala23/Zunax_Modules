# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class ItDepartment(models.Model):
    _name = 'it.department'
    _description = 'IT Support Department'
    _order = 'sequence, id'

    name = fields.Char(string='Department Name', required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    
    email_alias = fields.Char(
        string='Email Alias',
        help='Incoming emails to this address will automatically create tickets for this department'
    )
    
    member_ids = fields.Many2many(
        'res.users',
        'it_department_res_users_rel',
        'it_department_id',
        'user_id',
        string='Support Team Members',
        domain="[('share', '=', False)]",
        help='Backend Odoo users who will handle tickets in this department'
    )
    
    manager_id = fields.Many2one(
        'res.users',
        string='Support Manager',
        domain="[('share', '=', False)]",
        help='Manager who will receive notifications or escalate tickets'
    )
    
    assigned_employee_id = fields.Many2one(
        'hr.employee.public',
        string='Default Assigned Employee',
        domain="[('user_id', '!=', False)]",
        help='Specify an employee to be automatically assigned to tickets raised in this department'
    )

    ticket_count = fields.Integer(compute='_compute_ticket_count', string='Open Tickets')
    resolved_count = fields.Integer(compute='_compute_ticket_count', string='Resolved Tickets')

    def _compute_ticket_count(self):
        for record in self:
            record.ticket_count = self.env['it.ticket'].search_count([
                ('department_id', '=', record.id),
                ('stage', 'in', ['new', 'in_progress'])
            ])
            record.resolved_count = self.env['it.ticket'].search_count([
                ('department_id', '=', record.id),
                ('stage', '=', 'resolved')
            ])

    def action_view_department_tickets(self):
        """Action button on the department board card to open its tickets dashboard"""
        self.ensure_one()
        return {
            'name': _('Tickets: %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'it.ticket',
            'view_mode': 'kanban,list,form',
            'domain': [('department_id', '=', self.id)],
            'context': {
                'default_department_id': self.id,
                'search_default_department_id': self.id,
            }
        }
