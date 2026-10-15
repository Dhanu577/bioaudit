from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .audit import run_audit
from .ingest import load_paper, open_repository, sha256_bytes, tree_hash
from .report import render_json, render_text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bioaudit", description="Check a paper's parameters and methods against its code.")
    ap.add_argument("paper", help="paper .pdf or .txt")
    ap.add_argument("repo", help="repository directory, .zip, or git URL")
    ap.add_argument("-o", "--output", default="audit_report.txt")
    ap.add_argument("--json", dest="json_out", help="also write a JSON report")
    ap.add_argument("--rev", help="git commit/tag to check out (git URLs only)")
    ap.add_argument("--tool", action="append", help="name(s) the audited tool goes by (default: inferred from the repo folder)")
    ap.add_argument("--include-tests", action="store_true", help="also scan test/example/doc directories")
    args = ap.parse_args(argv)
    try:
        paper_text = load_paper(args.paper)
        with open_repository(args.repo, args.rev) as (root, source):
            report = run_audit(paper_text, root, include_tests=args.include_tests, tool_names=args.tool)
            report.meta.update({
                "Tool version": __version__,
                "Paper SHA-256": sha256_bytes(Path(args.paper).read_bytes()),
                "Repository source": source,
                "Repository tree SHA-256": tree_hash(root, args.include_tests),
            })
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    Path(args.output).write_text(render_text(report), encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(render_json(report), encoding="utf-8")
    c = report.counts()
    print(f"wrote {args.output}  numbers={c['number']}  concepts={c['concept']}")
    return 1 if any(i.verdict in ("MISMATCH", "PARTIAL_MATCH") for i in report.items) else 0
