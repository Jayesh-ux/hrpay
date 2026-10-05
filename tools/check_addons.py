#!/usr/bin/env python3
"""Static cross-reference checks for the hrpay addons.

Cannot replace running Odoo, but catches the class of mistake that only shows up
at install time: a reference to an XML id that does not exist, or one belonging
to an addon that has not been loaded yet.

Note on reference resolution:
  * An unprefixed ref/parent/action resolves within the declaring addon.
  * Every model automatically gets an ir.model record with id
    ``model_<name with dots replaced by underscores>``, so ``model_foo.bar_baz``
    is valid without being declared in XML.
  * A ref prefixed with a module that is not in this repository cannot be checked
    here and is skipped rather than reported.
"""

import ast
import csv
import pathlib
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDONS = ROOT / "addons"


def addon_of(path):
    return path.relative_to(ADDONS).parts[0]


def load_manifests():
    manifests = {}
    for path in sorted(ADDONS.glob("*/__manifest__.py")):
        try:
            manifests[path.parent.name] = ast.literal_eval(path.read_text().strip())
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"{path}: manifest is not a literal dict: {exc}")
    return manifests


def declared_ids(manifests):
    """xml ids each addon makes available, including auto-generated model ids.

    An ACL on an inherited model is legitimate: ``_inherit = "hr.employee"``
    adds fields to a model whose ``model_hr_employee`` id is created by the base
    ``hr`` module. Those ids are therefore allowed too, even though this
    repository does not declare them.
    """
    model_ids = {}
    for path in sorted(ADDONS.glob("*/models/*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            own, inherited = None, set()
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                key = getattr(stmt.targets[0], "id", "")
                if key == "_name" and isinstance(stmt.value, ast.Constant):
                    own = stmt.value.value
                elif key == "_inherit":
                    # _inherit is often a list: ["hr.employee", "some.mixin"].
                    if isinstance(stmt.value, ast.Constant):
                        inherited.add(stmt.value.value)
                    elif isinstance(stmt.value, (ast.List, ast.Tuple)):
                        inherited.update(
                            el.value for el in stmt.value.elts
                            if isinstance(el, ast.Constant)
                        )
            if own:
                model_ids.setdefault(addon_of(path), set()).add(
                    "model_" + own.replace(".", "_")
                )
            for base in inherited:
                model_ids.setdefault(addon_of(path), set()).add(
                    "model_" + base.replace(".", "_")
                )

    ids = {}
    for path in sorted(ADDONS.glob("*/**/*.xml")):
        addon = addon_of(path)
        ids.setdefault(addon, set()).update(
            el.get("id") for el in ET.parse(path).iter() if el.get("id")
        )
        ids[addon] |= model_ids.get(addon, set())
    return ids


def load_order(manifests, addons):
    order, seen = [], set()

    def visit(name, stack=()):
        if name in seen or name in stack:
            return
        for dep in manifests[name].get("depends", []):
            if dep in addons:
                visit(dep, stack + (name,))
        seen.add(name)
        order.append(name)

    for name in sorted(addons):
        visit(name)
    return order


def main():
    manifests = load_manifests()
    addons = set(manifests)
    ids = declared_ids(manifests)
    order = load_order(manifests, addons)
    errors = []

    # Dependency cycles.
    for name in order:
        for dep in manifests[name].get("depends", []):
            if dep not in addons:
                continue
            if order.index(dep) > order.index(name):
                errors.append(f"{name}: depends on {dep}, which loads later")

    # Manifest data files exist, and views load after the security they inherit.
    for name, manifest in manifests.items():
        data = manifest.get("data", [])
        for rel in data:
            if not (ADDONS / name / rel).exists():
                errors.append(f"{name}: manifest lists missing file {rel}")
        for i, rel in enumerate(data):
            if "views/" in rel:
                for later in data[i + 1:]:
                    if "views/" not in later:
                        errors.append(
                            f"{name}: {later} loads after views, so records the "
                            f"views reference may not exist yet"
                        )

    # XML references resolve, within the addon or into an already-loaded one.
    for path in sorted(ADDONS.glob("*/**/*.xml")):
        addon = addon_of(path)
        for el in ET.parse(path).iter():
            for attr in ("ref", "parent", "action", "inherit_id"):
                value = (el.get(attr) or "").split(",")[0].strip()
                if not value:
                    continue
                if "." in value:
                    module, _, local = value.partition(".")
                    if module not in addons:
                        continue
                    if order.index(module) > order.index(addon):
                        errors.append(f"{path}: {value} but {module} loads later")
                    if local not in ids.get(module, set()):
                        errors.append(f"{path}: {value} is not declared in {module}")
                elif value not in ids.get(addon, set()):
                    errors.append(f"{path}: '{value}' is not declared in {addon}")

    # ACL csv shape, and that every referenced model is a real model.
    for path in sorted(ADDONS.glob("*/security/ir.model.access.csv")):
        rows = list(csv.reader(path.open()))
        if not rows:
            errors.append(f"{path}: empty")
            continue
        for i, row in enumerate(rows[1:], 2):
            if len(row) != 8:
                errors.append(f"{path}:{i}: {len(row)} columns, expected 8")
                continue
            model_xml_id = row[2].split(".")[-1]
            if model_xml_id.startswith("model_") and model_xml_id not in ids.get(
                addon_of(path), set()
            ):
                errors.append(f"{path}:{i}: {model_xml_id} does not match any model")

    print("load order: " + " -> ".join(order))
    for name in order:
        external = [d for d in manifests[name].get("depends", []) if d not in addons]
        print(f"  {name:20} external: {', '.join(external) or '-'}")

    tests = sorted(ADDONS.glob("*/tests/test_*.py"))
    total = 0
    for path in tests:
        count = sum(
            1
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
        total += count
        print(f"  {addon_of(path):20} {count:3} authored tests (not executed)")

    print(f"\n{len(errors)} error(s), {total} authored test(s)")
    for err in errors:
        print("  ERROR  ", err)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())