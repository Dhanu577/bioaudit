"""Compare extracted claims against code facts and assign evidence-based verdicts."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import knowledge
from .claims import Claim, NumberRef, extract_claims
from .scan import Fact, ScanResult, scan_repository
import re

from .text import GENERIC, WEAK, identifier_tokens

# Verdict vocabulary (no percentages, no "confidence").
MATCH = "MATCH"                      # same value under a related parameter name
MISMATCH = "MISMATCH"                # related parameter exists, different value
NOT_FOUND = "NOT_FOUND"              # nothing related in scanned code
PARTIAL_MATCH = "PARTIAL_MATCH"  # value found, but the same variable is assigned a different literal elsewhere
LITERAL_FOUND = "LITERAL_FOUND"  # value appears inline on a line that mentions related terms
VALUE_UNRELATED = "VALUE_PRESENT_UNRELATED"  # number exists, names unrelated (not reassurance)
RESULT_NEEDS_RUN = "RESULT_NEEDS_RUN"        # reported result; cannot be checked statically
CALL_FOUND = "CALL_FOUND"
IMPORT_ONLY = "IMPORT_ONLY"

SEVERITY_ORDER = [MISMATCH, PARTIAL_MATCH, NOT_FOUND, IMPORT_ONLY, VALUE_UNRELATED, RESULT_NEEDS_RUN, LITERAL_FOUND, MATCH, CALL_FOUND]


@dataclass(frozen=True)
class Evidence:
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Item:
    kind: str       # number | concept
    key: str        # raw number text or concept id
    claim_id: str
    claim: str
    verdict: str
    detail: str
    evidence: tuple[Evidence, ...] = ()


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)
    files: dict[str, int] = field(default_factory=dict)
    unparsed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {"number": {}, "concept": {}}
        for it in self.items:
            out[it.kind][it.verdict] = out[it.kind].get(it.verdict, 0) + 1
        return out


def _ev(facts, limit=5) -> tuple[Evidence, ...]:
    return tuple(Evidence(f.path, f.line, f.text) for f in facts[:limit])


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


def _line_tokens(text: str) -> set[str]:
    out: set[str] = set()
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", text):
        out |= identifier_tokens(ident)
    return out


_ASSIGNED = re.compile(r"\s*([A-Za-z_.][\w.]*)\s*(?:<<-|<-|=(?!=))")


def _assigned_var(text: str):
    m = _ASSIGNED.match(text)
    return m.group(1) if m else None


def _looks_like_setting(f: Fact) -> bool:
    """A named option/constant (opts.k = 35, #define, const) rather than a local loop variable."""
    t = f.text
    return bool(re.search(r"(?:\.|->)\s*%s\s*=" % re.escape(f.name), t) or re.match(r"\s*(?:#\s*define|static|const|constexpr|my\s)", t) or f.name.isupper())


def _norm_name(name: str) -> str:
    """DEF_LOAD_FACTOR, load_factor and loadFactor are the same parameter."""
    n = name.lower().replace("_", "").replace(".", "")
    for prefix in ("default", "def"):
        if n.startswith(prefix) and len(n) - len(prefix) >= 3:
            return n[len(prefix):]
    return n


def _same_name_conflicts(names: set[str], consts: list[Fact], ref: NumberRef) -> list[Fact]:
    """Definitions of the same parameter name that carry a different (non-trivial) value."""
    normed = {_norm_name(n) for n in names}
    return [
        c for c in consts
        if _norm_name(c.name) in normed and c.value not in (0.0, 1.0, 2.0, -1.0)
        and not any(_close(v, c.value) for v in ref.values)
    ]


def _partial(ref: NumberRef, other: list[Fact], evidence: list[Fact]):
    where = sorted({f"{f.path}:{f.line} ({f.value:g})" for f in other})
    return (
        PARTIAL_MATCH,
        f"Value {ref.raw} found, but the same parameter is also defined with a different value at: "
        f"{', '.join(where[:5])}. Review: the code may be internally inconsistent (or these may be different contexts).",
        _ev(evidence, 3) + _ev(other, 3),
    )


def check_number(ref: NumberRef, consts: list[Fact], literals: list[Fact] = (), const_index=None):
    if ref.kind == "result":
        return RESULT_NEEDS_RUN, "Reported result; verifying it requires running the code on the paper's data.", ()

    if const_index is None:
        const_index = {}
        for c in consts:
            const_index.setdefault((c.path, c.line), []).append(c)
    value_hits = [f for f in consts if any(_close(v, f.value) for v in ref.values)]
    related: list[tuple[Fact, set[str]]] = []
    sym_facts = [f for f in consts if ref.symbol and f.name.lower() == ref.symbol]
    trivial = all(v in (0.0, 1.0, 2.0, -1.0) for v in ref.values)  # ubiquitous values: no aliasing
    context = ref.raw_context if trivial else ref.context
    for f in consts:
        overlap = (identifier_tokens(f.name, alias=not trivial) & context) - GENERIC
        if trivial:
            overlap -= WEAK  # 0/1/2 need a specific shared name, not just 'threshold'
        if overlap:
            related.append((f, overlap))

    strong_matches = [f for f, ov in related if f in value_hits and (ov - WEAK)]
    matches = [f for f, _ in related if f in value_hits] + [f for f in sym_facts if f in value_hits]
    matches = list(dict.fromkeys(matches))
    if matches:
        # only generic words ('cutoff', 'size') link the number: not enough when the matched value is a small round integer
        matches = [f for f in matches if f in strong_matches or f in sym_facts or not (float(f.value).is_integer() and abs(f.value) <= 100)]
    if trivial and ref.values == (0.0,) and matches:
        if not any(len(ov - WEAK) >= 2 for f, ov in related if f in matches):
            matches = []  # a 0 default is not evidence unless the name matches on two specific words
    if matches:
        conflicts = _same_name_conflicts({f.name for f in matches}, consts, ref)
        if conflicts:
            return _partial(ref, conflicts, matches)
        names = sorted({f.name for f in matches})
        others = sorted({f"{f.name}={f.value:g}" for f, _ in related if f not in value_hits})
        extra = f" Other related constants: {', '.join(others[:5])}." if others else ""
        return MATCH, f"Value found under related name(s): {', '.join(names)}.{extra}", _ev(matches)

    if not trivial:
        def _supported(f: Fact) -> bool:
            # two specific terms shared with the line, or one shared with the *name* of the
            # constant that carries this very value on that line
            if len((_line_tokens(f.text) & ref.sentence_context) - GENERIC - WEAK) >= 2:
                return True
            return any(
                any(_close(v, c.value) for v in ref.values)
                and (identifier_tokens(c.name) & ref.sentence_context) - GENERIC
                for c in const_index.get((f.path, f.line), [])
            )

        lit = [f for f in literals if any(_close(v, f.value) for v in ref.values) and _supported(f)]
        if lit:
            variables = {v for v in (_assigned_var(f.text) for f in lit) if v}
            siblings = [
                f for f in literals
                if f not in lit and f.value not in (0.0, 1.0, 2.0)
                and not any(_close(v, f.value) for v in ref.values)
                and _assigned_var(f.text) in variables
            ]
            on_lines = {(f.path, f.line) for f in lit}
            names = {c.name for c in consts if (c.path, c.line) in on_lines and any(_close(v, c.value) for v in ref.values)}
            siblings += _same_name_conflicts(names, consts, ref)
            if siblings:
                return _partial(ref, siblings, lit)
            return LITERAL_FOUND, "Value appears as an inline literal on line(s) mentioning related terms (no named constant).", _ev(lit)

    if trivial:
        strong = [f for f, ov in related if ov - WEAK]
    else:  # MISMATCH is a negative claim: demand the name overlap inside the number's own clause
        strong = [f for f in consts if (identifier_tokens(f.name) & ref.clause_context) - GENERIC - WEAK]
        strong += [f for f in sym_facts if f not in strong and _looks_like_setting(f)]
    # 0 / -1 initialisers (counters, flags, accumulators) are never evidence of a *different setting*
    strong = [f for f in strong if f.value not in (0.0, -1.0)]
    if max(ref.values) >= 50:
        strong = [f for f in strong if f.value != 1.0]  # a flag/counter of 1 says nothing about a large claimed number
    if trivial:
        strong = []  # a claimed 0, 1 or 2 is too common to call a *different setting* a mismatch
    if strong:
        found = sorted({f"{f.name}={f.value:g}" for f in strong})
        return (
            MISMATCH,
            f"Paper states {ref.raw}; code defines related parameter(s) with other values: "
            f"{', '.join(found[:6])}. Check for multiple definitions or CLI overrides before concluding.",
            _ev(strong),
        )
    if trivial:
        return None  # 0/1/2 elsewhere in the code say nothing about this claim
    if value_hits:
        return VALUE_UNRELATED, "The number occurs in code, but under names unrelated to the claim context.", _ev(value_hits, 3)
    return NOT_FOUND, "No related parameter or matching value found in scanned code.", ()


def _name_matches(fact_name: str, pattern: str) -> bool:
    f, p = fact_name.lower(), pattern.lower()
    return f == p or f.endswith("." + p) or f.endswith("::" + p)


def check_concept(concept: knowledge.Concept, facts: list[Fact]) -> tuple[str, str, tuple[Evidence, ...]]:
    calls = [f for f in facts if f.kind == "call" and any(_name_matches(f.name, p) for p in concept.calls)]
    if calls:
        names = sorted({f.name for f in calls})
        return CALL_FOUND, f"Call(s) found: {', '.join(names[:6])}. Presence of a call does not show correct use.", _ev(calls)
    imports = [
        f for f in facts
        if f.kind == "import" and any(_name_matches(f.name, p) for p in (*concept.calls, *concept.imports))
    ]
    if imports:
        return IMPORT_ONLY, "Related package/symbol is imported but no related call was found.", _ev(imports, 3)
    return NOT_FOUND, f"None of the expected calls ({', '.join(concept.calls[:5])}...) were found.", ()


def audit_claims(claims: list[Claim], scan: ScanResult) -> Report:
    report = Report(files=dict(scan.files), unparsed=list(scan.unparsed))
    consts = [f for f in scan.facts if f.kind == "const" and f.value is not None]
    literals = [f for f in scan.facts if f.kind == "literal"]
    const_index: dict = {}
    for c in consts:
        const_index.setdefault((c.path, c.line), []).append(c)
    by_id = {c.id: c for c in knowledge.CONCEPTS}
    for claim in claims:
        for ref in claim.numbers:
            checked = check_number(ref, consts, literals, const_index)
            if checked is None:
                continue
            verdict, detail, ev = checked
            report.items.append(Item("number", ref.raw, claim.id, claim.text, verdict, detail, ev))
        for cid in claim.concepts:
            verdict, detail, ev = check_concept(by_id[cid], scan.facts)
            report.items.append(Item("concept", cid, claim.id, claim.text, verdict, detail, ev))
    if not scan.facts:
        report.warnings.append("No scannable Python/R/C/C++ source found; every verdict below is meaningless.")
    if scan.unparsed:
        report.warnings.append(f"{len(scan.unparsed)} file(s) could not be parsed and were skipped.")
    if not claims:
        report.warnings.append("No checkable claims were extracted from the paper text.")
    return report


def infer_tool_names(root) -> frozenset[str]:
    """Names the audited tool goes by, from the repository directory (and a single nested directory)."""
    from pathlib import Path

    p = Path(root)
    cands = {p.name}
    subs = [d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")] if p.is_dir() else []
    if len(subs) == 1:
        cands.add(subs[0].name)
    names: set[str] = set()
    for c in cands:
        c = c.lower()
        c = re.sub(r"[-_.](master|main|devel|dev|develop)$", "", c)
        c = re.sub(r"[-_]?v?\d+(\.\d+)*$", "", c) if re.search(r"[-_]v?\d+(\.\d+)*$", c) else c
        for variant in {c, re.sub(r"\d+$", "", c), c.split("-")[0], c.replace("-", "")}:
            if variant:
                names.add(variant)
    return frozenset(names)


def run_audit(paper_text: str, repo_root, *, include_tests: bool = False, tool_names=None) -> Report:
    own = infer_tool_names(repo_root) if tool_names is None else frozenset(n.lower() for n in tool_names)
    from . import knowledge

    lowered = paper_text.lower()
    if not (own & knowledge.KNOWN_TOOLS or any(len(n) >= 4 and n in lowered for n in own)):
        own = frozenset()  # cannot tell which name the paper uses for the audited tool: do not filter
    return audit_claims(extract_claims(paper_text, own), scan_repository(repo_root, include_tests))
