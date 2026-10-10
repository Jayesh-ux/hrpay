{
    "name": "HRMS Theme",
    "summary": "Consolidated HRMS app menu plus a couple of small, non-layout "
               "backend tweaks. Light is the default theme.",
    "version": "18.0.1.1.0",
    "category": "Theme/Backend",
    "license": "LGPL-3",
    "author": "hrpay",
    "website": "https://github.com/hrpay/hrpay",
    "depends": [
        "web",
        "hr",
        "hrms_core_ext",
        "hrms_roster",
        "hrms_payroll_run",
        "hrms_fnf",
        "hrms_statutory",
    ],
    "data": [
        "views/menus.xml",
    ],
    "assets": {
        "web._assets_primary_variables": [
            "hrms_theme/static/src/scss/primary_variables.scss",
        ],
        "web.assets_backend": [
            "hrms_theme/static/src/scss/hrms_theme.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
