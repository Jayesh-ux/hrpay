{
    "name": "HRMS Core Extension",
    "summary": "Schema extension: sync columns, payroll period lock, integration "
               "sync log, audit logging, column-level encryption, segregation "
               "of duties, statutory context plumbing",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "license": "LGPL-3",
    "author": "hrpay",
    "website": "https://github.com/hrpay/hrpay",
    "depends": [
        "hr",
        "hr_contract",
        "hr_holidays",
        "hr_attendance",
        "hr_expense",
        "mail",
    ],
    "external_dependencies": {"python": ["cryptography"]},
    "data": [
        "security/ir.model.access.csv",
        "security/hrms_security.xml",
        "data/ir_config_data.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
