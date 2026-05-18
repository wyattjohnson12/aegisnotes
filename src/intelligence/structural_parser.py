"""Detect headings and build a topic tree.

Heuristics (all conservative, all deterministic):

* A line is a **heading** if it matches *any* of:
   - Numbered prefix:  ``1.``, ``1.1``, ``A.``, ``IV.``, ``2)``.
   - ALL-CAPS line, 2-50 chars, no terminal full-stop.
   - Title-case line that ends with ``:`` (e.g. ``Definitions:``).
   - A short line (≤ 60 chars, ≤ 8 words) sandwiched between a blank
     line and a content paragraph.
* The level for numbered headings is the depth of the numbering
  (``1.`` → 1, ``1.1`` → 2, ``1.1.1`` → 3). All other detected
  headings default to level 1.
* If no heading is detected at all, the whole note becomes a single
  level-1 topic titled "Note".
* Topics are emitted as a *flat* list with explicit ``level`` so the
  repository's tree-builder can re-parent them. (Some OCR'd notes have
  ragged level assignments; the repo's stack-based reparenting handles
  it.)

The parser never raises on malformed input; pathological notes simply
produce one root topic.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TopicNode:
    title: str
    level: int
    content: str = ""
    children: List["TopicNode"] = field(default_factory=list)


# --- Heading detectors -----------------------------------------------------
_NUMBERED_RE = re.compile(
    r"""
    ^\s*
    (
        (?:\d+(?:\.\d+){0,4})        # 1, 1.1, 1.1.1
        |
        (?:[IVXLCDM]+)               # roman numerals
        |
        (?:[A-Z])                    # single letter
    )
    [\.\)]\s+
    (.+?)
    \s*$
    """,
    re.VERBOSE,
)

_TRAILING_COLON_RE = re.compile(r"^([A-Z][^:\n]{1,80}):\s*$")
_ALL_CAPS_RE = re.compile(r"^[A-Z0-9][A-Z0-9 \-\&\(\)/]{1,49}$")


class StructuralParser:
    def __init__(self, *, max_topics: int = 200) -> None:
        self._max = max_topics

    def parse(self, cleaned_text: str) -> List[TopicNode]:
        if not cleaned_text or not cleaned_text.strip():
            return [TopicNode(title="Note", level=1)]

        raw_lines = cleaned_text.splitlines()
        # Detect headings.
        flat: List[TopicNode] = []
        buffer: List[str] = []

        def _flush_buffer_into_last() -> None:
            if not buffer:
                return
            content = "\n".join(buffer).strip()
            if not content:
                buffer.clear()
                return
            if flat:
                # Append to the most recent topic's content.
                last = flat[-1]
                last.content = (last.content + "\n" + content).strip() if last.content else content
            else:
                # No heading yet — first paragraph becomes root content.
                flat.append(TopicNode(title=_synth_title(content), level=1, content=content))
            buffer.clear()

        for i, raw_line in enumerate(raw_lines):
            line = raw_line.rstrip()
            stripped = line.strip()

            if not stripped:
                buffer.append(line)
                continue

            heading = _detect_heading(stripped, i, raw_lines)
            if heading is not None:
                _flush_buffer_into_last()
                title, level = heading
                flat.append(TopicNode(title=title, level=level))
                if len(flat) >= self._max:
                    break
                continue

            buffer.append(line)

        _flush_buffer_into_last()

        if not flat:
            return [TopicNode(title="Note", level=1, content=cleaned_text)]

        return _reparent(flat)


# ---------------------------------------------------------------------------
def _detect_heading(line: str, idx: int, all_lines: List[str]) -> Optional[tuple[str, int]]:
    """Return (title, level) if the line looks like a heading."""
    m = _NUMBERED_RE.match(line)
    if m:
        prefix, title = m.group(1), m.group(2).strip()
        level = max(1, prefix.count(".") + 1) if prefix and prefix[0].isdigit() else 1
        if level <= 6 and len(title) >= 2 and len(title) <= 120:
            return (title, level)

    m = _TRAILING_COLON_RE.match(line)
    if m:
        return (m.group(1).strip(), 1)

    if _ALL_CAPS_RE.match(line):
        return (line.title(), 1)

    # Short Title-case line followed by a content paragraph.
    if 2 <= len(line.split()) <= 8 and line[0].isupper() and not line.endswith((".", "!", "?", ",")):
        prev = all_lines[idx - 1].strip() if idx > 0 else ""
        nxt = all_lines[idx + 1].strip() if idx + 1 < len(all_lines) else ""
        if not prev and nxt and len(nxt) > 20:
            return (line, 1)

    return None


def _synth_title(content: str) -> str:
    """Best-effort title for a leading paragraph that has no heading."""
    first = content.strip().splitlines()[0] if content else "Note"
    first = re.sub(r"\s+", " ", first).strip(" .;:!?-")
    if len(first) > 80:
        first = first[:77] + "..."
    return first or "Note"


def _reparent(flat: List[TopicNode]) -> List[TopicNode]:
    """Turn a flat list of (title, level) into a properly-parented tree.

    Uses a stack: a node attaches to the most recent ancestor whose
    level is strictly less than its own. Levels are clamped to a sane
    range to defend against ragged OCR input.
    """
    roots: List[TopicNode] = []
    stack: List[TopicNode] = []
    for node in flat:
        node.level = max(1, min(node.level, 6))
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if not stack:
            roots.append(node)
        else:
            stack[-1].children.append(node)
        stack.append(node)
    return roots
