(function () {
  'use strict';

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  let recInitialized = false;
  let recCandPage = 1;
  let recEmailPage = 1;
  let currentSlotId = null;
  let cvCurrentPage = 1;
  let cvBaseUrl = '';

  // Stages that show ONLY opens_at / closes_at (no scoring/deadline fields)
  const DATE_ONLY_STAGES = new Set(['final_decision', 'documents']);
  // Stages where relative deadline is shown in days instead of hours
  const DEADLINE_IN_DAYS = new Set(['assessment']);

  // ── Hook into main tab switch ─────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    const btn = document.querySelector('.tab-btn[data-tab="recruitment"]');
    if (btn) {
      btn.addEventListener('click', () => {
        if (!recInitialized) { loadRecCandidates(1); recInitialized = true; }
      });
    }
  });

  // ── Sub-tab switching ─────────────────────────────────────────────────
  window.switchRecTab = function (name) {
    document.querySelectorAll('.rec-subtab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.rec-subpanel').forEach(p => p.classList.remove('active'));
    document.querySelector(`.rec-subtab[data-rec="${name}"]`).classList.add('active');
    document.getElementById(`rec-sub-${name}`).classList.add('active');

    if (name === 'candidates')  loadRecCandidates(1);
    if (name === 'interviewers') loadRecInterviewers();
    if (name === 'slots') {
      loadRecInterviewerSelect('arInterviewer');
      loadRecInterviewerSelect('panelistAddSel');
    }
    if (name === 'config')   loadRecStageConfig();
    if (name === 'emaillog') loadRecEmailLog(1);
  };

  // ── Candidates ────────────────────────────────────────────────────────
  window.loadRecCandidates = async function (page) {
    recCandPage = page;
    const stage   = document.getElementById('recSearchStage')?.value || '';
    const flagged = document.getElementById('recSearchFlagged')?.value || '';
    const tbody   = document.getElementById('recCandTbody');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888;padding:20px">Loading…</td></tr>';

    let url = `/api/admin/recruitment/candidates?page=${page}`;
    if (stage)   url += `&stage=${encodeURIComponent(stage)}`;
    if (flagged) url += `&flagged=${flagged}`;

    const data = await recApiGet(url);
    if (!data) {
      tbody.innerHTML = '<tr><td colspan="7" style="color:#c53030;padding:16px">Error loading.</td></tr>';
      return;
    }
    if (!data.candidates.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:#888;padding:24px">No candidates found.</td></tr>';
      return;
    }

    tbody.innerHTML = data.candidates.map(c => `
      <tr>
        <td>${esc(c.name)}</td>
        <td style="color:#888">${esc(c.email)}</td>
        <td><span class="rec-pill ${stagePill(c.stage)}">${esc(c.stage)}</span></td>
        <td>${c.latest_score !== null ? c.latest_score + '%' : '—'}</td>
        <td>${c.eligibility_flag
          ? `<span title="${esc(c.eligibility_flag_reason || '')}" style="color:#ed8936;cursor:help">⚠</span>`
          : ''}</td>
        <td style="color:#888">${c.created_at ? c.created_at.slice(0, 10) : '—'}</td>
        <td>
          <button class="btn btn-ghost" style="padding:4px 12px;font-size:.82rem" type="button"
            onclick="openRecCandModal(${c.id})">View</button>
        </td>
      </tr>`).join('');

    const total = data.total, pp = data.per_page;
    document.getElementById('recCandPagination').innerHTML = `
      <button type="button" class="btn btn-ghost"
        onclick="loadRecCandidates(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Previous</button>
      <span class="page-indicator font-mono">Page ${page} of ${Math.max(1, Math.ceil(total / pp))}</span>
      <button type="button" class="btn btn-ghost"
        onclick="loadRecCandidates(${page + 1})" ${page * pp >= total ? 'disabled' : ''}>Next →</button>`;
  };

  window.openRecCandModal = async function (candId) {
    document.getElementById('recCandModal').classList.remove('hidden');
    document.getElementById('recCandModalName').textContent = 'Loading…';
    document.getElementById('recCandModalContent').innerHTML =
      '<p style="color:#888;text-align:center;padding:24px">Loading…</p>';
    cvCurrentPage = 1; cvBaseUrl = '';

    const data = await recApiGet(`/api/admin/recruitment/candidates/${candId}`);
    if (!data) {
      document.getElementById('recCandModalContent').innerHTML =
        '<p style="color:#c53030">Error loading candidate.</p>';
      return;
    }
    const c = data.candidate;
    document.getElementById('recCandModalName').textContent = c.name;

    const stageOptions = [
      'applied', 'screening_failed', 'screening_flagged', 'screening_passed',
      'assessment_in_progress', 'assessment_failed', 'assessment_passed',
      'interview_slot_pending', 'interview_scheduled', 'documents_pending',
      'documents_submitted', 'interview_completed', 'offered', 'rejected',
    ].map(s => `<option value="${s}" ${s === c.stage ? 'selected' : ''}>${s}</option>`).join('');

    const cvHtml = c.cv_url ? `
      <div style="margin-top:8px">
        <button class="btn btn-ghost" style="padding:5px 14px;font-size:.85rem" type="button"
          onclick="toggleCVPreview('${esc(c.cv_url)}')">
          <i class="ti ti-file-text" style="margin-right:4px"></i>View CV
        </button>
      </div>
      <div id="cvPreviewWrap" class="cv-preview-wrap" style="display:none;margin-top:12px">
        <div class="cv-nav-bar">
          <button type="button" id="cvPrevBtn" onclick="cvChangePage(-1)" disabled>← Prev</button>
          <span id="cvPageLabel">Page 1</span>
          <button type="button" id="cvNextBtn" onclick="cvChangePage(1)">Next →</button>
          <a id="cvOpenLink" href="${esc(c.cv_url)}" target="_blank"
            style="margin-left:auto;color:#adf;font-size:.8rem;text-decoration:none">Open in new tab ↗</a>
        </div>
        <iframe id="cvIframe" class="cv-iframe" title="CV Preview"></iframe>
      </div>` : '';

    const scoresHtml = data.scores.length ? `
      <details style="margin-top:16px">
        <summary style="cursor:pointer;font-weight:700;color:#1a1a2e;padding:4px 0">
          Assessment Scores (${data.scores.length})
        </summary>
        <div class="table-container" style="margin-top:8px">
          <table class="data-table">
            <thead><tr><th>Label</th><th>Score</th><th>Result</th><th>Date</th></tr></thead>
            <tbody>${data.scores.map(s => `<tr>
              <td>${esc(s.label)}</td>
              <td>${s.score !== null ? s.score + '%' : '—'}</td>
              <td><span class="rec-pill ${s.pass_fail === 'pass' ? 'rec-pill-pass' : 'rec-pill-fail'}">${s.pass_fail || '—'}</span></td>
              <td style="color:#888">${s.taken_at ? s.taken_at.slice(0, 16) : '—'}</td>
            </tr>`).join('')}</tbody>
          </table>
        </div>
      </details>` : '';

    const docsHtml = data.documents.length ? `
      <details style="margin-top:12px">
        <summary style="cursor:pointer;font-weight:700;color:#1a1a2e;padding:4px 0">
          Documents (${data.documents.length})
        </summary>
        <div class="table-container" style="margin-top:8px">
          <table class="data-table">
            <thead><tr><th>Type</th><th>Status</th><th>Verified</th><th>View</th><th></th></tr></thead>
            <tbody>${data.documents.map(d => `<tr>
              <td style="text-transform:capitalize">${esc(d.doc_type.replace(/_/g, ' '))}</td>
              <td>${esc(d.status || '—')}</td>
              <td>${d.verified ? '<span style="color:#276749;font-weight:700">✓</span>' : '—'}</td>
              <td>${d.url
                ? `<a href="${esc(d.url)}" target="_blank" style="color:#1a1a2e;font-size:.85rem">Open ↗</a>`
                : '—'}</td>
              <td><button class="btn btn-ghost" type="button"
                style="padding:3px 10px;font-size:.78rem;border-color:${d.verified ? 'var(--color-danger)' : '#276749'};color:${d.verified ? 'var(--color-danger)' : '#276749'}"
                onclick="toggleRecDocVerify(${d.id},${!d.verified})">${d.verified ? 'Unverify' : 'Verify'}</button></td>
            </tr>`).join('')}</tbody>
          </table>
        </div>
      </details>` : '';

    const slotsHtml = data.interview_slots.length ? `
      <details style="margin-top:12px">
        <summary style="cursor:pointer;font-weight:700;color:#1a1a2e;padding:4px 0">Interview Slots</summary>
        <div class="table-container" style="margin-top:8px">
          <table class="data-table">
            <thead><tr><th>Time</th><th>Interviewer</th><th>Meeting</th></tr></thead>
            <tbody>${data.interview_slots.map(s => `<tr>
              <td>${s.start_time
                ? new Date(s.start_time).toLocaleString('en-NG', { timeZone: 'Africa/Lagos' })
                : '—'}</td>
              <td>${esc(s.interviewer || '—')}</td>
              <td>${s.meeting_link
                ? `<a href="${esc(s.meeting_link)}" target="_blank" style="color:#1a1a2e;font-size:.85rem">Join ↗</a>`
                : '—'}</td>
            </tr>`).join('')}</tbody>
          </table>
        </div>
      </details>` : '';

    const histHtml = data.stage_history.length ? `
      <details style="margin-top:12px">
        <summary style="cursor:pointer;font-weight:700;color:#1a1a2e;padding:4px 0">
          Stage History (${data.stage_history.length})
        </summary>
        <div class="table-container" style="margin-top:8px">
          <table class="data-table">
            <thead><tr><th>From</th><th>To</th><th>By</th><th>Date</th></tr></thead>
            <tbody>${data.stage_history.map(h => `<tr>
              <td>${esc(h.from || '—')}</td>
              <td>${esc(h.to)}</td>
              <td>${esc(h.by)}</td>
              <td style="color:#888">${h.at ? h.at.slice(0, 16) : '—'}</td>
            </tr>`).join('')}</tbody>
          </table>
        </div>
      </details>` : '';

    document.getElementById('recCandModalContent').innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px">
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Stage</label>
          <span class="rec-pill ${stagePill(c.stage)}">${esc(c.stage)}</span>
        </div>
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Email</label>
          ${esc(c.email)}
        </div>
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Phone</label>
          ${esc(c.phone || '—')}
        </div>
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">NYSC Status</label>
          ${esc(c.nysc_status || '—')}
        </div>
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Date of Birth</label>
          ${c.dob || '—'}
        </div>
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Role Applied</label>
          ${esc(c.role || '—')}
        </div>
        ${c.eligibility_flag ? `
        <div style="grid-column:1/-1">
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Flag Reason</label>
          <div style="color:#c05621">${esc(c.flag_reason || '')}</div>
        </div>` : ''}
      </div>

      ${cvHtml}

      <div style="margin:20px 0 8px">
        <label style="font-size:.82rem;font-weight:700;color:#555;display:block;margin-bottom:6px">
          Manual Stage Override
        </label>
        <div style="display:flex;gap:8px">
          <select id="recOverrideStage" class="rec-ctrl" style="flex:1">${stageOptions}</select>
          <button class="btn btn-primary" type="button" onclick="setRecStage(${candId})">Apply</button>
        </div>
        <div id="recOverrideMsg" style="font-size:.82rem;margin-top:6px"></div>
      </div>

      ${scoresHtml}${docsHtml}${slotsHtml}${histHtml}
    `;
  };

  window.closeRecCandModal = function () {
    document.getElementById('recCandModal').classList.add('hidden');
  };

  window.toggleCVPreview = function (url) {
    const wrap = document.getElementById('cvPreviewWrap');
    if (wrap.style.display === 'none') {
      cvBaseUrl = '/api/admin/cv-view?url=' + encodeURIComponent(url);
      cvCurrentPage = 1;
      renderCVPage();
      wrap.style.display = 'block';
    } else {
      wrap.style.display = 'none';
    }
  };

  function renderCVPage() {
    const iframe  = document.getElementById('cvIframe');
    const label   = document.getElementById('cvPageLabel');
    const prevBtn = document.getElementById('cvPrevBtn');
    if (!iframe) return;
    iframe.src = cvBaseUrl + '#page=' + cvCurrentPage;
    label.textContent = 'Page ' + cvCurrentPage;
    prevBtn.disabled = cvCurrentPage <= 1;
  }

  window.cvChangePage = function (delta) {
    const next = cvCurrentPage + delta;
    if (next < 1) return;
    cvCurrentPage = next;
    renderCVPage();
  };

  window.setRecStage = async function (candId) {
    const stage = document.getElementById('recOverrideStage').value;
    const msg   = document.getElementById('recOverrideMsg');
    const data  = await recApiPost(
      `/api/admin/recruitment/candidates/${candId}/stage`,
      { stage, notify: true, reason: 'admin override' }
    );
    if (data?.status === 'success') {
      msg.textContent = '✓ Stage updated.'; msg.style.color = '#276749';
      loadRecCandidates(recCandPage);
      setTimeout(() => openRecCandModal(candId), 400);
    } else {
      msg.textContent = data?.error || 'Error updating stage.'; msg.style.color = '#c53030';
    }
  };

  window.toggleRecDocVerify = async function (docId, verified) {
    await recApiPost(`/api/admin/recruitment/documents/${docId}/verify`, { verified });
  };

  // ── Interviewers ──────────────────────────────────────────────────────
  window.loadRecInterviewers = async function () {
    const tbody = document.getElementById('recInterviewerTbody');
    tbody.innerHTML =
      '<tr><td colspan="4" style="text-align:center;color:#888;padding:20px">Loading…</td></tr>';
    const data = await recApiGet('/api/admin/recruitment/interviewers');
    if (!data || !data.length) {
      tbody.innerHTML =
        '<tr><td colspan="4" style="text-align:center;color:#888;padding:20px">No interviewers added yet.</td></tr>';
      return;
    }
    tbody.innerHTML = data.map(i => `<tr>
      <td>${esc(i.name)}</td>
      <td style="color:#888">${esc(i.email)}</td>
      <td>${i.active
        ? '<span style="color:#276749;font-weight:700">Active</span>'
        : '<span style="color:#888">Inactive</span>'}</td>
      <td>
        <button class="btn btn-ghost" type="button"
          style="padding:3px 10px;font-size:.8rem;border-color:var(--color-danger);color:var(--color-danger)"
          onclick="deactivateRecInterviewer(${i.id})">${i.active ? 'Remove' : 'Removed'}</button>
      </td>
    </tr>`).join('');
  };

  window.addRecInterviewer = async function () {
    const errEl = document.getElementById('iError');
    errEl.style.display = 'none';
    const name  = document.getElementById('iName').value.trim();
    const email = document.getElementById('iEmail').value.trim();
    if (!name || !email) { showRecErr(errEl, 'Name and email are required.'); return; }
    const data = await recApiPost('/api/admin/recruitment/interviewers', { name, email });
    if (data?.status === 'success') {
      document.getElementById('iName').value  = '';
      document.getElementById('iEmail').value = '';
      loadRecInterviewers();
    } else {
      showRecErr(errEl, data?.error || 'Error adding interviewer.');
    }
  };

  window.deactivateRecInterviewer = async function (id) {
    if (!confirm('Remove this interviewer?')) return;
    await recApiFetch(`/api/admin/recruitment/interviewers/${id}`, 'DELETE');
    loadRecInterviewers();
  };

  window.loadRecInterviewerSelect = async function (selId) {
    const sel = document.getElementById(selId);
    if (!sel) return;
    const data = await recApiGet('/api/admin/recruitment/interviewers');
    if (!data) return;
    const actives = data.filter(i => i.active);
    if (selId === 'arInterviewer') {
      sel.innerHTML = actives.map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join('');
    } else {
      sel.innerHTML =
        '<option value="">— Select interviewer —</option>' +
        actives.map(i => `<option value="${i.id}">${esc(i.name)}</option>`).join('');
    }
  };

  // ── Slots & Availability Rules ────────────────────────────────────────
  window.toggleArType = function () {
    const t = document.getElementById('arType').value;
    document.getElementById('arRecurring').style.display  = t === 'recurring'  ? 'grid' : 'none';
    document.getElementById('arDateRange').style.display  = t === 'date_range' ? 'grid' : 'none';
  };

  window.addArRule = async function () {
    const body = {
      interviewer_id:         parseInt(document.getElementById('arInterviewer').value),
      rule_type:               document.getElementById('arType').value,
      day_of_week:             document.getElementById('arType').value === 'recurring'
                                 ? parseInt(document.getElementById('arDow').value) : null,
      date_from:               document.getElementById('arDateFrom').value || null,
      date_to:                 document.getElementById('arDateTo').value   || null,
      start_time:              document.getElementById('arStart').value,
      end_time:                document.getElementById('arEnd').value,
      slot_duration_minutes:   parseInt(document.getElementById('arDuration').value),
      buffer_minutes:          parseInt(document.getElementById('arBuffer').value),
      booking_lead_time_hours: parseInt(document.getElementById('arLead').value),
    };
    const data = await recApiPost('/api/admin/recruitment/availability-rules', body);
    if (data?.status === 'success') alert('Rule saved! Slots are generating in the background.');
    else alert(data?.error || 'Error saving rule.');
  };

  window.loadRecSlots = async function () {
    const from = document.getElementById('slotsFrom').value;
    const to   = document.getElementById('slotsTo').value;
    const wrap = document.getElementById('recSlotsTableWrap');
    if (!from || !to) {
      wrap.innerHTML = '<p style="color:#888;padding:8px 0">Please select both dates.</p>';
      return;
    }
    wrap.innerHTML = '<p style="color:#888;padding:8px 0">Loading…</p>';
    const data = await recApiGet(`/api/admin/recruitment/slots?from=${from}&to=${to}`);
    if (!data || !data.length) {
      wrap.innerHTML = '<p style="color:#888;padding:8px 0">No slots in this range.</p>';
      return;
    }
    wrap.innerHTML = `
      <table class="data-table">
        <thead>
          <tr><th>Start</th><th>End</th><th>Panelists</th><th>Booked By</th><th>Status</th><th></th><th></th></tr>
        </thead>
        <tbody>${data.map(s => `<tr>
          <td>${new Date(s.start_time).toLocaleString('en-NG', { timeZone: 'Africa/Lagos' })}</td>
          <td>${new Date(s.end_time).toLocaleTimeString('en-NG',
            { hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Lagos' })}</td>
          <td style="max-width:180px;font-size:.82rem">${esc(s.interviewers || s.interviewer || '—')}</td>
          <td>${esc(s.candidate_name || '—')}</td>
          <td><span class="rec-pill ${s.is_blocked ? 'rec-pill-fail' : s.is_booked ? 'rec-pill-active' : 'rec-pill-pass'}">
            ${s.is_blocked ? 'Blocked' : s.is_booked ? 'Booked' : 'Available'}</span></td>
          <td>
            <button class="btn btn-ghost" type="button"
              style="padding:3px 10px;font-size:.8rem;border-color:${s.is_blocked ? '#276749' : 'var(--color-danger)'};color:${s.is_blocked ? '#276749' : 'var(--color-danger)'}"
              onclick="toggleRecBlock(${s.id},${!s.is_blocked})">${s.is_blocked ? 'Unblock' : 'Block'}</button>
          </td>
          <td>
            <button class="btn btn-ghost" type="button"
              style="padding:3px 10px;font-size:.8rem"
              onclick="openPanelistModal(${s.id})">Panelists</button>
          </td>
        </tr>`).join('')}</tbody>
      </table>`;
  };

  window.toggleRecBlock = async function (slotId, blocked) {
    await recApiPost(`/api/admin/recruitment/slots/${slotId}/block`, { blocked });
    loadRecSlots();
  };

  window.triggerRecGenerate = async function () {
    const data = await recApiPost('/api/admin/recruitment/slots/generate', { weeks_ahead: 4 });
    alert(data?.message || 'Slot generation started.');
    setTimeout(loadRecSlots, 2000);
  };

  // ── Panelists ─────────────────────────────────────────────────────────
  window.openPanelistModal = async function (slotId) {
    currentSlotId = slotId;
    document.getElementById('panelistSlotId').textContent = slotId;
    document.getElementById('recPanelistModal').classList.remove('hidden');
    await refreshPanelistList(slotId);
    await loadRecInterviewerSelect('panelistAddSel');
  };

  async function refreshPanelistList(slotId) {
    const div = document.getElementById('panelistList');
    div.innerHTML = 'Loading…';
    const data = await recApiGet(`/api/admin/recruitment/slots/${slotId}/interviewers`);
    if (!data || !data.length) {
      div.innerHTML = '<span style="color:#888;font-size:.88rem">No panelists assigned yet.</span>';
      return;
    }
    div.innerHTML = data.map(p => `
      <span class="panelist-chip" style="margin:3px 4px 3px 0">
        ${esc(p.name)}
        <button type="button" onclick="removePanelist(${slotId},${p.interviewer_id})" title="Remove">✕</button>
      </span>`).join('');
  }

  window.addPanelist = async function () {
    const sel  = document.getElementById('panelistAddSel');
    const iid  = parseInt(sel.value);
    const msg  = document.getElementById('panelistMsg');
    if (!iid) { msg.textContent = 'Select an interviewer.'; msg.style.color = '#c53030'; return; }
    const data = await recApiPost(
      `/api/admin/recruitment/slots/${currentSlotId}/interviewers`,
      { interviewer_id: iid }
    );
    if (data?.status === 'success') {
      msg.textContent = '✓ Added.'; msg.style.color = '#276749';
      await refreshPanelistList(currentSlotId);
      sel.value = '';
    } else {
      msg.textContent = data?.error || 'Error.'; msg.style.color = '#c53030';
    }
  };

  window.removePanelist = async function (slotId, iid) {
    await recApiFetch(`/api/admin/recruitment/slots/${slotId}/interviewers/${iid}`, 'DELETE');
    await refreshPanelistList(slotId);
  };

  window.closePanelistModal = function () {
    document.getElementById('recPanelistModal').classList.add('hidden');
    loadRecSlots();
  };

  // ── Stage Config ──────────────────────────────────────────────────────
  window.loadRecStageConfig = async function () {
    const wrap = document.getElementById('recConfigGrid');
    wrap.innerHTML = '<p style="color:#888">Loading…</p>';
    const data = await recApiGet('/api/admin/recruitment/stage-config');
    if (!data) { wrap.innerHTML = '<p style="color:#c53030">Error loading config.</p>'; return; }

    wrap.innerHTML = `<div class="config-grid">${data.map(cfg => {
      const oa       = cfg.opens_at  ? cfg.opens_at.slice(0, 16)  : '';
      const ca       = cfg.closes_at ? cfg.closes_at.slice(0, 16) : '';
      const datesOnly = DATE_ONLY_STAGES.has(cfg.stage_name);
      const daysMode  = DEADLINE_IN_DAYS.has(cfg.stage_name);
      const rdVal     = cfg.relative_deadline_hours !== null
        ? (daysMode ? Math.round(cfg.relative_deadline_hours / 24) : cfg.relative_deadline_hours)
        : '';

      return `<div class="config-item">
        <h4>${esc(cfg.stage_name)}
          <span style="font-weight:400;font-size:.75rem;color:#aaa">(cycle ${cfg.cycle_id})</span>
        </h4>
        <div class="edit-row">
          <label>Opens At</label>
          <input id="oa-${cfg.stage_name}" type="datetime-local" value="${oa}"
            title="Stage becomes accessible after this time">
        </div>
        <div class="edit-row">
          <label>Closes At</label>
          <input id="ca-${cfg.stage_name}" type="datetime-local" value="${ca}"
            title="Stage no longer accessible after this time">
        </div>
        ${!datesOnly && cfg.pass_mark !== null ? `<div class="edit-row">
          <label>Pass mark %</label>
          <input id="pm-${cfg.stage_name}" type="number" step="0.5" min="0" max="100" value="${cfg.pass_mark}">
        </div>` : ''}
        ${!datesOnly && cfg.duration_minutes !== null ? `<div class="edit-row">
          <label>Duration (min)</label>
          <input id="dm-${cfg.stage_name}" type="number" min="1" value="${cfg.duration_minutes}">
        </div>` : ''}
        ${!datesOnly && cfg.relative_deadline_hours !== null ? `<div class="edit-row">
          <label>Deadline (${daysMode ? 'days' : 'hrs'})</label>
          <input id="rd-${cfg.stage_name}" type="number" min="0" value="${rdVal}">
        </div>` : ''}
        ${!datesOnly ? `
        <div class="edit-row">
          <label>Min age</label>
          <input id="minage-${cfg.stage_name}" type="number" min="16" max="60" value="${cfg.min_age || 18}">
        </div>
        <div class="edit-row">
          <label>Max age</label>
          <input id="maxage-${cfg.stage_name}" type="number" min="16" max="60" value="${cfg.max_age || 35}">
        </div>` : ''}
        <button class="btn btn-primary"
          style="margin-top:8px;padding:6px 14px;font-size:.83rem" type="button"
          onclick="saveRecConfig('${esc(cfg.stage_name)}')">Save</button>
        <span id="cfgMsg-${cfg.stage_name}"
          style="font-size:.78rem;margin-left:8px;color:#276749;display:none">Saved!</span>
      </div>`;
    }).join('')}</div>`;
  };

  window.saveRecConfig = async function (stageName) {
    const datesOnly = DATE_ONLY_STAGES.has(stageName);
    const daysMode  = DEADLINE_IN_DAYS.has(stageName);
    const rdRaw     = document.getElementById(`rd-${stageName}`)?.value;
    const rdHours   = rdRaw ? (daysMode ? parseInt(rdRaw) * 24 : parseInt(rdRaw)) : null;

    const body = {
      opens_at:                document.getElementById(`oa-${stageName}`)?.value || null,
      closes_at:               document.getElementById(`ca-${stageName}`)?.value || null,
      pass_mark:               datesOnly ? null : (document.getElementById(`pm-${stageName}`)?.value || null),
      duration_minutes:        datesOnly ? null : (document.getElementById(`dm-${stageName}`)?.value || null),
      relative_deadline_hours: datesOnly ? null : rdHours,
      min_age:                 datesOnly ? null : (document.getElementById(`minage-${stageName}`)?.value || null),
      max_age:                 datesOnly ? null : (document.getElementById(`maxage-${stageName}`)?.value || null),
    };

    const data = await recApiPost(`/api/admin/recruitment/stage-config/${stageName}`, body, 'PUT');
    const msg  = document.getElementById(`cfgMsg-${stageName}`);
    if (data?.status === 'success') {
      msg.style.display = 'inline';
      setTimeout(() => { msg.style.display = 'none'; }, 2500);
    } else {
      msg.textContent = 'Error.'; msg.style.color = '#c53030'; msg.style.display = 'inline';
    }
  };

  // ── Email Log ─────────────────────────────────────────────────────────
  window.loadRecEmailLog = async function (page) {
    recEmailPage = page;
    const tbody = document.getElementById('recEmailTbody');
    tbody.innerHTML =
      '<tr><td colspan="5" style="text-align:center;color:#888;padding:20px">Loading…</td></tr>';
    const data = await recApiGet(`/api/admin/recruitment/email-log?page=${page}`);
    if (!data || !data.logs.length) {
      tbody.innerHTML =
        '<tr><td colspan="5" style="text-align:center;color:#888;padding:20px">No emails logged yet.</td></tr>';
      return;
    }
    tbody.innerHTML = data.logs.map(l => `<tr>
      <td>${esc(l.recipient)}</td>
      <td>${esc(l.event_type)}</td>
      <td><span class="rec-pill ${l.status === 'sent' ? 'rec-pill-pass' : 'rec-pill-fail'}">${esc(l.status)}</span></td>
      <td style="color:#888">${l.sent_at ? l.sent_at.slice(0, 16) : '—'}</td>
      <td>${l.status === 'failed'
        ? `<button class="btn btn-ghost" type="button"
             style="padding:3px 10px;font-size:.8rem"
             onclick="resendRecEmail(${l.id})">Resend</button>`
        : '—'}</td>
    </tr>`).join('');

    const total = data.total, pp = data.per_page;
    document.getElementById('recEmailPagination').innerHTML = `
      <button type="button" class="btn btn-ghost"
        onclick="loadRecEmailLog(${page - 1})" ${page <= 1 ? 'disabled' : ''}>← Previous</button>
      <span class="page-indicator font-mono">Page ${page} of ${Math.max(1, Math.ceil(total / pp))}</span>
      <button type="button" class="btn btn-ghost"
        onclick="loadRecEmailLog(${page + 1})" ${page * pp >= total ? 'disabled' : ''}>Next →</button>`;
  };

  window.resendRecEmail = async function (logId) {
    const data = await recApiPost(`/api/admin/recruitment/email-log/${logId}/resend`, {});
    alert(data?.status === 'success' ? 'Email resent.' : 'Resend failed.');
    loadRecEmailLog(recEmailPage);
  };

  // ── Internal helpers ──────────────────────────────────────────────────
  function stagePill(stage) {
    if (['screening_passed', 'assessment_passed', 'offered', 'documents_submitted'].includes(stage))
      return 'rec-pill-pass';
    if (['screening_failed', 'assessment_failed', 'rejected'].includes(stage) ||
        (stage || '').includes('expired'))
      return 'rec-pill-fail';
    if (['applied', 'assessment_in_progress', 'interview_slot_pending', 'documents_pending'].includes(stage))
      return 'rec-pill-pending';
    return 'rec-pill-active';
  }

  function esc(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function recApiGet(url) {
    try { const r = await fetch(url); return r.ok ? await r.json() : null; }
    catch (e) { return null; }
  }

  async function recApiPost(url, body, method = 'POST') {
    try {
      const r = await fetch(url, {
        method,
        headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return await r.json();
    } catch (e) { return null; }
  }

  async function recApiFetch(url, method) {
    try {
      const r = await fetch(url, { method, headers: { 'X-CSRF-Token': csrf } });
      return await r.json();
    } catch (e) { return null; }
  }

  function showRecErr(el, msg) { el.textContent = msg; el.style.display = 'block'; }

})();
