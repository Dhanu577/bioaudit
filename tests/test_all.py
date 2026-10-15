import json
import zipfile
from pathlib import Path

import pytest

from bioaudit.audit import CALL_FOUND, MATCH, MISMATCH, NOT_FOUND, RESULT_NEEDS_RUN, run_audit
from bioaudit.claims import extract_claims
from bioaudit.evaluate import evaluate_cases
from bioaudit.ingest import safe_extract_zip
from bioaudit.scan import scan_cpp_source, scan_python_source, scan_r_source, scan_repository

CASES = Path(__file__).parent.parent / "validation" / "cases"


def verdicts(paper, tmp_path, files):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return {(i.kind, i.key): i.verdict for i in run_audit(paper, tmp_path).items}


# ---- the v1 failure: tool name in a path + an unrelated lm() produced "100% supported"
def test_path_and_unrelated_call_do_not_support_method_claim(tmp_path):
    v = verdicts("We used DESeq2 with a negative binomial model.", tmp_path,
                 {"DESeq2/run.R": "fit <- lm(y ~ x)\n"})
    assert v[("concept", "deseq2")] == NOT_FOUND
    assert v[("concept", "negative_binomial")] == NOT_FOUND


def test_comments_and_strings_do_not_count_as_calls(tmp_path):
    v = verdicts("We used DESeq2 for testing.", tmp_path, {"a.R": "# dds <- DESeq(dds)\nx <- 'DESeq('\n"})
    assert v[("concept", "deseq2")] == NOT_FOUND


def test_numeric_mismatch_and_match(tmp_path):
    paper = "We set the FDR threshold to 0.05."
    assert verdicts(paper, tmp_path / "a", {"x.py": "alpha = 0.05\n"})[("number", "0.05")] == MATCH
    assert verdicts(paper, tmp_path / "b", {"x.py": "alpha = 0.01\n"})[("number", "0.05")] == MISMATCH


def test_value_under_unrelated_name_is_not_a_match(tmp_path):
    v = verdicts("We set the FDR threshold to 0.05.", tmp_path, {"x.py": "learning_rate = 0.05\n"})
    assert v[("number", "0.05")] == "VALUE_PRESENT_UNRELATED"


def test_percent_normalisation(tmp_path):
    v = verdicts("Reads were filtered at a quality threshold of 5%.", tmp_path, {"x.py": "min_quality = 0.05\n"})
    assert v[("number", "5%")] == MATCH


def test_results_are_never_marked_verified(tmp_path):
    v = verdicts("The tool is 2.7 times faster than the baseline.", tmp_path, {"x.py": "x = 2.7\n"})
    assert v[("number", "2.7")] == RESULT_NEEDS_RUN


# ---- extraction
def test_citations_years_and_figure_refs_skipped():
    c = extract_claims("Described previously [12, 14] in 2015. We used 3 replicates per group (Fig. 2).")
    raws = [n.raw for cl in c for n in cl.numbers]
    assert raws == ["3"]


def test_comparison_sentences_do_not_create_method_claims():
    assert extract_claims("We compared our method with edgeR and DESeq2 on many datasets.") == []


def test_scientific_notation_forms():
    c = extract_claims("We used an adjusted p-value cutoff of 10^-5 and a threshold of 1e-3 here.")
    vals = sorted(v for cl in c for n in cl.numbers for v in n.values)
    assert vals == pytest.approx([1e-5, 1e-3]) or vals == pytest.approx([1e-5, 1e-3][::-1]) or set(vals) == {1e-5, 1e-3}


# ---- scanners
def test_python_scanner_finds_defaults_kwargs_argparse():
    src = (
        "import argparse\n"
        "def f(a, threads=4):\n    pass\n"
        "p = argparse.ArgumentParser()\n"
        "p.add_argument('--min-length', default=50, type=int)\n"
        "g(resolution=0.8)\nX = 10 ** -5\n"
    )
    consts = {(f.name, f.value) for f in scan_python_source(src, "x.py") if f.kind == "const"}
    assert {("threads", 4.0), ("min_length", 50.0), ("resolution", 0.8), ("X", 1e-5)} <= consts


def test_r_scanner_handles_assignment_args_and_comments():
    src = "alpha <- 0.05  # 0.9\nres <- results(dds, lfcThreshold = 1)\n"
    f = scan_r_source(src, "a.R")
    assert ("alpha", 0.05) in {(x.name, x.value) for x in f if x.kind == "const"}
    assert ("lfcThreshold", 1.0) in {(x.name, x.value) for x in f if x.kind == "const"}
    assert 0.9 not in {x.value for x in f}


def test_cpp_scanner_defines_members_threads_and_comments():
    src = "// int x = 9;\n#define PACK 1000\nint n = 3;\nstd::thread t(run);\n#pragma omp parallel for\n"
    f = scan_cpp_source(src, "a.cpp")
    assert {("PACK", 1000.0), ("n", 3.0)} <= {(x.name, x.value) for x in f if x.kind == "const"}
    assert {"std::thread", "omp"} <= {x.name for x in f if x.kind == "call"}
    assert 9.0 not in {x.value for x in f}


def test_notebook_code_cells_scanned(tmp_path):
    nb = {"cells": [{"cell_type": "code", "source": ["alpha = 0.05\n"]}, {"cell_type": "markdown", "source": ["alpha = 9"]}]}
    (tmp_path / "n.ipynb").write_text(json.dumps(nb))
    vals = {f.value for f in scan_repository(tmp_path).facts if f.kind == "const"}
    assert vals == {0.05}


def test_unparseable_python_is_reported_not_fatal(tmp_path):
    (tmp_path / "bad.py").write_text("def (:\n")
    assert scan_repository(tmp_path).unparsed == ["bad.py"]


def test_test_directories_ignored_by_default(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("alpha = 0.5\n")
    assert scan_repository(tmp_path).facts == []
    assert scan_repository(tmp_path, include_tests=True).facts


# ---- ingest safety
def test_zip_path_traversal_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.py", "x=1")
    with pytest.raises(ValueError):
        safe_extract_zip(z, tmp_path / "out")


# ---- validation suite is a regression gate
def test_validation_suite_has_no_false_reassurance_or_forbidden_hits():
    res = evaluate_cases(CASES)
    assert res["n"] >= 30
    assert not res["false_reassurance"]
    assert not res["forbidden_hits"]
    assert res["accuracy"] == 1.0, res["errors"]
