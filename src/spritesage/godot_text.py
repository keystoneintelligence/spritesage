"""Edit known spans in Godot text resources without rewriting user content.

This supports the generated SpriteFrames structure, not arbitrary Variant
values. Unsupported structures fail closed before any export writes.
"""

import json
import math
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    def text(self, source: str) -> str:
        return source[self.start : self.end]


def items(source: str, span: Span) -> list[Span]:
    """Split a container at top-level commas, respecting strings and nesting."""
    start = span.start + 1
    stack: list[str] = []
    quoted = escaped = False
    result = []
    for index in range(start, span.end - 1):
        char = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "[{(":
            stack.append(char)
        elif char in "]})":
            if not stack or "[{("["]})".index(char)] != stack.pop():
                raise ValueError("Unsupported Godot resource structure.")
        elif char == "," and not stack:
            _append_span(source, result, start, index)
            start = index + 1
    if quoted or stack:
        raise ValueError("Incomplete Godot resource structure.")
    _append_span(source, result, start, span.end - 1)
    return result


def _append_span(source: str, result: list[Span], start: int, end: int) -> None:
    while start < end and source[start].isspace():
        start += 1
    while end > start and source[end - 1].isspace():
        end -= 1
    if start < end:
        result.append(Span(start, end))


def container(source: str, start: int) -> Span:
    opening = source[start]
    if opening not in "[{(":
        raise ValueError("Expected a Godot resource container.")
    stack = [opening]
    quoted = escaped = False
    for index in range(start + 1, len(source)):
        char = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "[{(":
            stack.append(char)
        elif char in "]})":
            if "[{("["]})".index(char)] != stack.pop():
                raise ValueError("Unsupported Godot resource structure.")
            if not stack:
                return Span(start, index + 1)
    raise ValueError("Incomplete Godot resource structure.")


def fields(source: str, span: Span) -> dict[str, Span]:
    if source[span.start] != "{":
        raise ValueError("Expected a Godot animation dictionary.")
    result = {}
    for item in items(source, span):
        match = re.match(r'"((?:[^"\\]|\\.)*)"\s*:\s*', item.text(source))
        if not match:
            raise ValueError("Unsupported Godot animation dictionary.")
        key = json.loads('"' + match[1] + '"')
        if key in result:
            raise ValueError("Duplicate Godot animation property.")
        result[key] = Span(item.start + match.end(), item.end)
    return result


def animations(source: str) -> dict[str, dict[str, Span]]:
    resource = re.search(r"(?m)^\[resource\]\s*$", source)
    if not resource:
        raise ValueError("Missing Godot resource section.")
    match = re.search(r"(?m)^animations\s*=\s*\[", source[resource.end() :])
    if not match:
        raise ValueError("Missing Godot animations array.")
    start = resource.end() + match.end() - 1
    result = {}
    for span in items(source, container(source, start)):
        record = fields(source, span)
        name = json.loads(record["name"].text(source).removeprefix("&"))
        if name in result:
            raise ValueError("Duplicate Godot animation name.")
        result[name] = record
    return result


def scalar(source: str, span: Span, *, allow_zero: bool = False) -> float | bool:
    value = span.text(source)
    if value in ("true", "false"):
        return value == "true"
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
        raise ValueError("Unsupported Godot playback value.")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError("Invalid Godot playback value.")
    return number


def patch(source: str, edits: list[tuple[Span, str]]) -> str:
    for span, value in sorted(edits, key=lambda edit: edit[0].start, reverse=True):
        source = source[: span.start] + value + source[span.end :]
    return source
