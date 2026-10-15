"""Static fact extraction from source code. Nothing is executed."""
from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "third_party", "build", "dist", "__pycache__", ".venv", "venv",
}
TEST_DIRS = {"test", "tests", "testthat", "doc", "docs", "example", "examples", "vignettes", "notebooks", "notebook", "tutorials"}
MAX_BYTES = 2_000_000
LANG_BY_EXT = {
    ".py": "python", ".ipynb": "python", ".r": "r", ".rmd": "r",
    **{e: "cpp" for e in (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")},
    **{e: "script" for e in (".pl", ".pm", ".sh", ".bash")},
}


def _shebang_lang(path: Path) -> str | None:
    """Extension-less launcher scripts (e.g. kraken2-build, k2) are real code: detect them by '#!'."""
    if path.suffix:
        return None
    try:
        head = path.open("rb").read(160).split(b"\n", 1)[0]
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    if b"python" in head:
        return "python"
    if b"perl" in head or b"bash" in head or head.rstrip().endswith(b"sh"):
        return "script"
    return None


@dataclass(frozen=True)
class Fact:
    kind: str  # const | call | import
    name: str
    value: float | None
    path: str
    line: int
    lang: str
    text: str


@dataclass
class ScanResult:
    facts: list[Fact] = field(default_factory=list)
    files: dict[str, int] = field(default_factory=dict)
    unparsed: list[str] = field(default_factory=list)


def iter_source_files(root: Path, include_tests: bool = False):
    skip = SKIP_DIRS if include_tests else SKIP_DIRS | TEST_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in skip)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            lang = LANG_BY_EXT.get(path.suffix.lower()) or _shebang_lang(path)
            if lang and path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES:
                yield path, lang


def _line(lines: list[str], n: int) -> str:
    return lines[n - 1].strip()[:200] if 0 < n <= len(lines) else ""


# ---------------------------------------------------------------- Python (AST)
def _num(node) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _num(node.operand)
        return None if v is None else (-v if isinstance(node.op, ast.USub) else v)
    if isinstance(node, ast.BinOp):
        a, b = _num(node.left), _num(node.right)
        if a is None or b is None:
            return None
        try:
            if isinstance(node.op, ast.Pow):
                return float(a ** b)
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
        except (ArithmeticError, OverflowError, ValueError):
            return None
    return None


def _dotted(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return None


ARG_DECLARERS = {"add_argument", "add_option", "option", "Option", "Argument"}


def scan_python_source(source: str, rel: str) -> list[Fact]:
    tree = ast.parse(source)
    lines = source.splitlines()
    facts: list[Fact] = []
    arithmetic = {id(c) for n in ast.walk(tree) if isinstance(n, ast.BinOp) for c in (n.left, n.right) if isinstance(c, ast.Constant)}

    def const(name: str, value: float, lineno: int):
        facts.append(Fact("const", name, value, rel, lineno, "python", _line(lines, lineno)))

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool) and id(node) not in arithmetic:
            facts.append(Fact("literal", "", float(node.value), rel, node.lineno, "python", _line(lines, node.lineno)))
        if isinstance(node, ast.Assign):
            value = _num(node.value)
            if value is not None:
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        const(t.id, value, node.lineno)
                    elif isinstance(t, ast.Attribute):
                        const(t.attr, value, node.lineno)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            value = _num(node.value)
            if value is not None and isinstance(node.target, (ast.Name, ast.Attribute)):
                const(getattr(node.target, "id", None) or node.target.attr, value, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            pos = node.args.args[len(node.args.args) - len(node.args.defaults):]
            for arg, default in zip(pos, node.args.defaults):
                if (v := _num(default)) is not None:
                    const(arg.arg, v, node.lineno)
            for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                if default is not None and (v := _num(default)) is not None:
                    const(arg.arg, v, node.lineno)
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name:
                facts.append(Fact("call", name, None, rel, node.lineno, "python", _line(lines, node.lineno)))
            for kw in node.keywords:
                if kw.arg and (v := _num(kw.value)) is not None:
                    const(kw.arg, v, node.lineno)
            if name and name.split(".")[-1] in ARG_DECLARERS and node.args:
                first = node.args[0]
                default = next((_num(k.value) for k in node.keywords if k.arg == "default"), None)
                if isinstance(first, ast.Constant) and isinstance(first.value, str) and default is not None:
                    const(first.value.lstrip("-").replace("-", "_"), default, node.lineno)
        elif isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and (n := _num(v)) is not None:
                    const(k.value, n, node.lineno)
        elif isinstance(node, ast.Import):
            for a in node.names:
                facts.append(Fact("import", a.name, None, rel, node.lineno, "python", _line(lines, node.lineno)))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            facts.append(Fact("import", mod, None, rel, node.lineno, "python", _line(lines, node.lineno)))
            for a in node.names:
                facts.append(Fact("import", a.name, None, rel, node.lineno, "python", _line(lines, node.lineno)))
    return facts


def _notebook_source(raw: str) -> str:
    nb = json.loads(raw)
    cells = ["".join(c.get("source", [])) for c in nb.get("cells", []) if c.get("cell_type") == "code"]
    return "\n".join(line for cell in cells for line in cell.splitlines() if not line.lstrip().startswith(("%", "!")))


# ------------------------------------------------------------------------- R
R_NUM = r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
# The number must END the expression: `x <- -1 * y` and `size = 1 / a` are not constants.
R_ASSIGN = re.compile(r"(?<![\w.])([A-Za-z.][\w.]*)\s*(?:<<-|<-|=(?!=))\s*(" + R_NUM + r")L?(?![\w.])(?=\s*(?:[,;)}\]]|$))")
R_CALL = re.compile(r"(?<![\w.$@])([A-Za-z.][\w.]*(?:::{1,2}[A-Za-z.][\w.]*)?)\s*\(")
R_LIB = re.compile(r"\b(?:library|require|requireNamespace|loadNamespace)\(\s*[\"']?([A-Za-z.][\w.]*)")
R_NS = re.compile(r"\b([A-Za-z.][\w.]*)::")
LIT_RE = re.compile(r"(?<![\w.])(\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![\w.])")
def _standalone_literal(text: str, m) -> bool:
    prev, nxt = text[: m.start()].rstrip()[-1:], text[m.end():].lstrip()[:1]
    return prev not in "*/+-^%" and nxt not in "*/+-^%"


R_KEYWORDS = {"if", "for", "while", "function", "return", "switch", "repeat"}


def _r_views(source: str) -> tuple[str, str]:
    """Return (comments removed, comments removed + string contents blanked), newline-aligned.

    String state is carried across lines so text inside multi-line strings is never code.
    """
    with_s: list[str] = []
    blank: list[str] = []
    quote = None
    comment = False
    escaped = False
    for ch in source:
        nl = ch == "\n"
        if comment:
            if nl:
                comment = False
                with_s.append(ch)
                blank.append(ch)
            continue
        if quote:
            with_s.append(ch)
            if escaped:
                escaped = False
                blank.append("\n" if nl else " ")
            elif ch == "\\":
                escaped = True
                blank.append(" ")
            elif ch == quote:
                quote = None
                blank.append(ch)
            else:
                blank.append("\n" if nl else " ")
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "#":
            comment = True
            continue
        with_s.append(ch)
        blank.append(ch)
    return "".join(with_s), "".join(blank)


def scan_r_source(source: str, rel: str) -> list[Fact]:
    facts: list[Fact] = []
    with_strings, blanked = _r_views(source)
    originals = source.splitlines()
    for n, (ws, line) in enumerate(zip(with_strings.splitlines(), blanked.splitlines()), 1):
        text = originals[n - 1].strip()[:200] if n <= len(originals) else ""
        for m in R_ASSIGN.finditer(line):
            facts.append(Fact("const", m.group(1), float(m.group(2)), rel, n, "r", text))
        for m in LIT_RE.finditer(line):
            if _standalone_literal(line, m):
                facts.append(Fact("literal", "", float(m.group(0)), rel, n, "r", text))
        for m in R_CALL.finditer(line):
            if m.group(1) not in R_KEYWORDS:
                facts.append(Fact("call", m.group(1), None, rel, n, "r", text))
        for m in R_LIB.finditer(ws):
            facts.append(Fact("import", m.group(1), None, rel, n, "r", text))
        for m in R_NS.finditer(line):
            facts.append(Fact("import", m.group(1), None, rel, n, "r", text))
    return facts


# --------------------------------------------------------------------- C/C++
C_NUM = r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
C_DEFINE = re.compile(rf"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+\(?[ \t]*({C_NUM})[uUlLfF]*[ \t]*\)?[ \t]*$", re.M)
C_ASSIGN = re.compile(rf"(?<![\w])([A-Za-z_]\w*)\s*(?:\[\s*\w*\s*\])?\s*=(?!=)\s*\(?\s*(-?{C_NUM})[uUlLfF]*\s*\)?\s*(?=[;,)])")
C_CALL = re.compile(r"(?<![\w])([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\(")
C_INCLUDE = re.compile(r"^[ \t]*#[ \t]*include[ \t]*[<\"]([^>\"]+)", re.M)
C_STD_THREAD = re.compile(r"\bstd::(thread|jthread|async)\b")
C_OMP = re.compile(r"^[ \t]*#[ \t]*pragma[ \t]+omp\b", re.M)
C_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch", "defined", "alignof", "decltype"}


def _strip_c_comments(src: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)


def _blank_c_strings(code: str) -> str:
    out, quote, esc = [], None, False
    for ch in code:
        if quote:
            if esc:
                esc = False
                out.append("\n" if ch == "\n" else " ")
            elif ch == "\\":
                esc = True
                out.append(" ")
            elif ch == quote:
                quote = None
                out.append(ch)
            else:
                out.append("\n" if ch == "\n" else " ")
        else:
            if ch in "\"'":
                quote = ch
            out.append(ch)
    return "".join(out)


def scan_cpp_source(source: str, rel: str) -> list[Fact]:
    code_with_strings = _strip_c_comments(source)
    code = _blank_c_strings(code_with_strings)  # string contents never count as code
    lines = code_with_strings.splitlines()
    facts: list[Fact] = []

    def add(kind, name, value, m):
        n = code.count("\n", 0, m.start()) + 1
        facts.append(Fact(kind, name, value, rel, n, "cpp", _line(lines, n)))

    for m in C_DEFINE.finditer(code):
        add("const", m.group(1), float(m.group(2)), m)
    for m in C_ASSIGN.finditer(code):
        add("const", m.group(1), float(m.group(2)), m)
    for m in LIT_RE.finditer(code):
        if _standalone_literal(code, m):
            add("literal", "", float(m.group(0)), m)
    for m in C_CALL.finditer(code):
        if m.group(1) not in C_KEYWORDS:
            add("call", m.group(1), None, m)
    for m in C_STD_THREAD.finditer(code):
        add("call", f"std::{m.group(1)}", None, m)
    for m in C_OMP.finditer(code):
        add("call", "omp", None, m)
    for m in C_INCLUDE.finditer(code_with_strings):
        add("import", m.group(1), None, m)
    return facts


# ------------------------------------------------------------------ Perl / shell
SCRIPT_ASSIGN = re.compile(r"(?:^|[\s;(])(?:my\s+|our\s+|local\s+|export\s+|readonly\s+)?\$?([A-Za-z_]\w*)\s*=\s*(" + C_NUM + r")\s*(?=[;,)\n]|$)")


def scan_script_source(source: str, rel: str) -> list[Fact]:
    facts: list[Fact] = []
    for n, raw in enumerate(source.splitlines(), 1):
        line = re.sub(r"(?<!\S)#.*$", "", raw)
        for m in SCRIPT_ASSIGN.finditer(line):
            facts.append(Fact("const", m.group(1), float(m.group(2)), rel, n, "script", raw.strip()[:200]))
    return facts


# --------------------------------------------------------------------- driver
def scan_repository(root: str | Path, include_tests: bool = False) -> ScanResult:
    base = Path(root).resolve()
    result = ScanResult()
    for path, lang in iter_source_files(base, include_tests):
        rel = path.relative_to(base).as_posix()
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".ipynb":
                raw = _notebook_source(raw)
            facts = {"python": scan_python_source, "r": scan_r_source, "cpp": scan_cpp_source, "script": scan_script_source}[lang](raw, rel)
        except (SyntaxError, ValueError, json.JSONDecodeError, RecursionError):
            result.unparsed.append(rel)
            continue
        result.files[lang] = result.files.get(lang, 0) + 1
        result.facts.extend(facts)
    return result
