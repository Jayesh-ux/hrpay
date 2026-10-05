#!/usr/bin/env python3
"""Check that every field named in a view exists on the model.

A mistyped field name in a view is an install-time error, not a runtime one, and
it is easy to introduce when fields are listed by hand. This resolves each
``<field name="..."/>`` against the model it is rendered in, following
``ir.ui.view`` arch bodies and inherited views.

Fields on core Odoo models that this repository does not extend are listed in
EXTERNAL below; anything referencing a core field not listed there is reported
rather than silently accepted.
"""

import ast
import pathlib
import sys
import xml.etree.ElementTree as ET

ADDONS = pathlib.Path(__file__).resolve().parents[1] / "addons"

# Core fields referenced by views but not declared here. Kept explicit so an
# addition to a view cannot quietly rely on a field nobody verified.
EXTERNAL = {
    "hr.employee": {
        "name", "user_id", "company_id", "department_id", "join_date",
        "skill_ids", "contract_id", "active", "parent_id", "job_id",
        "employee_type", "work_contact_id", "identification_id", "date_of_birth",
    },
    "hr.leave": {
        "state", "date_from", "date_to", "holiday_status_id", "user_id",
        "employee_id", "number_of_days", "description",
    },
    "hr.contract": {"wage", "employee_id", "company_id", "date_start", "date_end"},
    "hr.department": {"name", "company_id", "parent_id", "member_ids"},
    "hr.payslip": {
        "employee_id", "date_from", "date_to", "state", "total", "name",
        "contract_id", "struct_id", "worked", "input", "other", "note",
        "number", "company_id", "currency_id", "line_ids",
    },
    "hr.payslip.line": {"name", "code", "quantity", "rate", "amount", "total"},
    "res.company": {"name", "currency_id", "parent_id"},
    "res.users": {"name", "login", "groups_id", "company_id"},
    "res.groups": {"name", "category_id", "implied_ids", "comment"},
    "res.partner": {"name", "email", "phone", "company_id"},
    "helpdesk.ticket": {
        "name", "partner_id", "user_id", "team_id", "stage_id", "category_id",
        "ticket_type_id", "priority", "partner_email", "description", "date",
        "date_deadline", "close_date", "channel_id", "tag_ids", "rating_ids",
        "active", "company_id", "number", "message_follower_ids",
    },
    "hr.skill": {"name"},
    "hr.payslip.run": {"state", "date_from", "date_to", "name", "slip_ids"},
    "account.move": {"name", "state", "date", "amount_total", "move_type"},
    "account.payment": {"name", "amount", "date", "state"},
}

# Not model fields: view/record plumbing.
PLUMBING = {
    "groups_id", "arch", "inherit_id", "domain_force", "eval", "sequence",
    "id", "name", "code", "module", "value", "key", "special", "attrs",
    "context", "domain", "model", "priority", "widget", "class", "colspan",
    "states", "track", "nodrop", "default", "precompute", "search", "options",
    "display_name", "translation", "group_operator", "ondelete", "currency_field",
    "change_default", "copy", "store", "index", "compute", "inverse", "related",
    "help", "string", "size", "digits", "selection", "tracking", "aggregator",
    "position", "view_id", "mode", "field_id", "model_id", "act_window_id",
    "allow", "column1", "column2", "values", "tag", "first", "last", "empty",
    "date_start", "date_end", "note", "arch_base", "field_parent", "t-field",
}


def collect_relations():
    """model -> {field name: related model} for relational fields.

    A nested list inside a relational field renders the related model's fields,
    not the parent's, so the arch walk needs to know where each relation points.
    """
    relations = {}
    for path in sorted(ADDONS.glob("*/models/*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            model, bases = None, set()
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                key = getattr(stmt.targets[0], "id", "")
                value = stmt.value
                if key == "_name" and isinstance(value, ast.Constant):
                    model = value.value
                elif key == "_inherit":
                    if isinstance(value, ast.Constant):
                        bases.add(value.value)
                    elif isinstance(value, (ast.List, ast.Tuple)):
                        bases.update(
                            el.value for el in value.elts if isinstance(el, ast.Constant)
                        )
                elif model and not key.startswith("_") and isinstance(value, ast.Call):
                    fn = getattr(value.func, "attr", "")
                    if fn in ("Many2one", "One2many", "Many2many") and value.args:
                        first = value.args[0]
                        target = None
                        if isinstance(first, ast.Constant):
                            target = first.value
                        elif fn == "One2many" and len(value.args) > 1:
                            # One2many(comodel, inverse_name)
                            if isinstance(value.args[1], ast.Constant):
                                target = value.args[1].value
                        if target:
                            relations.setdefault(model, {}).setdefault(key, target)
            for base in bases:
                relations.setdefault(base, {})
    return relations


def collect_model_fields():
    """model name -> field names, including fields added by _inherit."""
    own, inherited = {}, {}
    for path in sorted(ADDONS.glob("*/models/*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            model, bases, names = None, set(), set()
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                key = getattr(stmt.targets[0], "id", "")
                if key == "_name" and isinstance(stmt.value, ast.Constant):
                    model = stmt.value.value
                elif key == "_inherit":
                    value = stmt.value
                    if isinstance(value, ast.Constant):
                        bases.add(value.value)
                    elif isinstance(value, (ast.List, ast.Tuple)):
                        bases.update(
                            el.value for el in value.elts if isinstance(el, ast.Constant)
                        )
                elif not key.startswith("_"):
                    names.add(key)
            if model:
                own.setdefault(model, set()).update(names)
            for base in bases:
                inherited.setdefault(base, set()).update(names)
    fields = {k: set(v) for k, v in own.items()}
    for base, names in inherited.items():
        fields.setdefault(base, set()).update(names)
    for model, names in EXTERNAL.items():
        fields.setdefault(model, set()).update(names)
    return fields


def check_view(path, fields, errors, relations):
    tree = ET.parse(path)
    for record in tree.iter("record"):
        if record.get("model") != "ir.ui.view":
            continue
        model = None
        inherit_id = None
        for child in record:
            if child.get("name") == "model" and child.text:
                model = child.text.strip()
            if child.get("name") == "inherit_id" and child.text:
                inherit_id = child.text.strip()
        if model is None and inherit_id:
            # An inherited view renders fields of the model it inherits from, so
            # resolve that model from the id being inherited.
            target = inherit_id.split(".")[-1]
            for path2 in ADDONS.glob("*/views/*.xml"):
                for other in ET.parse(path2).iter("record"):
                    if other.get("model") != "ir.ui.view":
                        continue
                    if other.get("id") == target:
                        for c in other:
                            if c.get("name") == "model" and c.text:
                                model = c.text.strip()
        if not model:
            errors.append(f"{path}: view record {record.get('id')} declares no model")
            continue
        if model not in fields:
            continue
        for child in record:
            if child.get("name") != "arch":
                continue
            # Odoo embeds the view arch as real child markup, and its own importer
            # rebuilds the string from node.text plus the serialised children. So
            # the arch root is the first element child, not the text node; the
            # text here is only indentation.
            arch = next((c for c in child if isinstance(c.tag, str)), None)
            if arch is None:
                errors.append(f"{path}: view for {model} has an empty arch")
                continue
            check_arch(arch, model, path, fields, errors, relations)


def check_arch(el, model, path, fields, errors, relations):
    """Walk the arch, descending into relational sub-views with their own model."""
    for child in el:
        if not isinstance(child.tag, str):
            continue
        if child.tag == "field":
            name = child.get("name")
            if not name or name in PLUMBING:
                continue
            target = relations.get(model, {}).get(name)
            if target:
                # A relational field renders the related record's own fields.
                for sub in child:
                    if isinstance(sub.tag, str) and sub.tag in (
                        "list", "form", "tree", "search", "kanban",
                    ):
                        check_arch(sub, target, path, fields, errors, relations)
                continue
            if name in fields.get(model, set()):
                continue
            errors.append(f"{path}: field '{name}' is not a field of {model}")
        elif child.tag in ("list", "form", "tree", "search", "kanban"):
            check_arch(child, model, path, fields, errors, relations)
        else:
            check_arch(child, model, path, fields, errors, relations)


def main():
    fields = collect_model_fields()
    relations = collect_relations()
    errors = []
    for path in sorted(ADDONS.glob("*/views/*.xml")):
        check_view(path, fields, errors, relations)
    print(f"{len(errors)} view field error(s)")
    for err in errors:
        print("  ERROR  ", err)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())