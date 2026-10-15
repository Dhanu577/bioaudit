"""Score verdict accuracy against labelled cases.

Case layout:  <cases>/<name>/paper.txt, <name>/repo/..., <name>/expected.json
expected.json: {"expect": [{"kind": "number|concept", "key": "...", "verdict": "..."}],
                "forbid": [{"kind": "...", "key": "..."}]}
The metrics that matter are FALSE REASSURANCE (MATCH/CALL_FOUND predicted when the
label says otherwise) and FALSE ALARM, not overall accuracy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .audit import CALL_FOUND, LITERAL_FOUND, MATCH, MISMATCH, NOT_FOUND, PARTIAL_MATCH, run_audit

REASSURING = {MATCH, CALL_FOUND, LITERAL_FOUND}
ALARMING = {MISMATCH, PARTIAL_MATCH, NOT_FOUND}


def evaluate_cases(cases_dir: str | Path) -> dict:
    rows, forbidden_hits = [], []
    for case in sorted(p for p in Path(cases_dir).iterdir() if p.is_dir()):
        spec = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        report = run_audit((case / "paper.txt").read_text(encoding="utf-8"), case / "repo")
        got = {(i.kind, i.key): i.verdict for i in report.items}
        for e in spec.get("expect", []):
            rows.append((case.name, e["kind"], e["key"], e["verdict"], got.get((e["kind"], e["key"]), "MISSED")))
        for f in spec.get("forbid", []):
            if (f["kind"], f["key"]) in got:
                forbidden_hits.append((case.name, f["kind"], f["key"]))
    correct = sum(r[3] == r[4] for r in rows)
    false_reassurance = [r for r in rows if r[4] in REASSURING and r[3] != r[4]]
    false_alarm = [r for r in rows if r[4] in ALARMING and r[3] in REASSURING]
    per_verdict = {}
    for v in sorted({r[3] for r in rows} | {r[4] for r in rows}):
        tp = sum(r[3] == v and r[4] == v for r in rows)
        pred, true = sum(r[4] == v for r in rows), sum(r[3] == v for r in rows)
        per_verdict[v] = {"precision": tp / pred if pred else None, "recall": tp / true if true else None, "support": true}
    return {
        "n": len(rows), "correct": correct, "accuracy": correct / len(rows) if rows else None,
        "false_reassurance": false_reassurance, "false_alarm": false_alarm,
        "forbidden_hits": forbidden_hits, "per_verdict": per_verdict,
        "errors": [r for r in rows if r[3] != r[4]],
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    res = evaluate_cases(args[0] if args else "validation/cases")
    fmt = lambda x: "n/a" if x is None else f"{x:.2f}"
    print(f"labelled items: {res['n']}   exact verdicts: {res['correct']}   accuracy: {fmt(res['accuracy'])}")
    print(f"FALSE REASSURANCE: {len(res['false_reassurance'])}   FALSE ALARM: {len(res['false_alarm'])}   forbidden hits: {len(res['forbidden_hits'])}")
    for v, m in res["per_verdict"].items():
        print(f"  {v:24s} precision={fmt(m['precision'])} recall={fmt(m['recall'])} support={m['support']}")
    for r in res["errors"]:
        print("  ERROR case=%s %s=%s expected=%s got=%s" % (r[0], r[1], r[2], r[3], r[4]))
    return 1 if res["false_reassurance"] or res["forbidden_hits"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
