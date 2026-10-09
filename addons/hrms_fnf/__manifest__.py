{
    "name": "HRMS Full and Final Settlement",
    "summary": "Statutory-gated final settlement: leave encashment, notice "
               "shortfall recovery, gratuity, statutory dues and clawback, with "
               "a payable-by clock and an itemised, signed-off statement",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "license": "LGPL-3",
    "author": "hrpay",
    "depends": [
        "hrms_core_ext",
        "hrms_statutory",
        "hrms_roster",
        "hr_payroll_community",
        "hr_payroll_account_community",
    ],
    "data": [
        "security/hrms_fnf_security.xml",
        "security/ir.model.access.csv",
        "data/fnf_reason_codes.xml",
        "views/fnf_views.xml"
    ],
    "installable": True,
    "application": False,
}
