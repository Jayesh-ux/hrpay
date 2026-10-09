{
    "name": "HRMS Payroll Run Orchestration",
    "summary": "Payroll run lifecycle: attendance and roster gating, statutory "
               "coverage check, immutable results, anomaly flags, approval "
               "separation and period lock",
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
        "security/ir.model.access.csv",
        "security/hrms_payroll_run_security.xml",
        "views/payroll_run_views.xml",
    ],
    "installable": True,
    "application": False,
}
