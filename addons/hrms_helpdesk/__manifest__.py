{
    "name": 'HRMS Helpdesk and Support',
    "summary": 'HR service desk: ticket categories mapped to statutory obligations, due dates driven by statutory deadlines, confidential-case access rules and AI triage suggestions',
    "version": '18.0.1.0.0',
    "category": 'Help Desk',
    "license": 'LGPL-3',
    "author": 'hrpay',
    "depends": ['helpdesk_mgmt', 'helpdesk_mgmt_sla', 'helpdesk_mgmt_type', 'helpdesk_mgmt_rating', 'helpdesk_mgmt_team', 'hrms_core_ext', 'hrms_statutory'],
    "data": ['security/hrms_helpdesk_security.xml', 'security/ir.model.access.csv', 'data/helpdesk_ticket_categories.xml', 'views/ticket_views.xml'],
    "installable": True,
    "application": False,
}
