{
    "name": 'HRMS Helpdesk and Support',
    "summary": 'HR service desk: ticket categories mapped to statutory obligations, due dates driven by statutory deadlines, confidential-case access rules and AI triage suggestions',
    "version": '18.0.1.0.0',
    "category": 'Help Desk',
    "license": 'LGPL-3',
    "author": 'hrpay',
    # helpdesk_mgmt provides helpdesk.ticket; helpdesk_type provides
    # helpdesk.ticket.type, which hrms_helpdesk extends. Upstream renamed
    # helpdesk_mgmt_type -> helpdesk_type during the 18.0 cycle, so the old
    # names do not resolve. The SLA, business-hours and CSAT modules are
    # deliberately not depended on: nothing in this addon reads them, and the
    # original SLA requirement is still unmet and tracked in
    # docs/adr/0009-oca-helpdesk-dependency-minimisation.md.
    "depends": ['helpdesk_mgmt', 'helpdesk_type', 'hrms_core_ext', 'hrms_statutory'],
    "data": ['security/hrms_helpdesk_security.xml', 'security/ir.model.access.csv', 'data/helpdesk_ticket_categories.xml', 'views/ticket_views.xml'],
    "installable": True,
    "application": False,
}
