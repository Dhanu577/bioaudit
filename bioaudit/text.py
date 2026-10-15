"""Tokenisation helpers shared by claim extraction and matching."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    "per a an and are as at be by for from has have in into is it its of on or that the their "
    "then this to was were which with we our us than also each all any can may used using "
    "use set value values number".split()
)
# Tokens that say nothing about *which* parameter a constant is.
GENERIC = frozenset({"value", "num", "number", "default", "param", "parameter", "const", "val", "var", "opt",
                     "change", "fold", "log", "log2", "gene", "sample", "estimate", "data", "test", "analysis",
                     "expression", "model", "group", "type", "name", "result", "output", "input",
                     "total", "processed", "finished", "checked", "counter", "idx", "index",
                     "distribution", "empirical", "background"})
# Meaningful but shared by many unrelated constants; cannot alone justify a MISMATCH.
WEAK = frozenset({"threshold", "cutoff", "minimum", "maximum", "size", "length", "n", "k", "count", "limit", "max", "min",
                  "mean", "median", "level", "rate", "high", "low", "quantile", "percentile", "byte", "bit"})

_ALIAS_GROUPS = {
    "threads": "thread nthread core ncore worker job njob cpu ncpu parallel",
    "fdr": "fdr alpha padj pval pvalue significance qvalue qval signif",
    "quality": "qual quality qualified phred",
    "minimum": "min minimum minimal least lower",
    "maximum": "max maximum most upper",
    "neighbors": "neighbor neighbour nn knn",
    "components": "comp component npc dim dimension",
    "iterations": "iter iteration niter maxit",
    "seed": "seed state randomstate",
    "permutations": "perm permutation nperm",
    "bootstrap": "boot bootstrap nboot resample",
    "trees": "tree ntree estimator nestimator",
    "depth": "depth maxdepth",
    "batch": "batch batchsize",
    "length": "len length",
    "variance": "var variance",
}
_ALIAS = {tok: canon for canon, toks in _ALIAS_GROUPS.items() for tok in toks.split()}
# "minimum"/"maximum" tokens are WEAK, so keep the canonical names in WEAK too.
WEAK = WEAK | {"minimum", "maximum"}


def singular(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def canonical(token: str) -> str:
    token = singular(token.lower())
    return _ALIAS.get(token, token)


def split_identifier(name: str) -> list[str]:
    """snake_case, dotted.names, camelCase and digit boundaries -> lower tokens."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+|\s+", spaced) if t]


def _keep(token: str) -> bool:
    # Drop 1-2 letter fragments (loop counters, 'i', 'm', 'sq') unless they are known aliases.
    return len(token) >= 3 or token in _ALIAS


def identifier_tokens(name: str, alias: bool = True) -> set[str]:
    toks = [t for t in split_identifier(name) if not t.isdigit()]
    return {canonical(t) if alias else singular(t) for t in toks if _keep(t)}


def words(text: str) -> list[str]:
    text = re.sub(r"(?i)\b([pq])[- ]?values?\b", lambda m: m.group(1).lower() + "value", text)
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9]*", text)]


def context_tokens(text: str, alias: bool = True) -> set[str]:
    return {canonical(w) if alias else singular(w) for w in words(text) if w not in STOPWORDS and _keep(w)}
