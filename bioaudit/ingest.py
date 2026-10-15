"""Safe loading of papers and repositories."""
from __future__ import annotations

import contextlib
import hashlib
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .scan import iter_source_files

MAX_ENTRIES = 20_000
MAX_EXPANDED = 500 * 1024 * 1024


def load_paper(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Paper not found: {p}")
    if p.suffix.lower() == ".pdf":
        try:
            import pypdf
        except ImportError as exc:  # pragma: no cover
            raise ValueError("PDF input needs `pip install pypdf`") from exc
        reader = pypdf.PdfReader(str(p))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            raise ValueError("PDF has no selectable text (scanned PDFs need OCR first).")
        return text
    return p.read_text(encoding="utf-8", errors="replace")


def safe_extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ValueError("Archive has too many entries")
        if sum(i.file_size for i in infos) > MAX_EXPANDED:
            raise ValueError("Archive expands beyond the size limit")
        root = dest.resolve()
        for info in infos:
            name = info.filename.replace("\\", "/")
            target = (dest / name).resolve()
            if name.startswith("/") or ".." in Path(name).parts or root not in (target, *target.parents):
                raise ValueError(f"Unsafe path in archive: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"Symlink in archive: {info.filename}")
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


@contextlib.contextmanager
def open_repository(source: str, rev: str | None = None):
    """Yield (directory, description). Accepts a directory, a .zip, or a git URL (+ --rev)."""
    tmp = None
    try:
        if source.startswith(("https://", "git@")):
            tmp = tempfile.mkdtemp(prefix="bioaudit-")
            subprocess.run(["git", "clone", "--quiet", source, tmp], check=True, timeout=600)
            if rev:
                subprocess.run(["git", "-C", tmp, "checkout", "--quiet", rev], check=True, timeout=120)
            head = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            yield Path(tmp), f"git commit {head}"
        elif source.lower().endswith(".zip"):
            tmp = tempfile.mkdtemp(prefix="bioaudit-")
            safe_extract_zip(Path(source), Path(tmp))
            yield Path(tmp), "zip archive"
        else:
            p = Path(source)
            if not p.is_dir():
                raise ValueError(f"Repository directory not found: {p}")
            yield p, "local directory (no revision pinned)"
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(root: Path, include_tests: bool = False) -> str:
    h = hashlib.sha256()
    base = root.resolve()
    for path, _ in iter_source_files(base, include_tests):
        h.update(path.relative_to(base).as_posix().encode())
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()
