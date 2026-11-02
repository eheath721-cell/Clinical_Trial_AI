"""Split registry eligibility text into a tree of inclusion / exclusion criteria.

The registry stores criteria as loosely formatted markdown. This parser:
  * finds the Inclusion / Exclusion sections,
  * turns bullets / numbered items into nodes, nesting by indentation, colon-introduced
    lists ("Meet one of the following criteria:") and numbering continuity,
  * marks group nodes and whether their children combine with ALL or ANY logic,
  * tracks cohort headers (e.g. "Part B (Participants with Dyslipidemia):") so that
    multi-cohort studies can be evaluated per cohort,
  * flags partial lists ("main criteria include but are not limited to").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ESCAPES = [("\\<", "<"), ("\\>", ">"), ("\\[", "["), ("\\]", "]"), ("\\.", "."), ("\\-", "-"),
            ("\\*", "*"), ("\\_", "_"), ("\\(", "("), ("\\)", ")"), ("\\~", "~")]

_SECTION_RE = re.compile(r"^\s*(?:key\s+|main\s+|major\s+)?(inclusion|exclusion)\s+criteria\s*:?\s*$", re.I)
_BULLET_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>[*\-•·]\s+|(?P<num>\d{1,2}[a-z]?)[.)]\s+|(?P<numc>\d{1,2}[a-z]):\s*|(?P<let>[a-z])[.)]\s+)(?P<text>.*)$")
_INNER_NUM_RE = re.compile(r"^(?P<num>\d{1,2})[.)]\s+(?P<text>.*)$")
_GROUP_ANY_RE = re.compile(r"\b(one of the following|any of the following|either|at least one of|one or more of|"
                           r"one or more of the following|any one of)\b", re.I)
_GROUP_TAIL_RE = re.compile(r"(:\s*$|defined as\s*:?\s*$|as evidenced by( history of)?( either)?\s*:?\s*$|"
                            r"following( criteria)?\s*:?\s*$|including\s*:?\s*$)", re.I)
_PARTIAL_RE = re.compile(r"not limited to|main (inclusion|exclusion) criteria|key (inclusion|exclusion) criteria", re.I)
_COHORT_RE = re.compile(r"\b(part|parts|cohort|arm|group|stage)\b|participants with|healthy (participants|volunteers)", re.I)


@dataclass
class CriterionNode:
    kind: str
    text: str
    ordinal: int = 0
    depth: int = 0
    children: list[CriterionNode] = field(default_factory=list)
    logic: str = "all"
    is_group: bool = False
    cohort: str | None = None
    parent: CriterionNode | None = field(default=None, repr=False)
    # parse bookkeeping
    indent: int = 0
    marker: str = "*"
    number: int | None = None


@dataclass
class ParsedCriteria:
    inclusion: list[CriterionNode]
    exclusion: list[CriterionNode]
    partial_list: bool = False
    cohorts: list[str] = field(default_factory=list)
    unstructured: bool = False

    def walk(self):
        def rec(nodes):
            for n in nodes:
                yield n
                yield from rec(n.children)

        yield from rec(self.inclusion)
        yield from rec(self.exclusion)


def clean_text(text: str) -> str:
    for a, b in _ESCAPES:
        text = text.replace(a, b)
    text = text.replace(" ", " ").replace("\r", "")
    return text


def _cohort_key(header: str) -> str | None:
    h = header.strip().rstrip(":").strip()
    if re.match(r"^all (parts|cohorts|participants|arms|groups)$", h, re.I):
        return None
    m = re.search(r"\(([^)]+)\)", h)
    key = (m.group(1) if m else h).strip().lower()
    return key or None


def parse_criteria(text: str | None) -> ParsedCriteria:
    if not text or not text.strip():
        return ParsedCriteria([], [], unstructured=True)
    lines = clean_text(text).split("\n")
    sections: dict[str, list[str]] = {"inclusion": [], "exclusion": []}
    current: str | None = None
    preamble: list[str] = []
    for line in lines:
        m = _SECTION_RE.match(line)
        if m:
            current = m.group(1).lower()
            continue
        if current is None:
            preamble.append(line)
        else:
            sections[current].append(line)
    unstructured = False
    if not sections["inclusion"] and not sections["exclusion"]:
        sections["inclusion"] = preamble  # no headings: treat everything as inclusion text
        unstructured = True

    partial = False
    cohorts: list[str] = []
    out: dict[str, list[CriterionNode]] = {}
    for kind in ("inclusion", "exclusion"):
        roots, p, cs = _build_tree(kind, sections[kind])
        partial = partial or p
        for c in cs:
            if c not in cohorts:
                cohorts.append(c)
        out[kind] = roots
    parsed = ParsedCriteria(out["inclusion"], out["exclusion"], partial, cohorts, unstructured)
    _finalize(parsed)
    return parsed


def _build_tree(kind: str, lines: list[str]) -> tuple[list[CriterionNode], bool, list[str]]:
    roots: list[CriterionNode] = []
    prev: CriterionNode | None = None
    cohort: str | None = None
    partial = False
    cohorts: list[str] = []

    for raw in lines:
        if not raw.strip() or not re.search(r"[A-Za-z0-9]", raw):
            continue
        m = _BULLET_RE.match(raw)
        if m is None:
            stripped = raw.strip()
            if stripped.endswith(":"):
                # header / context line
                if _PARTIAL_RE.search(stripped):
                    partial = True
                elif _COHORT_RE.search(stripped) or re.match(r"^all (parts|cohorts)", stripped, re.I):
                    cohort = _cohort_key(stripped)
                    if cohort and cohort not in cohorts:
                        cohorts.append(cohort)
                prev = None
                continue
            if prev is not None and (len(raw) - len(raw.lstrip())) > prev.indent:
                prev.text = f"{prev.text} {stripped}"  # wrapped continuation
                continue
            if _PARTIAL_RE.search(stripped):
                partial = True
                continue
            node = CriterionNode(kind=kind, text=stripped, indent=len(raw) - len(raw.lstrip()), marker="text",
                                 cohort=cohort)
            roots.append(node)
            prev = node
            continue

        indent = len(m.group("indent"))
        body = m.group("text").strip()
        marker = "*"
        number = None
        if m.group("num"):
            marker, number = "num", _num(m.group("num"))
        elif m.group("numc"):
            marker, number = "numc", _num(m.group("numc"))
        elif m.group("let"):
            marker = "let"
        inner = _INNER_NUM_RE.match(body)
        if marker == "*" and inner:
            marker, number, body = "num", int(inner.group("num")), inner.group("text").strip()
        if not body or body in {"-", "N/A", "None"}:
            continue
        node = CriterionNode(kind=kind, text=body, indent=indent, marker=marker, number=number, cohort=cohort)

        parent = _choose_parent(prev, node)
        if parent is None:
            roots.append(node)
        else:
            node.parent = parent
            parent.children.append(node)
        prev = node
    return roots, partial, cohorts


def _num(s: str) -> int | None:
    digits = re.match(r"\d+", s)
    return int(digits.group(0)) if digits else None


def _ends_with_colon(n: CriterionNode) -> bool:
    return bool(re.search(r"(:|defined as|as evidenced by|including)\s*$", n.text.strip(), re.I))


def _choose_parent(prev: CriterionNode | None, node: CriterionNode) -> CriterionNode | None:
    if prev is None:
        return None
    if _ends_with_colon(prev) and (node.indent > prev.indent or node.marker != prev.marker):
        return prev
    # sibling of the nearest ancestor-or-self with the same marker and same indent / numbering continuity
    cur: CriterionNode | None = prev
    while cur is not None:
        if cur.marker == node.marker and (
            cur.indent == node.indent
            or (cur.number is not None and node.number is not None and node.number == cur.number + 1)
        ):
            return cur.parent
        cur = cur.parent
    if node.indent > prev.indent:
        return prev
    # fall back to the closest ancestor whose indent is smaller than ours
    cur = prev.parent
    while cur is not None and cur.indent >= node.indent:
        cur = cur.parent
    return cur


def _finalize(parsed: ParsedCriteria) -> None:
    counter = 0

    def rec(nodes: list[CriterionNode], depth: int):
        nonlocal counter
        for n in nodes:
            counter += 1
            n.ordinal = counter
            n.depth = depth
            if n.children:
                n.is_group = bool(_GROUP_TAIL_RE.search(n.text) or _GROUP_ANY_RE.search(n.text))
                # An exclusion group applies if any listed item applies ("..., including:").
                n.logic = "any" if (_GROUP_ANY_RE.search(n.text) or n.kind == "exclusion") else "all"
            rec(n.children, depth + 1)

    rec(parsed.inclusion, 0)
    rec(parsed.exclusion, 0)
