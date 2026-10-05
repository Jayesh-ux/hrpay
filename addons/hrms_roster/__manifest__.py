{
    "name": "HRMS Rostering and Attendance",
    "summary": "Publish-first rostering: roster periods, shifts, assignments, "
               "demand forecasting and attendance exceptions validated against "
               "the published roster",
    "version": "18.0.1.0.0",
    "category": "Human Resources",
    "license": "LGPL-3",
    "author": "hrpay",
    "depends": [
        "hrms_core_ext",
        "hr_contract",
        "hr_leave",
        "hr_attendance",
        "hrms_statutory",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/solver_security.xml",
        "views/roster_views.xml",
        "views/solver_views.xml",
    ],
    "installable": True,
    "application": False,
}
