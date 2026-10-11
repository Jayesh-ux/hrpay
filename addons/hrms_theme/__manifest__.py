{
    "name": "HRMS Theme",
    "summary": "Dark navy + violet backend redesign: fixed left sidebar, gradient "
               "page headers, restyled lists/forms/kanban. Dark by default with a "
               "light toggle. Styling and a small UI-enhancement script only.",
    "version": "18.0.1.2.0",
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
            # GSAP core is vendored locally (no CDN / runtime network dependency)
            # so animations work offline. Loaded before theme.js, which uses the
            # global `gsap`. License: GSAP Standard (free) - see static/lib/gsap.
            "hrms_theme/static/lib/gsap/gsap.min.js",
            "hrms_theme/static/src/scss/hrms_theme.scss",
            "hrms_theme/static/src/js/theme.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
