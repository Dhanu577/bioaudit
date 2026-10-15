"""Plain-text and JSON rendering. Output contains no timestamps or absolute paths."""
from __future__ import annotations

import json

from .audit import SEVERITY_ORDER, Report

CONDENSED = {"RESULT_NEEDS_RUN", "VALUE_PRESENT_UNRELATED"}

PREAMBLE = (
    "HOW TO READ THIS REPORT\n"
    "  Verdicts come from static analysis of Python (AST), R and C/C++ (patterns). Nothing is executed.\n"
    "  MATCH / CALL_FOUND mean 'consistent evidence located', not 'correct'. NOT_FOUND means the scanners\n"
    "  did not see it, not that it is absent. MISMATCH is the highest-value finding: review it first.\n"
    "  Methods are checked only for concepts in bioaudit/knowledge.py; other claims are not scored.\n"
)


def render_json(report: Report) -> str:
    data = {
        "meta": report.meta,
        "files_scanned": report.files,
        "unparsed_files": report.unparsed,
        "warnings": report.warnings,
        "counts": report.counts(),
        "items": [
            {
                "kind": i.kind, "key": i.key, "claim_id": i.claim_id, "claim": i.claim,
                "verdict": i.verdict, "detail": i.detail,
                "evidence": [{"path": e.path, "line": e.line, "text": e.text} for e in i.evidence],
            }
            for i in report.items
        ],
    }
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_text(report: Report) -> str:
    out = ["BIOAUDIT v2 REPORT", "=" * 18]
    out += [f"{k}: {v}" for k, v in sorted(report.meta.items())]
    out.append(f"Files scanned: {', '.join(f'{k}={v}' for k, v in sorted(report.files.items())) or 'none'}")
    if report.unparsed:
        out.append("Unparsed: " + ", ".join(report.unparsed[:10]))
    out += ["", PREAMBLE]
    for w in report.warnings:
        out.append(f"WARNING: {w}")
    counts = report.counts()
    out += ["SUMMARY"]
    for kind, label in (("number", "Parameter/result numbers"), ("concept", "Method concepts")):
        row = " | ".join(f"{v} {n}" for v, n in sorted(counts[kind].items(), key=lambda x: SEVERITY_ORDER.index(x[0])))
        out.append(f"  {label}: {row or 'none'}")
    for verdict in SEVERITY_ORDER:
        group = [i for i in report.items if i.verdict == verdict]
        if not group:
            continue
        out += ["", f"{verdict} ({len(group)})", "-" * (len(verdict) + 6)]
        if verdict in CONDENSED:
            for i in group:
                out.append(f"[{i.kind}] {i.key}: {i.claim[:110]}")
            continue
        for i in group:
            out.append(f"[{i.kind}] {i.key}  (claim {i.claim_id})")
            out.append(f"  Paper:  {i.claim[:240]}")
            out.append(f"  Result: {i.detail}")
            for e in i.evidence:
                out.append(f"  Code:   {e.path}:{e.line}  {e.text}")
    return "\n".join(out) + "\n"
