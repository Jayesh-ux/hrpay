#!/usr/bin/env python3
"""Render a concrete test-run report from the template.

Kept separate from the shell script so the substitution is inspectable and
testable, and so a run report is reproducible from a template rather than
hand-written after the fact. A hand-written report is how a failing run ends up
recorded as passing.
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import subprocess


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--status", required=True, choices=["pass", "fail", "install-failed"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--addons", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--odoo-version", required=True)
    parser.add_argument("--pg-version", required=True)
    parser.add_argument("--total-tests", default="0")
    parser.add_argument("--total-failures", default="0")
    parser.add_argument("--exit-code", default="0")
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    generated = datetime.datetime.now(datetime.timezone.utc)
    context = {
        "RUN_ID": args.run_id,
        "GENERATED_AT": now,
        "GIT_REVISION": git("rev-parse", "HEAD"),
        "GIT_BRANCH": git("rev-parse", "--abbrev-ref", "HEAD"),
        "STATUS": args.status,
        "ODOO_VERSION": args.odoo_version,
        "PG_VERSION": args.pg_version,
        "DATABASE": args.db,
        "ADDONS": args.addons.replace(",", ", "),
        "LOG_FILE": args.log,
        "TOTAL_TESTS": args.total_tests,
        "TOTAL_FAILURES": args.total_failures,
        "EXIT_CODE": args.exit_code,
        "ODOO_SUMMARY": args.summary or "(no summary line found in the log)",
    }

    template = pathlib.Path(args.template).read_text()
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))

    # Refuse to emit a report that still contains an unfilled placeholder: a
    # half-rendered report is worse than none, because it looks finished.
    leftover = [
        line.strip()
        for line in rendered.splitlines()
        if "{{" in line and "}}" in line
    ]
    if leftover:
        raise SystemExit(
            "template has placeholders this script does not fill:\n  "
            + "\n  ".join(sorted({l for l in leftover}))
        )

    path = pathlib.Path(args.output)
    path.write_text(rendered)
    print(f"rendered {path} ({generated:%Y-%m-%d})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())