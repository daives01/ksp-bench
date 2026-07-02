"""Small YAML subset parser for repository-owned scenario files.

The v0 scenarios deliberately use a conservative YAML subset: mappings,
lists, scalars, and indentation with spaces. This keeps the harness runnable
without runtime dependencies while still leaving the file format easy to move
to PyYAML or stricter schema tooling later.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SimpleYamlError(ValueError):
    """Raised when a scenario file uses unsupported YAML syntax."""


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a small YAML mapping from *path*."""

    lines = _preprocess(path.read_text(encoding="utf-8").splitlines())
    if not lines:
        return {}

    index, result = _parse_mapping(lines, 0, lines[0][0])
    if index != len(lines):
        raise SimpleYamlError(f"unexpected content on line {lines[index][1]}")
    return result


def _preprocess(raw_lines: list[str]) -> list[tuple[int, int, str]]:
    lines: list[tuple[int, int, str]] = []
    for line_no, raw_line in enumerate(raw_lines, start=1):
        if "\t" in raw_line:
            raise SimpleYamlError(f"tabs are not supported on line {line_no}")
        without_comment = _strip_comment(raw_line).rstrip()
        if not without_comment.strip():
            continue
        indent = len(without_comment) - len(without_comment.lstrip(" "))
        lines.append((indent, line_no, without_comment.strip()))
    return lines


def _strip_comment(line: str) -> str:
    in_quote: str | None = None
    for index, char in enumerate(line):
        if char in {"'", '"'}:
            if in_quote is None:
                in_quote = char
            elif in_quote == char:
                in_quote = None
        elif char == "#" and in_quote is None:
            return line[:index]
    return line


def _parse_mapping(
    lines: list[tuple[int, int, str]], index: int, indent: int
) -> tuple[int, dict[str, Any]]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        current_indent, line_no, text = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"unexpected indentation on line {line_no}")
        if text.startswith("- "):
            break

        key, separator, value = text.partition(":")
        if not separator:
            raise SimpleYamlError(f"expected key/value mapping on line {line_no}")
        key = key.strip()
        if not key:
            raise SimpleYamlError(f"empty key on line {line_no}")
        if value.strip():
            mapping[key] = _parse_scalar(value.strip())
            index += 1
            continue

        index += 1
        if index >= len(lines) or lines[index][0] <= current_indent:
            mapping[key] = {}
            continue
        child_indent = lines[index][0]
        if lines[index][2].startswith("- "):
            index, mapping[key] = _parse_list(lines, index, child_indent)
        else:
            index, mapping[key] = _parse_mapping(lines, index, child_indent)
    return index, mapping


def _parse_list(
    lines: list[tuple[int, int, str]], index: int, indent: int
) -> tuple[int, list[Any]]:
    values: list[Any] = []
    while index < len(lines):
        current_indent, line_no, text = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise SimpleYamlError(f"unexpected indentation on line {line_no}")
        if not text.startswith("- "):
            break
        value = text[2:].strip()
        if value:
            values.append(_parse_scalar(value))
            index += 1
            continue
        index += 1
        if index >= len(lines) or lines[index][0] <= current_indent:
            values.append({})
            continue
        child_indent = lines[index][0]
        if lines[index][2].startswith("- "):
            index, child = _parse_list(lines, index, child_indent)
        else:
            index, child = _parse_mapping(lines, index, child_indent)
        values.append(child)
    return index, values


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "Null", "None", "~"}:
        return None
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
