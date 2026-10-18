const $ = (selector, root = document) => root.querySelector(selector);
const state = { report: null, selected: -1, repoMode: 'archive', loading: false, timer: null };
const VERDICTS = ['MISMATCH', 'PARTIAL_MATCH', 'NOT_FOUND', 'IMPORT_ONLY', 'VALUE_PRESENT_UNRELATED', 'RESULT_NEEDS_RUN', 'LITERAL_FOUND', 'MATCH', 'CALL_FOUND'];
const KIND_LABEL = { number: 'PARAMETER / RESULT', concept: 'METHOD CONCEPT' };
const THEME_STORAGE_KEY = 'bioaudit-theme';

function setTheme(theme, persist = false) {
  const selectedTheme = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = selectedTheme;
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === selectedTheme));
  });
  const themeColor = $('meta[name="theme-color"]');
  if (themeColor) themeColor.content = selectedTheme === 'light' ? '#f3f5ef' : '#09100f';
  if (persist) {
    try { window.localStorage.setItem(THEME_STORAGE_KEY, selectedTheme); } catch {}
  }
}

function initTheme() {
  let savedTheme = document.documentElement.dataset.theme || 'dark';
  try { savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY) || savedTheme; } catch {}
  setTheme(savedTheme);
  document.querySelectorAll('[data-theme-choice]').forEach(button => {
    button.addEventListener('click', () => setTheme(button.dataset.themeChoice, true));
  });
}

initTheme();

const $form = $('#auditForm');
const $paper = $('#paperInput');
const $repo = $('#repoInput');
const $error = $('#formError');
const $status = $('#runStatus');
const $results = $('#results');
const $findingList = $('#findingList');

function setError(message) {
  $error.textContent = message;
  $error.hidden = !message;
}
function setFileLabel(input, title, meta, emptyTitle, emptyMeta) {
  const file = input.files && input.files[0];
  title.textContent = file ? file.name : emptyTitle;
  meta.textContent = file ? `${formatBytes(file.size)} · ready to scan` : emptyMeta;
}
function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
function setRepoMode(mode) {
  state.repoMode = mode;
  document.querySelectorAll('[data-repo-mode]').forEach(button => {
    const active = button.dataset.repoMode === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  $('#archivePanel').hidden = mode !== 'archive';
  $('#urlPanel').hidden = mode !== 'url';
  setError('');
}
function attachDrop(label, input) {
  for (const eventName of ['dragenter', 'dragover']) label.addEventListener(eventName, event => { event.preventDefault(); label.classList.add('dragging'); });
  for (const eventName of ['dragleave', 'drop']) label.addEventListener(eventName, event => {
    event.preventDefault();
    label.classList.remove('dragging');
    if (eventName === 'drop' && event.dataTransfer.files.length) {
      try { input.files = event.dataTransfer.files; input.dispatchEvent(new Event('change', { bubbles: true })); }
      catch { setError('This browser could not attach the dropped file. Use Browse files instead.'); }
    }
  });
}
function showLoading(label = 'SCANNING SOURCE EVIDENCE') {
  state.loading = true;
  const submit = $('#submitAudit');
  submit.disabled = true;
  submit.innerHTML = '<span>Audit in progress</span><span class="button-arrow">···</span>';
  $('#statusTitle').textContent = label;
  $('#statusDescription').textContent = 'Bioaudit is mapping paper claims to source facts. Repository code is never run.';
  $status.hidden = false;
  const started = Date.now();
  state.timer = window.setInterval(() => {
    const total = Math.floor((Date.now() - started) / 1000);
    $('#elapsedTime').textContent = `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
  }, 1000);
  setError('');
}
function stopLoading() {
  state.loading = false;
  window.clearInterval(state.timer);
  state.timer = null;
  $status.hidden = true;
  const submit = $('#submitAudit');
  submit.disabled = false;
  submit.innerHTML = '<span>Run static audit</span><span class="button-arrow">↗</span>';
}
function labelCount(n, singular, plural = `${singular}s`) { return `${n} ${n === 1 ? singular : plural}`; }
function addText(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  parent.append(element);
  return element;
}
function countByVerdict(items, verdict) { return items.filter(item => item.verdict === verdict).length; }
function renderSummary(report) {
  const items = report.items || [];
  const matched = items.filter(item => ['MATCH', 'CALL_FOUND', 'LITERAL_FOUND'].includes(item.verdict)).length;
  const review = items.filter(item => ['MISMATCH', 'PARTIAL_MATCH', 'NOT_FOUND', 'IMPORT_ONLY'].includes(item.verdict)).length;
  const methods = items.filter(item => item.kind === 'concept' && ['CALL_FOUND', 'IMPORT_ONLY'].includes(item.verdict)).length;
  const cards = [
    { value: items.length, label: 'TOTAL FINDINGS', cls: '' },
    { value: review, label: 'NEEDS REVIEW', cls: 'warning' },
    { value: matched, label: 'EVIDENCE LOCATED', cls: 'match' },
    { value: methods, label: 'METHOD CALLS / IMPORTS', cls: 'methods' },
  ];
  const strip = $('#summaryStrip');
  strip.replaceChildren();
  cards.forEach(card => {
    const el = addText(strip, 'div', `summary-card ${card.cls}`);
    addText(el, 'div', 'summary-value', card.value);
    addText(el, 'div', 'summary-label', card.label);
  });
}
function populateVerdictFilter(items) {
  const select = $('#verdictFilter');
  const selected = select.value;
  select.replaceChildren();
  const all = document.createElement('option'); all.value = 'all'; all.textContent = 'All verdicts'; select.append(all);
  const present = [...new Set(items.map(item => item.verdict))].sort((a, b) => VERDICTS.indexOf(a) - VERDICTS.indexOf(b));
  present.forEach(verdict => { const option = document.createElement('option'); option.value = verdict; option.textContent = verdict.replaceAll('_', ' '); select.append(option); });
  select.value = present.includes(selected) ? selected : 'all';
}
function slug(value) { return String(value || '').toLowerCase().replaceAll('_', '-').replaceAll(' ', '-'); }
function getGroup(item) {
  const mode = $('#groupFilter').value;
  if (mode === 'verdict') return item.verdict.replaceAll('_', ' ');
  if (mode === 'kind') return item.kind === 'concept' ? 'METHOD CONCEPTS' : 'PARAMETERS & RESULTS';
  if (mode === 'file') return item.evidence?.[0]?.path || 'NO SOURCE LOCATION';
  return '';
}
function visibleItems() {
  if (!state.report) return [];
  const query = $('#findingSearch').value.trim().toLowerCase();
  const kind = $('#kindFilter').value;
  const verdict = $('#verdictFilter').value;
  return state.report.items.map((item, index) => ({ item, index })).filter(({ item }) => {
    if (kind !== 'all' && item.kind !== kind) return false;
    if (verdict !== 'all' && item.verdict !== verdict) return false;
    if (!query) return true;
    const evidence = (item.evidence || []).map(ev => `${ev.path} ${ev.line} ${ev.text}`).join(' ');
    return `${item.kind} ${item.key} ${item.claim} ${item.verdict} ${item.detail} ${evidence}`.toLowerCase().includes(query);
  });
}
function renderFindingList() {
  const found = visibleItems();
  $findingList.replaceChildren();
  $('#emptyFilter').hidden = found.length !== 0;
  $('#findingCount').textContent = `${found.length} / ${state.report.items.length} FINDINGS`;
  const groups = new Map();
  found.forEach(({ item, index }) => {
    const group = getGroup(item);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push({ item, index });
  });
  groups.forEach((items, group) => {
    if (group) addText($findingList, 'div', 'group-title', group);
    items.forEach(({ item, index }) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = `finding-row${state.selected === index ? ' selected' : ''}`;
      row.dataset.index = String(index);
      row.setAttribute('aria-label', `${item.verdict.replaceAll('_', ' ')}: ${item.kind}, ${item.key}. ${item.claim}`);
      const verdict = addText(row, 'span', `verdict-pill v-${slug(item.verdict)}`, item.verdict.replaceAll('_', ' '));
      verdict.setAttribute('aria-hidden', 'true');
      const content = addText(row, 'span', 'finding-main', '');
      addText(content, 'span', 'finding-key', `${item.kind === 'concept' ? 'METHOD · ' : ''}${item.key}`);
      addText(content, 'span', 'finding-claim', item.claim);
      addText(row, 'span', 'finding-arrow', state.selected === index ? '↗' : '›');
      $findingList.append(row);
    });
  });
  if (state.selected >= 0 && !found.some(entry => entry.index === state.selected)) {
    state.selected = found.length ? found[0].index : -1;
    renderFindingList();
    return;
  }
  if (state.selected >= 0) renderDetail(state.report.items[state.selected]);
  else renderEmptyDetail();
}
function renderEmptyDetail() {
  const panel = $('#detailPanel');
  panel.replaceChildren();
  const empty = addText(panel, 'div', 'detail-empty', '');
  addText(empty, 'span', 'detail-empty-icon', '⌁');
  addText(empty, 'strong', '', 'Evidence, in context.');
  addText(empty, 'p', '', 'Select a finding to inspect the claim, verdict rationale, and source lines.');
}
function renderDetail(item) {
  const panel = $('#detailPanel');
  panel.replaceChildren();
  const top = addText(panel, 'div', 'detail-topline', '');
  addText(top, 'span', 'detail-kind', KIND_LABEL[item.kind] || item.kind.toUpperCase());
  addText(top, 'span', `verdict-pill v-${slug(item.verdict)}`, item.verdict.replaceAll('_', ' '));
  addText(panel, 'h3', 'detail-key', item.key);
  addText(panel, 'p', 'detail-claim', `“${item.claim}”`);
  addText(panel, 'div', 'detail-rationale', item.detail || 'No additional rationale was returned by the analyzer.');
  const evidenceHeader = addText(panel, 'div', 'evidence-header', '');
  addText(evidenceHeader, 'span', '', `SOURCE EVIDENCE · ${(item.evidence || []).length}`);
  if (item.evidence?.length) {
    const copy = addText(evidenceHeader, 'button', 'copy-evidence', 'COPY');
    copy.type = 'button'; copy.dataset.copyEvidence = 'true';
  }
  const evidence = item.evidence || [];
  if (!evidence.length) {
    addText(panel, 'div', 'no-evidence', 'No source location was returned for this finding. NOT_FOUND means the scanner did not locate evidence; it does not prove the method or value is absent.');
  } else {
    evidence.forEach(entry => {
      const box = addText(panel, 'div', 'code-evidence', '');
      addText(box, 'code', 'code-path', `${entry.path}:${entry.line}`);
      const code = addText(box, 'div', 'code-line', '');
      addText(code, 'span', 'line-number', entry.line);
      addText(code, 'code', '', entry.text);
    });
  }
  const meta = addText(panel, 'div', 'detail-meta', '');
  addText(meta, 'span', '', `CLAIM ${item.claim_id || '—'}`);
  addText(meta, 'span', '', item.kind === 'concept' ? 'METHOD VOCABULARY' : 'PAPER PARAMETER / RESULT');
}
function renderMetadata(report) {
  const element = $('#reportMeta');
  element.replaceChildren();
  const meta = report.meta || {};
  const entries = [
    ['ENGINE', meta['Tool version'] || 'Bioaudit'],
    ['REPOSITORY', meta['Repository source'] || '—'],
    ['PAPER SHA-256', meta['Paper SHA-256'] || '—'],
    ['SOURCE TREE SHA-256', meta['Repository tree SHA-256'] || '—'],
  ];
  if (meta.Dataset) entries.unshift(['DATASET', meta.Dataset]);
  entries.forEach(([label, value]) => {
    const chip = addText(element, 'span', 'meta-chip', '');
    addText(chip, 'b', '', `${label} · `);
    addText(chip, 'span', '', value);
  });
  const files = Object.entries(report.files_scanned || {}).map(([lang, n]) => `${lang} ${n}`).join(' · ') || 'no source files';
  const scanned = addText(element, 'span', 'meta-chip', '');
  addText(scanned, 'b', '', 'FILES SCANNED · ');
  addText(scanned, 'span', '', files);
  if (report.unparsed_files?.length) {
    const skipped = addText(element, 'span', 'meta-chip', '');
    addText(skipped, 'b', '', 'UNPARSED · ');
    addText(skipped, 'span', '', report.unparsed_files.join(', '));
  }
  (report.warnings || []).forEach(warning => {
    const chip = addText(element, 'span', 'meta-chip', '');
    addText(chip, 'b', '', 'ANALYZER NOTE · ');
    addText(chip, 'span', '', warning);
  });
}
function displayReport(report, isDemo = false) {
  state.report = report;
  state.selected = report.items?.length ? 0 : -1;
  renderSummary(report);
  populateVerdictFilter(report.items || []);
  renderFindingList();
  renderMetadata(report);
  $('#sampleTag').hidden = !isDemo;
  $results.hidden = false;
  requestAnimationFrame(() => $results.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}
function friendlyError(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map(item => typeof item === 'string' ? item : (item?.msg || 'Invalid input')).join(' ');
  return 'The audit could not be completed. Check the inputs and try again.';
}
function isRecord(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function isValidReport(payload) {
  if (!isRecord(payload) || !isRecord(payload.meta) || !isRecord(payload.files_scanned) || !Array.isArray(payload.items)) return false;
  return payload.items.every(item => isRecord(item)
    && typeof item.kind === 'string'
    && typeof item.key === 'string'
    && typeof item.claim_id === 'string'
    && typeof item.claim === 'string'
    && typeof item.verdict === 'string'
    && typeof item.detail === 'string'
    && Array.isArray(item.evidence)
    && item.evidence.every(evidence => isRecord(evidence)
      && typeof evidence.path === 'string'
      && Number.isInteger(evidence.line)
      && typeof evidence.text === 'string'));
}
async function fetchReport(url, options, label) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (error instanceof TypeError) throw new Error('Could not reach the Bioaudit backend. Check your connection and retry.');
    throw new Error('The request stopped before Bioaudit returned a response. Check your connection and retry.');
  }

  let payload;
  try {
    payload = await response.json();
  } catch (error) {
    if (!response.ok) throw new Error(`Bioaudit returned HTTP ${response.status}, but its error details could not be read. Retry the request.`);
    if (error instanceof TypeError) throw new Error(`${label} reached Bioaudit, but the report response was interrupted. The audit may have completed; retry with a smaller ZIP or use a public Git URL.`);
    throw new Error(`${label} reached Bioaudit, but the response was not valid JSON. The audit may have completed; retry with a smaller ZIP or use a public Git URL.`);
  }

  if (!response.ok) throw new Error(friendlyError(payload?.detail));
  if (!isValidReport(payload)) throw new Error(`${label} received a response, but its report structure is incomplete. The audit may have completed; retry with a smaller ZIP or use a public Git URL.`);
  return payload;
}
function displayReportSafely(payload, isDemo) {
  try {
    displayReport(payload, isDemo);
  } catch (error) {
    console.error('Bioaudit report rendering failed after a successful response.', error);
    throw new Error('Bioaudit returned a report, but the browser could not display it. Retry with a smaller ZIP or use a public Git URL.');
  }
}
async function submitAudit(event) {
  event.preventDefault();
  if (state.loading) return;
  const paperFile = $paper.files?.[0];
  if (!paperFile) { setError('Choose the research paper you want to audit.'); $paper.focus(); return; }
  if (paperFile.size > 40 * 1024 * 1024) { setError('The paper exceeds the 40 MB upload limit.'); return; }
  const data = new FormData();
  data.append('paper', paperFile);
  if (state.repoMode === 'archive') {
    const repositoryFile = $repo.files?.[0];
    if (!repositoryFile) { setError('Choose a repository ZIP archive.'); $repo.focus(); return; }
    if (repositoryFile.size > 100 * 1024 * 1024) { setError('The repository archive exceeds the 100 MB upload limit.'); return; }
    data.append('repo_archive', repositoryFile);
  } else {
    const url = $('#repoUrl').value.trim();
    if (!url) { setError('Enter a public GitHub, GitLab, or Bitbucket HTTPS URL.'); $('#repoUrl').focus(); return; }
    data.append('repo_url', url);
    const revision = $('#revision').value.trim();
    if (revision) data.append('revision', revision);
  }
  showLoading();
  try {
    const payload = await fetchReport('/api/audit', { method: 'POST', body: data, headers: { Accept: 'application/json' } }, 'The audit');
    displayReportSafely(payload, false);
  } catch (error) {
    setError(error.message || 'The audit failed. Check the inputs and try again.');
    $('#formError').scrollIntoView({ behavior: 'smooth', block: 'center' });
  } finally {
    stopLoading();
  }
}
async function runDemo() {
  if (state.loading) return;
  showLoading('LOADING THE SYNTHETIC EXAMPLE');
  try {
    const payload = await fetchReport('/api/demo', { headers: { Accept: 'application/json' } }, 'The sample report');
    displayReportSafely(payload, true);
  } catch (error) {
    setError(error.message || 'The sample report could not be loaded.');
    $('#audit').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } finally { stopLoading(); }
}
function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}
function buildShareHtml(report) {
  const data = JSON.stringify(report).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
  const metaRows = Object.entries(report.meta || {}).map(([key, value]) => `<div class="meta"><b>${escapeHtml(key)}</b><span>${escapeHtml(value)}</span></div>`).join('');
  const fileCounts = Object.entries(report.files_scanned || {}).map(([key, value]) => `${escapeHtml(key)}: ${escapeHtml(value)}`).join(' · ') || 'none';
  const items = (report.items || []).map(item => {
    const evidence = (item.evidence || []).map(entry => `<div class="code"><b>${escapeHtml(entry.path)}:${escapeHtml(entry.line)}</b><pre>${escapeHtml(entry.text)}</pre></div>`).join('') || '<p class="muted">No source location returned.</p>';
    return `<article><div class="topline"><small>${escapeHtml(item.kind)} · ${escapeHtml(item.key)}</small><strong>${escapeHtml(item.verdict)}</strong></div><blockquote>${escapeHtml(item.claim)}</blockquote><p>${escapeHtml(item.detail)}</p>${evidence}<small>Claim ${escapeHtml(item.claim_id)}</small></article>`;
  }).join('');
  const warnings = (report.warnings || []).map(warning => `<li>${escapeHtml(warning)}</li>`).join('');
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Bioaudit report</title><style>body{margin:0;background:#0b1210;color:#e8f0e8;font:15px/1.65 system-ui,sans-serif}main{max-width:1000px;margin:auto;padding:40px 22px}h1{font-size:clamp(36px,7vw,64px);letter-spacing:-.06em;line-height:1;margin:14px 0}h1 em{color:#c8f36a;font-family:Georgia,serif;font-weight:400}small,.meta b{font:10px ui-monospace,monospace;letter-spacing:.08em;color:#8fa195;text-transform:uppercase}.intro{color:#9eada2;max-width:680px}.notice{border:1px solid #76613a;background:#f1c8790a;padding:16px;margin:24px 0;color:#ebd8b5}.meta{display:flex;gap:16px;border-bottom:1px solid #ffffff18;padding:9px 0;overflow-wrap:anywhere}.meta b{width:190px;flex:none}.meta span{color:#c8d4ca;font:12px ui-monospace,monospace}.summary{padding:16px 0;color:#c8f36a}article{border:1px solid #ffffff1c;border-radius:6px;padding:18px;margin:13px 0;background:#111c19}article blockquote{font:19px/1.5 Georgia,serif;margin:12px 0;color:#e3ece3}article p{color:#9eada2}.topline{display:flex;justify-content:space-between;gap:15px}.topline strong{font:10px ui-monospace,monospace;color:#c8f36a}.code{background:#070c0a;border:1px solid #ffffff16;border-radius:4px;margin:9px 0;overflow:hidden}.code b{display:block;padding:7px 10px;color:#b5c4b7;font:10px ui-monospace,monospace}.code pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:8px 10px;margin:0;color:#d4e1d5;font:12px/1.6 ui-monospace,monospace}.muted{color:#91a096}.foot{border-top:1px solid #ffffff1a;margin-top:28px;padding-top:18px;color:#d1b779}</style><main><small>BIOAUDIT · STATIC TRACE REPORT</small><h1>Evidence over <em>assumption.</em></h1><p class="intro">A paper-to-code comparison generated by Bioaudit v${escapeHtml(report.meta?.['Tool version'] || '2.0.0')}. Source code is inspected statically and is never executed.</p><div class="summary">${(report.items || []).length} findings · files scanned: ${fileCounts}</div><section>${metaRows}</section><section>${items || '<p>No checkable findings were returned.</p>'}</section>${warnings ? `<h2>Analyzer notes</h2><ul>${warnings}</ul>` : ''}<div class="notice"><b>Interpretation limit.</b> Static matches and calls do not prove runtime behavior, correct use, reproducibility, or scientific validity. A missing finding means the scanner did not locate evidence; it does not prove absence.</div><small>Complete machine-readable report is embedded below as JSON.</small><script type="application/json" id="bioaudit-data">${data}</script></main></html>`;
}
function downloadFile(filename, contents, mime) {
  const blob = new Blob([contents], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a'); link.href = url; link.download = filename; link.style.display = 'none';
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function safeFilename(value) { return String(value || 'audit').replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'audit'; }
function toast(message) {
  let element = $('.toast');
  if (!element) { element = document.createElement('div'); element.className = 'toast'; element.setAttribute('role', 'status'); document.body.append(element); }
  element.textContent = message; element.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => { element.hidden = true; }, 2300);
}

$paper.addEventListener('change', () => setFileLabel($paper, $('#paperFileTitle'), $('#paperFileMeta'), 'Drop a paper here', 'PDF or plain text · max 40 MB'));
$repo.addEventListener('change', () => setFileLabel($repo, $('#repoFileTitle'), $('#repoFileMeta'), 'Drop a repository ZIP', 'ZIP archive · max 100 MB'));
attachDrop($('#paperDrop'), $paper); attachDrop($('#repoDrop'), $repo);
document.querySelectorAll('[data-repo-mode]').forEach(button => button.addEventListener('click', () => setRepoMode(button.dataset.repoMode)));
$form.addEventListener('submit', submitAudit);
$('#startAudit').addEventListener('click', () => $('#audit').scrollIntoView({ behavior: 'smooth', block: 'start' }));
$('#navAudit').addEventListener('click', () => $('#audit').scrollIntoView({ behavior: 'smooth', block: 'start' }));
$('#navFindings').addEventListener('click', () => state.report ? $results.scrollIntoView({ behavior: 'smooth', block: 'start' }) : toast('Run an audit to reveal findings.'));
$('#runDemo').addEventListener('click', runDemo);
$('#findingSearch').addEventListener('input', renderFindingList);
$('#kindFilter').addEventListener('change', renderFindingList);
$('#verdictFilter').addEventListener('change', renderFindingList);
$('#groupFilter').addEventListener('change', renderFindingList);
$findingList.addEventListener('click', event => {
  const row = event.target.closest('[data-index]');
  if (!row || !state.report) return;
  state.selected = Number(row.dataset.index);
  renderFindingList();
});
$('#detailPanel').addEventListener('click', async event => {
  const button = event.target.closest('[data-copy-evidence]');
  if (!button || state.selected < 0) return;
  const item = state.report.items[state.selected];
  const text = (item.evidence || []).map(entry => `${entry.path}:${entry.line}\n${entry.text}`).join('\n\n');
  try { await navigator.clipboard.writeText(text); toast('Evidence copied to clipboard.'); }
  catch { toast('Clipboard access is unavailable in this browser.'); }
});
$('#exportJson').addEventListener('click', () => {
  if (!state.report) return;
  downloadFile(`bioaudit-${safeFilename(state.report.meta?.['Repository source'])}.json`, JSON.stringify(state.report, null, 2) + '\n', 'application/json');
});
$('#exportHtml').addEventListener('click', () => {
  if (!state.report) return;
  downloadFile(`bioaudit-${safeFilename(state.report.meta?.['Repository source'])}.html`, buildShareHtml(state.report), 'text/html;charset=utf-8');
});
