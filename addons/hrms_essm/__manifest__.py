{
    "name": "HRMS Employee Self-Service",
    "summary": "Employee self-service ('My HR'): my profile and change requests, "
               "my payslips (gate-aware), my leave, my expenses, my documents and "
               "tax declarations. A UI over the existing HRMS backends; it does not "
               "reimplement payroll, statutory or approval logic.",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "license": "LGPL-3",
    "author": "hrpay",
    "website": "https://github.com/hrpay/hrpay",
    "depends": [
        "hr",
        "hr_holidays",
        "hr_expense",
        "hr_payroll_community",
        "hrms_core_ext",
        "mail",
    ],
    "data": [
        "security/hrms_essm_security.xml",
        "security/ir.model.access.csv",
        "data/hrms_essm_sequence.xml",
        "views/profile_change_request_views.xml",
        "views/tax_declaration_views.xml",
        "views/employee_self_views.xml",
        "views/payslip_self_views.xml",
        "views/leave_self_views.xml",
        "views/expense_self_views.xml",
        "views/document_views.xml",
        "views/hrms_essm_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
