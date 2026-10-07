"""Check statically known ``str.format`` calls for missing fields."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from string import Formatter


TRANSLATION_FUNCTIONS = {"_", "gettext", "gettext_noop", "pgettext"}


def get_literal_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = get_literal_string(node.left)
        right = get_literal_string(node.right)
        if left is not None and right is not None:
            return left + right

    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in TRANSLATION_FUNCTIONS
        and node.args
    ):
        # pgettext(context, message) takes its message as the final argument.
        message = node.args[-1] if node.func.id == "pgettext" else node.args[0]
        return get_literal_string(message)

    return None


def get_format_fields(template: str) -> list[str]:
    fields: list[str] = []
    formatter = Formatter()

    def visit(format_string: str) -> None:
        for _literal_text, field_name, format_spec, _conversion in (
                formatter.parse(format_string)):
            if field_name is not None:
                fields.append(field_name)
                if format_spec:
                    visit(format_spec)

    visit(template)
    return fields


def get_missing_fields(call: ast.Call, template: str) -> list[str]:
    fields = get_format_fields(template)
    named_fields: set[str] = set()
    positional_indexes: list[int] = []
    automatic_index = 0

    for field in fields:
        root = field.split(".", 1)[0].split("[", 1)[0]
        if root == "":
            positional_indexes.append(automatic_index)
            automatic_index += 1
        elif root.isdecimal():
            positional_indexes.append(int(root))
        else:
            named_fields.add(root)

    keyword_names = {
        keyword.arg for keyword in call.keywords if keyword.arg is not None
    }
    has_keyword_unpacking = any(keyword.arg is None for keyword in call.keywords)
    has_positional_unpacking = any(isinstance(arg, ast.Starred) for arg in call.args)

    missing = sorted(
        field for field in named_fields
        if field not in keyword_names and not has_keyword_unpacking
    )

    if not has_positional_unpacking:
        missing_indexes = sorted({
            index for index in positional_indexes if index >= len(call.args)
        })
        if missing_indexes:
            missing.extend(f"positional index {index}" for index in missing_indexes)

    return missing


def tracked_python_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo_root}",
            "-C",
            str(repo_root),
            "ls-files",
            "-z",
            "--",
            "*.py",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        repo_root / path.decode()
        for path in result.stdout.split(b"\0")
        if path and not is_test_file(Path(path.decode()))
    ]


def is_test_file(path: Path) -> bool:
    return (
        any(part in {"test", "tests"} for part in path.parts)
        or path.name == "tests.py"
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    issues: list[str] = []
    checked_templates = 0
    dynamic_templates = 0

    for path in tracked_python_files(repo_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            issues.append(
                f"{path.relative_to(repo_root)}: unable to parse Python: {exc}"
            )
            continue

        for node in ast.walk(tree):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "format"
            ):
                continue

            template = get_literal_string(node.func.value)
            if template is None:
                dynamic_templates += 1
                continue

            checked_templates += 1
            try:
                missing = get_missing_fields(node, template)
            except ValueError as exc:
                issues.append(
                    f"{path.relative_to(repo_root)}:{node.lineno}: "
                    f"invalid format string {template!r}: {exc}"
                )
                continue

            if missing:
                issues.append(
                    f"{path.relative_to(repo_root)}:{node.lineno}: "
                    f"missing format field(s) {', '.join(missing)} in {template!r}"
                )

    if issues:
        print("String format check failed:", file=sys.stderr)
        for issue in issues:
            print(f"  {issue}", file=sys.stderr)
        return 1

    print(
        f"Checked {checked_templates} static format template(s); "
        f"skipped {dynamic_templates} dynamic template(s)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
