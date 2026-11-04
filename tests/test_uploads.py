import asyncio
from io import BytesIO

from fastapi import HTTPException, UploadFile

from server import MAX_BYTES, _safe_source_filename, _save_source_files


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


def _assert_http_error(action, status_code: int) -> HTTPException:
    try:
        action()
    except HTTPException as exc:
        assert exc.status_code == status_code
        return exc
    raise AssertionError(f"Expected HTTP {status_code} from {action!r}")


def test_source_file_uploads_are_written_to_temporary_repository(tmp_path):
    repository = tmp_path / "repository-files"
    uploads = [
        _upload("options.cpp", b"#define PACK_SIZE 1000\n"),
        _upload("worker.py", b"THREADS = 4\n"),
    ]

    total = asyncio.run(_save_source_files(uploads, repository))

    assert total == len(b"#define PACK_SIZE 1000\n") + len(b"THREADS = 4\n")
    assert (repository / "options.cpp").read_bytes() == b"#define PACK_SIZE 1000\n"
    assert (repository / "worker.py").read_bytes() == b"THREADS = 4\n"


def test_source_upload_rejects_path_components():
    for filename in ("../options.cpp", "folder/options.cpp", r"folder\options.cpp", ".."):
        _assert_http_error(lambda filename=filename: _safe_source_filename(filename), 400)


def test_source_upload_rejects_unsupported_rust_files():
    _assert_http_error(lambda: _safe_source_filename("main.rs"), 415)


def test_source_upload_rejects_duplicate_basenames(tmp_path):
    uploads = [_upload("main.cpp", b"int a;"), _upload("MAIN.cpp", b"int b;")]
    _assert_http_error(lambda: asyncio.run(_save_source_files(uploads, tmp_path / "repo")), 422)


def test_source_upload_rejects_files_larger_than_scanner_limit(tmp_path):
    upload = _upload("large.py", b"x" * (MAX_BYTES + 1))
    error = _assert_http_error(lambda: asyncio.run(_save_source_files([upload], tmp_path / "repo")), 413)
    assert "2 MB" in error.detail
