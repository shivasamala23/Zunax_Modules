# -*- coding: utf-8 -*-

from odoo import models, fields, api, _

class ItTicketCancelWizard(models.TransientModel):
    _name = 'it.ticket.cancel.wizard'
    _description = 'Cancel IT Ticket Wizard'

    ticket_id = fields.Many2one(
        'it.ticket',
        string='Ticket',
        required=True,
        default=lambda self: self.env.context.get('active_id')
    )
    
    reason_id = fields.Many2one(
        'it.cancellation.reason',
        string='Cancellation Reason',
        required=True,
        domain="[('active', '=', True)]"
    )
    
    details = fields.Text(
        string='Additional Details',
        help='State any additional comments or context for the cancellation'
    )

    def action_cancel(self):
        """Perform the cancellation write which triggers backend validation rules"""
        self.ensure_one()
        reason_text = self.reason_id.name
        if self.details:
            reason_text += f"\nDetails: {self.details}"
            
        self.ticket_id.write({
            'stage': 'cancelled',
            'cancellation_reason': reason_text
        })
        return {'type': 'ir.actions.act_window_close'}
