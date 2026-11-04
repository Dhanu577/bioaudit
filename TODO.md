# Bioaudit Web UI — Delivery Outcomes

The Python Bioaudit v2 analyzer remains the sole analysis engine. The browser application presents its existing static-analysis behavior and verdicts without executing audited repository code.

## 1. Browser audit setup and run states
- [x] Provide a browser-based audit setup for the research paper and repository inputs supported by the existing Bioaudit v2 analyzer, including clear input validation.
- [x] Provide high-end workflow states for setup, analysis progress, results, backend errors, and recovery so a user can correct inputs or retry.

## 2. Existing analyzer integration and safe handling
- [x] Integrate the existing Bioaudit v2 Python backend as the sole analysis engine and preserve its actual static-analysis behavior and verdict semantics.
- [x] Make it explicit that uploaded repository source is inspected statically and never executed; do not add a second or substitute analysis engine.

## 3. Results overview and evidence
- [x] Present an overview of Bioaudit verdicts for stated parameters and named methods found or not found in repository code.
- [x] Provide detailed finding views that connect each paper claim to the corresponding code evidence, file locations, and rationale when available.

## 4. Finding discovery and review
- [x] Support search, filtering, and grouping of findings by verdict, parameter, method, and source file so people can efficiently review the evidence.

## 5. Interpretation and limitations
- [x] Prominently explain that Bioaudit cannot establish runtime behavior, correctness, reproducibility, or scientific validity. Make clear that a static match or method call is evidence of textual/static correspondence, not proof of correct use or execution.

## 6. Exportable and shareable reports
- [x] Provide an exportable, shareable audit report that preserves findings, evidence, analyzer metadata, and limitations.

## 7. High-end accessible interface
- [x] Deliver a high-end, striking UI for the web development project, with a strong information hierarchy, readable code presentation, and interaction states suitable for technical and non-technical users.
- [x] Make the interface accessible and usable on desktop and mobile.

## 8. Theme options
- [x] Let the user switch between a white/light theme and a black/dark theme, keeping the current look as the dark theme; remember the selected theme across page reloads.

## 9. Accurate audit-response errors
- [x] For repository audits, distinguish network failures, HTTP errors, unreadable JSON, invalid report structure, and browser rendering failures. Do not label a successful backend response as “Could not reach the Bioaudit backend”; validate report shape before rendering and give a specific, actionable message if the browser cannot use the response.

## 10. Repository source-file input
- [x] In addition to ZIP archives and public Git repository URLs, let the user select one or more supported source-code files for audit. Make the input mode explicit in the browser, validate supported file types and size limits on client and server, safely place uploaded files in a temporary repository directory, and pass that directory to the existing static analyzer without executing any uploaded code.

## Design direction
- Scientific editorial instrument panel: deep ink surfaces, cool mineral neutrals, and a distinctive electric-lime signal color; asymmetrical, evidence-first composition; restrained motion and precise monospaced evidence accents. Keep visual effects behind content so they never compete with findings.
