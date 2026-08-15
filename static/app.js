const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (character) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'}[character]));

async function request(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || 'Request failed');
  return payload;
}

async function loadDocuments() {
  const documents = await request('/api/documents');
  const select = byId('document-select');
  select.innerHTML = documents.length ? documents.map((d) => `<option value="${escapeHtml(d.id)}">${escapeHtml(d.issuer)} · ${escapeHtml(d.document_type)} · ${escapeHtml(d.filing_date)}</option>`).join('') : '<option value="">Upload a filing first</option>';
}

async function loadLeads() {
  const leads = await request('/api/leads');
  byId('lead-list').innerHTML = leads.length ? leads.map((lead) => `<article class="lead"><div><strong>${escapeHtml(lead.name)}</strong><span>${escapeHtml(lead.role)} · ${escapeHtml(lead.issuer)}</span></div><b>${lead.score}</b><p>${escapeHtml(lead.document_type)} filed ${escapeHtml(lead.filing_date)}${lead.stale ? ' · stale' : ''}</p><p>Score: shares ${lead.score_breakdown.share}, role ${lead.score_breakdown.role}, freshness ${lead.score_breakdown.freshness}, RHP ${lead.score_breakdown.rhp}</p><blockquote>p.${lead.evidence_page}: ${escapeHtml(lead.evidence_quote)}</blockquote></article>`).join('') : '<p>No candidates yet. Add only records with page-level evidence.</p>';
}

byId('upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { const result = await request('/api/documents/upload', {method: 'POST', body: new FormData(event.target)}); byId('upload-result').textContent = `Recorded ${result.issuer}: ${result.page_count} pages.`; event.target.reset(); await loadDocuments(); }
  catch (error) { byId('upload-result').textContent = error.message; }
});

byId('lead-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.target); const body = Object.fromEntries(form.entries());
  for (const field of ['disclosed_shares', 'price_per_share']) body[field] = body[field] ? Number(body[field]) : null;
  body.evidence_page = Number(body.evidence_page);
  try { await request('/api/leads', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}); byId('lead-result').textContent = 'Candidate recorded with provenance.'; event.target.reset(); await loadLeads(); }
  catch (error) { byId('lead-result').textContent = error.message; }
});

Promise.all([loadDocuments(), loadLeads()]).catch((error) => { byId('lead-list').textContent = error.message; });
