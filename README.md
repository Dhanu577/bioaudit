# Bioaudit Web UI

Bioaudit keeps the existing Python v2 analyzer as its only analysis engine. FastAPI serves the same-origin browser interface and translates browser uploads into calls to the existing `bioaudit` package. The audited repository is scanned statically; its source is never executed.

## Run

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 3000
```

Open `http://localhost:3000`. The app has no database or account requirement. Uploaded inputs are held in a request-scoped temporary directory and removed when processing ends.

## Browser inputs

- Research paper: selectable-text PDF or UTF-8 plain-text TXT, up to 40 MB. Scanned PDFs require OCR before use.
- Repository: ZIP archive up to 100 MB (the existing safe extractor also enforces a 500 MB expanded-size cap and 20,000-entry cap), or a public HTTPS Git URL from GitHub, GitLab, or Bitbucket. Optional branch, tag, or commit is accepted for URL input.

The URL allowlist limits remote-fetch destinations. Git clone/checkout obtains source only; Bioaudit never runs repository scripts, package installation, notebooks, or build commands. The API limits concurrent audits to two. Inputs and reports are not persisted by the server.

## API

- `GET /api/health` — backend readiness/version.
- `GET /api/demo` — runs Bioaudit against a bundled **synthetic validation example**.
- `POST /api/audit` — multipart form with `paper` and exactly one of `repo_archive` or `repo_url`, optional `revision` for a URL; returns the existing JSON report shape (`meta`, `files_scanned`, `warnings`, `items`, and evidence).

The UI exports the complete report as JSON or a portable HTML file. No server-side sharing links are created.

## Checks

```bash
python -m pytest -q tests/test_all.py
python -m bioaudit.evaluate validation/cases
```

The validation examples are synthetic, not proof of broad real-world accuracy. Review `bioaudit/` for the existing analyzer's exact supported concepts and known limits. A `MATCH` or `CALL_FOUND` means corresponding evidence was found, not that the method was used correctly or a result is reproducible. `NOT_FOUND` means the scanner did not locate evidence, not that the method or value is absent. Results cannot establish runtime behavior, correctness, reproducibility, or scientific validity.
