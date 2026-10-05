{
    "name": "HRMS Statutory Rules Engine",
    "summary": "Effective-dated, source-referenced, sign-off-gated statutory "
               "configuration; India wages-composition engine; PF/ESI/PT/LWF/TDS "
               "and gratuity computations",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "license": "LGPL-3",
    "author": "hrpay",
    "depends": [
        "hrms_core_ext",
        "hr_payroll_community",
        "hr_payroll_account_community",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/hrms_statutory_security.xml",
    ],
    "installable": True,
    "application": False,
}
