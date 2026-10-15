"""Extract checkable claims: parameter values and method statements."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace

from . import knowledge
from .text import GENERIC, WEAK, context_tokens

SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")

RESULT_RE = re.compile(
    r"collision|identify|faster|slower|speed|accuracy|sensitivity|specificity|precision|recall|\bf1\b|\bauc\b|auroc|"
    r"outperform|improv|reduc|runtime|run time|seconds?|minutes?|hours?|\b[gm]b\b|"
    r"times (?:faster|slower|more|less)|false[- ]positive|detected|identified|achiev|reached|yield",
    re.I,
)
PARAM_RE = re.compile(
    r"threshold|cut-?off|default|set to|set at|parameter|window|size|length|minimum|minimal|maximum|"
    r"at least|at most|up to|resolution|neighbo|component|iteration|seed|thread|core|\bper\b|batch|"
    r"pack|alpha|fdr|p-value|padj|trim|quality|phred|\bbins?\b|learning rate|epoch|depth|trees|"
    r"permutation|bootstrap|fold[- ]change|filter|removed|discard|retain|\bk\s*=|quantile|percentile",
    re.I,
)
SKIP_PREFIX = {
    "fig", "figure", "figs", "table", "tables", "eq", "equation", "step", "section", "supplementary",
    "panel", "ref", "refs", "reference", "page", "pp", "chapter", "version", "v", "file", "files",
}
BRACKET_CITE_RE = re.compile(r"\[[\d,\s\-–]+\]")
POW_RE = re.compile(r"(?<![\d.])10\s*(?:\^\s*\{?\s*([-−–]?\d+)\s*\}?|([−–])\s*(\d+)|⁻([⁰¹²³⁴⁵⁶⁷⁸⁹]+))")
NUM_RE = re.compile(
    r"(?<![\w.\-−])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?(?:[eE][-+−]?\d+)?)"
    r"(?P<suffix>\s?%|\s?(?:×|x)(?![A-Za-z]))?"
)
NUM_COMPARISON_RE = re.compile(r"compar(?:e|es|ed|ing|ison)|versus|\bvs\.?\b|other (?:tools|algorithms|methods)|existing (?:tools|methods)", re.I)
ABBREV_RE = re.compile(r"\b(e\.g|i\.e|et al|vs|fig|figs|eq|approx|ca|cf|no|dr|prof)\.", re.I)


@dataclass(frozen=True)
class NumberRef:
    raw: str
    values: tuple[float, ...]
    context: frozenset[str]
    raw_context: frozenset[str]
    sentence_context: frozenset[str]
    clause_context: frozenset[str]  # strictly the clause around the number (used for MISMATCH)
    kind: str  # parameter | result | other
    symbol: str = ""  # 'k' for 'k = 35' (single-letter parameter names)


@dataclass(frozen=True)
class MethodRef:
    concept: str


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    numbers: tuple[NumberRef, ...]
    concepts: tuple[str, ...]


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=[a-z])", "", text)  # de-hyphenate line breaks
    text = re.sub(r"_x[0-9A-Fa-f]{4}_", " ", text)  # PDF extraction junk
    text = text.replace("¼", "=").replace("þ", "+")  # glyphs some PDFs use for "=" and "+"
    text = re.sub(r"https?://\S+|www\.\S+|doi:\s*\S+|\b10\.\d{4,9}/\S+|\S+@\S+\.\S+", " ", text)  # URLs, DOIs, e-mails
    text = re.sub(r"\b(\d) (\d) (\d) (\d)\b", r"\1\2\3\4", text)  # years split by PDF spacing: "2 0 1 7"
    text = re.sub(r"\b([35])\s0(?=\s*(?:to\b|end|ends|-|,|\.|\)|UTR|primer))", lambda m: m.group(1) + "′", text)  # 5' / 3' with the prime lost
    text = re.sub(r"\b([35])0 to ([35])0\b", lambda m: m.group(1) + "′ to " + m.group(2) + "′", text)  # "30 to 50" is 3' to 5' 
    text = re.sub(r"\bof 2 (\d{2})\b", r"of 2^\1", text)  # "size of 2 24" is 2^24
    counts: dict[str, int] = {}
    for ln in text.split("\n"):
        key = ln.strip()
        if len(key) >= 10:
            counts[key] = counts.get(key, 0) + 1
    text = "\n".join(ln for ln in text.split("\n") if counts.get(ln.strip(), 0) < 3)  # running headers/footers
    text = re.sub(r"\b[A-Z][A-Za-z\-]+ et al\.? (?:Genome Biology|Genome Research|Bioinformatics|Nucleic Acids Research|Nature Methods|BMC Bioinformatics|Scientific Reports)\b", " ", text)
    text = re.sub(r"\bPage \d+ of \d+\b", " ", text)          # running footers
    text = re.sub(r"\(\d{4}\)\s*\d+:\d+", " ", text)              # journal (2014) 15:550 headers
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.fullmatch(r"\s*(references|bibliography|literature cited|acknowledg(?:e)?ments)\s*", line, re.I):
            lines = lines[:i]
            break
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def split_sentences(text: str) -> list[str]:
    protected = ABBREV_RE.sub(lambda m: m.group(0).replace(".", "§"), text)
    protected = re.sub(r"(?<=\d)\.(?=\d)", "§", protected)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", protected)
    return [p.replace("§", ".").strip() for p in parts if len(p.split()) >= 4]


def _parse_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "").replace("−", "-"))
    except ValueError:
        return None


def _window(sentence: str, start: int, end: int, n: int) -> str:
    left = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", sentence[:start])[-n:]
    right = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", sentence[end:])[:n]
    return " ".join(left + right)


def _clause_window(sentence: str, start: int, end: int, n: int) -> str:
    """Words near the number, not crossing commas/semicolons/parentheses."""
    left = re.split(r"[,;:()]", sentence[:start])[-1]
    right = re.split(r"[,;:()]", sentence[end:])[0]
    lw = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", left)[-n:]
    rw = re.findall(r"[A-Za-z][A-Za-z0-9\-]*", right)[:n]
    return " ".join(lw + rw)


def _numbers_in(sentence: str) -> list[NumberRef]:
    if len(NUM_RE.findall(sentence)) > 8 or len(sentence) > 900:
        return []  # axis labels, table rows or glued figure text, not prose
    sentence_ctx = frozenset(context_tokens(sentence))
    masked: list[tuple[int, int]] = [m.span() for m in BRACKET_CITE_RE.finditer(sentence)]
    refs: list[NumberRef] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < y and x < b for x, y in masked)

    experiment = bool(re.search(knowledge.EXPERIMENT_RE, sentence, re.I))

    def classify(start: int, end: int):
        win4, win8 = _window(sentence, start, end, 4), _window(sentence, start, end, 8)
        if experiment or NUM_COMPARISON_RE.search(sentence):
            kind = "result"
        elif RESULT_RE.search(win4):
            kind = "result"
        elif PARAM_RE.search(win8):
            kind = "parameter"
        elif RESULT_RE.search(sentence):
            kind = "result"
        else:
            kind = "other"
        clause = _clause_window(sentence, start, end, 8)
        if not (context_tokens(clause) - GENERIC - WEAK):
            clause = win8  # clause has nothing specific: fall back to the wider window
        clause_only = frozenset(context_tokens(_clause_window(sentence, start, end, 8)))
        return kind, frozenset(context_tokens(clause)), frozenset(context_tokens(clause, alias=False)), clause_only

    pvalue_cue = bool(re.search(r"p-?value|cutoff|cut-off|threshold|default|\bFDR\b|<", sentence, re.I))
    if pvalue_cue:  # "10-5" / "10 -5" with the superscript lost in the PDF
        for m in re.finditer(r"(?<![\d.])10\s?-\s?([1-9]\d?)(?!\d)", sentence):
            masked.append(m.span())
            kind, ctx, raw, strict = classify(*m.span())
            refs.append(NumberRef(m.group(0).strip(), (10.0 ** -int(m.group(1)),), ctx, raw, sentence_ctx, strict, kind))

    for m in POW_RE.finditer(sentence):
        if overlaps(*m.span()):
            continue
        if m.group(1):
            exp = int(m.group(1).replace("−", "-").replace("–", "-"))
        elif m.group(2):
            exp = -int(m.group(3))
        else:
            exp = -int(m.group(4).translate(SUPERSCRIPT))
        masked.append(m.span())
        kind, ctx, raw, strict = classify(*m.span())
        refs.append(NumberRef(m.group(0).strip(), (10.0 ** exp,), ctx, raw, sentence_ctx, strict, kind))

    for m in NUM_RE.finditer(sentence):
        if overlaps(*m.span()):
            continue
        prev = re.findall(r"[A-Za-z]+", sentence[: m.start()])[-1:]
        if prev and (prev[0].lower() in SKIP_PREFIX or re.search(r"(?:figure|table|fig|section|eq|file)$", prev[0].lower())):
            continue
        value = _parse_number(m.group("num"))
        if value is None:
            continue
        suffix = (m.group("suffix") or "").strip()
        before, after = sentence[: m.start()].rstrip(), sentence[m.end():].lstrip()
        if not suffix and before.endswith(".") and (re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?", m.group("num"))) and value <= 12 and after[:1].isalpha():
            continue  # heading number glued to the previous sentence: "... ends. 2.5 polyG trimming"
        if not suffix and (before[-1:] in "/*^+" or re.match(r"[A-Z](?![A-Za-z])", after)) and not before.endswith("e"):
            continue  # part of a formula such as 4Y/0.7, or a coefficient of a variable ("12 X")
        if re.match(r"\s+(?:sequencing|platform)\b", after):
            continue  # "454 sequencing" is a platform name
        if after[:1] in ("\u2032", "'", "\u2019"):
            continue  # 5' / 3' end notation
        nxt_word = re.match(r"([A-Z][A-Za-z]+)", after)
        if not suffix and nxt_word and (
            (re.fullmatch(r"\d{1,2}\.\d{1,2}", m.group("num")) and after[:1].isupper())
            or (value.is_integer() and value <= 9 and len(nxt_word.group(1)) >= 4 and not nxt_word.group(1).isupper())
        ):
            continue  # section heading such as "2.1 Overall design" or "1 Introduction"
        prev_word = re.findall(r"[A-Za-z]+", sentence[: m.start()])[-1:]
        if (not suffix and value.is_integer() and 1 <= value <= 9 and prev_word
                and prev_word[0][:1].isupper() and sentence[: m.start()].rstrip().endswith(prev_word[0])
                and sentence[: m.start()].rstrip()[:-len(prev_word[0])].strip() != ""):
            continue  # tool name with a version digit: "Kraken 2", "Cuffdiff 2"
        if value in (0.0, 1.0, 2.0) and not suffix and sentence[m.end():m.end() + 1].isalpha():
            continue  # "2d", "1x"-style multipliers glued to a letter
        if value == 0 and not suffix and before[-1:] in (">", "<", "≥", "≤"):
            continue  # 'theta > 0' states a constraint, not a setting
        if before.endswith("(") and after.startswith(")") and value.is_integer() and value <= 99 and not suffix:
            continue  # equation / reference number such as "(7)"
        if not suffix and value.is_integer() and 1900 <= value <= 2100:
            continue  # publication year
        if suffix in ("×", "x"):
            continue  # fold-change multipliers are results, not parameters
        if value in (0.0, 1.0, 2.0) and not suffix:
            p, n = before[-1:], after[:1]
            if p in "−-+/*^(" or n in "−-+/*^=<>≈≥≤":
                continue  # a number inside a formula such as (1 - p/2), not a setting
        if re.match(r"\s*bytes?\b", after) and not suffix:
            byte_forms = (value * 8,)  # code often stores sizes in bits
        elif re.match(r"\s*bits?\b", after) and not suffix:
            byte_forms = (value / 8,)
        else:
            byte_forms = ()
        if suffix == "%":
            values = (value, value / 100.0) if value not in (0.0, 1.0, 2.0) else (value / 100.0,)
            if re.search(r"quantile|percentile", sentence, re.I):
                values += (1 - value / 100.0, 2 * (1 - value / 100.0))  # p, or two-sided p (97.5% -> 0.05)
        else:
            values = (value,) + byte_forms
        kind, ctx, raw, strict = classify(m.start(), m.end())
        if kind == "result" and not suffix and value in (0.0, 1.0, 2.0):
            continue  # bare 0/1/2 inside result prose carries no checkable content
        sym = re.search(r"(?<![A-Za-z])([A-Za-zℓ])\s*[=≈]\s*$", sentence[: m.start()])
        symbol = ("l" if sym.group(1) == "ℓ" else sym.group(1).lower()) if sym else ""
        refs.append(NumberRef(m.group(0).strip(), values, ctx, raw, sentence_ctx, strict, kind, symbol))
    return refs


def extract_claims(text: str, own_names: frozenset[str] = frozenset()) -> list[Claim]:
    claims: list[Claim] = []
    seen: set[str] = set()
    comparison = re.compile(knowledge.COMPARISON_RE, re.I)
    cue = re.compile(knowledge.IMPLEMENTATION_CUE_RE, re.I)
    for sentence in split_sentences(clean_text(text)):
        cid = hashlib.sha1(sentence.encode()).hexdigest()[:8]
        if cid in seen:
            continue
        seen.add(cid)
        numbers = tuple(n for n in _numbers_in(sentence) if n.kind != "other")
        about_other = False
        if own_names:
            toks = set(re.findall(r"[a-z0-9]+", sentence.lower()))
            toks |= {re.sub(r"\d+$", "", t) for t in toks}
            about_other = bool(toks & knowledge.KNOWN_TOOLS) and not (toks & own_names)
            low = sentence.lower()
            for n in own_names:  # another *version* of the audited tool ("Kraken 1" while auditing Kraken 2)
                mm = re.fullmatch(r"([a-z]+)(\d+)", n)
                if mm and re.search(r"\b%s\s?(?!%s\b)\d\b" % (mm.group(1), mm.group(2)), low) and not re.search(r"\b%s\s?%s\b" % (mm.group(1), mm.group(2)), low):
                    about_other = True
        if about_other:  # sentence is about somebody else's software, not the code being audited
            numbers = tuple(replace(n, kind="result") for n in numbers)
        concepts: tuple[str, ...] = ()
        if cue.search(sentence) and not about_other and not comparison.search(sentence) and not re.search(knowledge.EXPERIMENT_RE, sentence, re.I):
            concepts = tuple(
                c.id for c in knowledge.CONCEPTS if re.search(c.claim_re, sentence, re.I)
            )
        if numbers or concepts:
            claims.append(Claim(cid, sentence, numbers, concepts))
    return claims
