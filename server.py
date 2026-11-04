from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from bioaudit import __version__
from bioaudit.audit import run_audit
from bioaudit.ingest import load_paper, open_repository, sha256_bytes, tree_hash
from bioaudit.report import render_json
from bioaudit.scan import LANG_BY_EXT, MAX_BYTES

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DEMO_PAPER = ROOT / "demo_data" / "paper.txt"
DEMO_REPOSITORY = ROOT / "demo_data" / "repo"
MAX_REQUEST_BYTES = 145 * 1024 * 1024
MAX_PAPER_BYTES = 40 * 1024 * 1024
MAX_REPOSITORY_ZIP_BYTES = 100 * 1024 * 1024
MAX_REPOSITORY_SOURCE_FILES = 20_000
MAX_REPOSITORY_SOURCE_BYTES = 100 * 1024 * 1024
SUPPORTED_SOURCE_EXTENSIONS = frozenset(LANG_BY_EXT)
ALLOWED_GIT_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
AUDIT_SLOTS = asyncio.Semaphore(2)

app = FastAPI(title="Bioaudit", version=__version__, docs_url=None, redoc_url=None)


@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    length = request.headers.get("content-length")
    if length:
        try:
            if int(length) > MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request is too large. The paper and repository archive together must fit within the upload limit."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
    return await call_next(request)


@app.get("/api/health")
async def health():
    return {"ok": True, "engine": "Bioaudit", "version": __version__, "mode": "static-analysis"}


def _validate_git_url(value: str) -> str:
    url = value.strip()
    if len(url) > 2048:
        raise HTTPException(422, "Repository URL is too long.")
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Enter a valid public HTTPS Git URL.") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_GIT_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or len([part for part in parsed.path.split("/") if part]) < 2
    ):
        raise HTTPException(422, "Use a public HTTPS repository URL hosted on GitHub, GitLab, or Bitbucket. Private credentials and custom ports are not accepted.")
    return url


def _validate_revision(value: str | None) -> str | None:
    revision = (value or "").strip()
    if not revision:
        return None
    if len(revision) > 128 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", revision) or ".." in revision.split("/"):
        raise HTTPException(422, "Revision must be a simple branch, tag, or commit identifier (1–128 safe characters).")
    return revision


async def _save_upload(
    upload: UploadFile,
    target: Path,
    allowed_extensions: set[str] | frozenset[str],
    limit: int,
    kind: str,
    limit_message: str | None = None,
) -> int:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(415, f"Choose a {kind} file with one of these extensions: {', '.join(sorted(allowed_extensions))}.")
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    message = limit_message or f"{kind.capitalize()} exceeds the {((limit + 1024 * 1024 - 1) // (1024 * 1024))} MB upload limit."
                    raise HTTPException(413, message)
                output.write(chunk)
    finally:
        await upload.close()
    if total == 0:
        raise HTTPException(400, f"The selected {kind} file is empty.")
    return total


def _safe_source_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/")
    if not name or name in {".", ".."} or "/" in name or "\x00" in name or len(name) > 255:
        raise HTTPException(400, "Upload source files by filename only; folder paths and unsafe filenames are not accepted.")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_SOURCE_EXTENSIONS))
        raise HTTPException(415, f"Unsupported source file type. Choose files with these extensions: {allowed}.")
    return name


async def _save_source_files(uploads: list[UploadFile], target: Path) -> int:
    if not uploads:
        raise HTTPException(422, "Choose one or more supported source-code files.")
    if len(uploads) > MAX_REPOSITORY_SOURCE_FILES:
        raise HTTPException(413, f"Select no more than {MAX_REPOSITORY_SOURCE_FILES:,} source files.")

    target.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    total = 0
    for upload in uploads:
        try:
            name = _safe_source_filename(upload.filename)
            if name.casefold() in names:
                raise HTTPException(422, f"More than one selected file is named {name!r}. Rename duplicate files before uploading.")
            names.add(name.casefold())
            remaining = MAX_REPOSITORY_SOURCE_BYTES - total
            if remaining <= 0:
                raise HTTPException(413, "Selected source files exceed the 100 MB combined upload limit.")
            limit = min(MAX_BYTES, remaining)
            limit_message = (
                "Selected source files exceed the 100 MB combined upload limit."
                if remaining < MAX_BYTES
                else "Each source file must be no larger than 2 MB, matching Bioaudit's per-file scan limit."
            )
            total += await _save_upload(
                upload,
                target / name,
                SUPPORTED_SOURCE_EXTENSIONS,
                limit,
                "source file",
                limit_message,
            )
        finally:
            await upload.close()

    return total


def _audit(
    paper_path: Path,
    repository_source: str,
    revision: str | None,
    paper_sha: str,
    *,
    dataset: str | None = None,
    repository_description: str | None = None,
) -> dict:
    paper_text = load_paper(paper_path)
    with open_repository(repository_source, revision) as (repository_root, source):
        report = run_audit(paper_text, repository_root)
        report.meta.update({
            "Tool version": __version__,
            "Paper SHA-256": paper_sha,
            "Repository source": repository_description or source,
            "Repository tree SHA-256": tree_hash(repository_root),
        })
        if dataset:
            report.meta["Dataset"] = dataset
        return json.loads(render_json(report))


async def _run_audit(
    paper_path: Path,
    repository_source: str,
    revision: str | None,
    paper_sha: str,
    *,
    dataset: str | None = None,
    repository_description: str | None = None,
) -> dict:
    async with AUDIT_SLOTS:
        try:
            return await run_in_threadpool(
                _audit,
                paper_path,
                repository_source,
                revision,
                paper_sha,
                dataset=dataset,
                repository_description=repository_description,
            )
        except HTTPException:
            raise
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "The repository fetch timed out. Try a smaller archive or a stable public repository URL.") from exc
        except subprocess.CalledProcessError as exc:
            raise HTTPException(422, "The repository could not be fetched or checked out. Confirm it is public and the branch, tag, or commit exists.") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)[:500]) from exc


@app.post("/api/audit")
async def create_audit(
    paper: UploadFile = File(...),
    repo_archive: UploadFile | None = File(default=None),
    repo_files: list[UploadFile] | None = File(default=None),
    repo_url: str | None = Form(default=None),
    revision: str | None = Form(default=None),
):
    clean_url = _validate_git_url(repo_url) if repo_url and repo_url.strip() else None
    clean_revision = _validate_revision(revision)
    has_files = bool(repo_files)
    if sum((repo_archive is not None, has_files, clean_url is not None)) != 1:
        raise HTTPException(422, "Provide exactly one repository ZIP archive, source-file selection, or public Git URL.")
    if clean_revision and not clean_url:
        raise HTTPException(422, "A revision can only be supplied with a public Git URL.")

    paper_suffix = Path(paper.filename or "").suffix.lower()
    if paper_suffix not in {".pdf", ".txt"}:
        await paper.close()
        raise HTTPException(415, "Paper must be a PDF or plain-text TXT file.")

    with tempfile.TemporaryDirectory(prefix="bioaudit-request-") as temporary:
        work = Path(temporary)
        paper_path = work / f"paper{paper_suffix}"
        await _save_upload(paper, paper_path, {".pdf", ".txt"}, MAX_PAPER_BYTES, "paper")
        paper_sha = hashlib.sha256(paper_path.read_bytes()).hexdigest()

        if repo_archive is not None:
            repo_path = work / "repository.zip"
            await _save_upload(repo_archive, repo_path, {".zip"}, MAX_REPOSITORY_ZIP_BYTES, "repository archive")
            return await _run_audit(paper_path, str(repo_path), None, paper_sha)
        if has_files:
            repository_root = work / "repository-files"
            await _save_source_files(repo_files or [], repository_root)
            return await _run_audit(
                paper_path,
                str(repository_root),
                None,
                paper_sha,
                repository_description="uploaded source files",
            )
        return await _run_audit(paper_path, clean_url or "", clean_revision, paper_sha)


@app.get("/api/demo")
async def demo_audit():
    if not DEMO_PAPER.is_file() or not DEMO_REPOSITORY.is_dir():
        raise HTTPException(503, "The bundled demo fixture is unavailable.")
    paper_sha = hashlib.sha256(DEMO_PAPER.read_bytes()).hexdigest()
    return await _run_audit(DEMO_PAPER, str(DEMO_REPOSITORY), None, paper_sha, dataset="Synthetic validation example")


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
