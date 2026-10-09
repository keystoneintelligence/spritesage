"""Edit known spans in Godot text resources without rewriting user content.

Known properties are editable spans. Arbitrary Variant values, metadata,
scripts, node properties and resource sections stay opaque and retain their text.
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


@dataclass(frozen=True)
class Section:
    kind: str
    attributes: dict[str, str]
    header: Span
    body: Span
    properties: dict[str, Span]


def sections(source: str) -> list[Section]:
    """Godot 4 text envelope; property values remain unevaluated Variant text."""
    headers = list(
        re.finditer(
            r"(?m)^\[(gd_resource|gd_scene|ext_resource|sub_resource|resource|node|connection)([^\n]*)\]\s*\n?",
            source,
        )
    )
    result = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(source)
        attributes = {}
        for match in re.finditer(r'(\w+)=("(?:[^"\\]|\\.)*"|[^\s]+)', header[2]):
            attributes[match[1]] = match[2]
        properties = {}
        offset = header.end()
        while offset < end:
            match = re.match(r"([^\s=;][^\n=]*?)\s*=\s*", source[offset:end])
            if match:
                start = offset + match.end()
                finish = source.find("\n", start, end)
                finish = end if finish == -1 else finish
                if start < end and source[start] in "[{(":
                    finish = container(source, start).end
                else:
                    constructor = re.match(r"[\w]+\(", source[start:end])
                    if constructor:
                        finish = container(source, start + constructor.end() - 1).end
                while finish > start and source[finish - 1].isspace():
                    finish -= 1
                properties[match[1].strip()] = Span(start, finish)
                offset = finish
            newline = source.find("\n", offset, end)
            offset = end if newline == -1 else newline + 1
        result.append(
            Section(
                header[1],
                attributes,
                Span(header.start(), header.end()),
                Span(header.end(), end),
                properties,
            )
        )
    return result


def animations_span(source: str) -> Span:
    section = next(section for section in sections(source) if section.kind == "resource")
    return section.properties["animations"]


def animation_records(source: str) -> dict[str, Span]:
    return {
        json.loads(fields(source, record)["name"].text(source).removeprefix("&")): record
        for record in items(source, animations_span(source))
    }
