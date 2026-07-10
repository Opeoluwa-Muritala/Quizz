(function () {
  'use strict';

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  
  function formatStageText(stage) {
    if (!stage) return '—';
    const map = {
      'applied': 'Applied',
      'screening_failed': 'Screening Failed',
      'screening_flagged': 'Screening Flagged',
      'screening_passed': 'Screening Passed',
      'assessment_in_progress': 'Assessment In Progress',
      'assessment_failed': 'Assessment Failed',
      'assessment_passed': 'Assessment Passed',
      'interview_slot_pending': 'Interview Slot Pending',
      'interview_scheduled': 'Interview Scheduled',
      'interview_completed': 'Interview Completed',
      'documents_pending': 'Documents Pending',
      'documents_submitted': 'Documents Submitted',
      'offered': 'Offered',
      'rejected': 'Rejected'
    };
    if (map[stage]) return map[stage];
    return stage.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function formatWAT(dateOrStr) {
    if (!dateOrStr) return '—';
    const d = new Date(dateOrStr);
    if (isNaN(d.getTime())) return '—';
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Africa/Lagos',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: true
    });
    const parts = formatter.formatToParts(d);
    const m = {};
    parts.forEach(p => m[p.type] = p.value);
    return `${m.year}-${m.month}-${m.day} ${m.hour}:${m.minute} ${m.dayPeriod.toLowerCase()}`;
  }

  let recInitialized = false;
  let recCandPage = 1;
  let recEmailPage = 1;
  let currentSlotId = null;
  let cvCurrentPage = 1;
  let cvBaseUrl = '';

  function getLocalDateString(d) {
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

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
    document.addEventListener('click', (event) => {
      const cvLink = event.target.closest('#cvOpenLink');
      if (cvLink) {
        event.preventDefault();
        document.getElementById('cvPreviewWrap')?.classList.toggle('expanded-preview');
        return;
      }
      const link = event.target.closest('a[href*="/documents/file/"]');
      if (!link) return;
      event.preventDefault();
      showAdminDocument(link.href);
    });
  });

  window.showAdminDocument = function (url) {
    let popup = document.getElementById('adminDocumentPopup');
    if (!popup) {
      popup = document.createElement('div');
      popup.id = 'adminDocumentPopup';
      popup.className = 'modal-overlay hidden';
      popup.innerHTML = '<div class="card" style="width:min(1100px,96vw);height:92vh;padding:12px;display:flex;flex-direction:column">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 4px 10px"><strong>Candidate document</strong>' +
        '<button type="button" class="btn btn-ghost" data-close-document>Close</button></div>' +
        '<iframe title="Candidate document" style="width:100%;flex:1;border:0;background:#f5f5f5"></iframe></div>';
      document.body.appendChild(popup);
      popup.querySelector('[data-close-document]').addEventListener('click', closeAdminDocument);
      popup.addEventListener('click', event => { if (event.target === popup) closeAdminDocument(); });
    }
    popup.querySelector('iframe').src = url;
    popup.classList.remove('hidden');
  };

  window.closeAdminDocument = function () {
    const popup = document.getElementById('adminDocumentPopup');
    if (!popup) return;
    popup.classList.add('hidden');
    popup.querySelector('iframe').src = 'about:blank';
  };

  // ── Sub-tab switching ─────────────────────────────────────────────────
  window.switchRecTab = function (name) {
    document.querySelectorAll('.rec-subtab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.rec-subpanel').forEach(p => p.classList.remove('active'));
    document.querySelector(`.rec-subtab[data-rec="${name}"]`).classList.add('active');
    document.getElementById(`rec-sub-${name}`).classList.add('active');

    // Toggle full-screen layout body class when slots subtab is selected
    const dashboardContainer = document.querySelector('.admin-dashboard-container');
    if (dashboardContainer) {
      if (name === 'slots') {
        dashboardContainer.classList.add('fullscreen-slots');
        dashboardContainer.classList.add('sidebar-collapsed');
      } else {
        dashboardContainer.classList.remove('fullscreen-slots');
        dashboardContainer.classList.remove('sidebar-collapsed');
      }
    }

    if (name === 'candidates')  loadRecCandidates(1);
    if (name === 'interviewers') loadRecInterviewers();
    if (name === 'slots') {
      loadRecInterviewerSelect('arInterviewer');
      loadRecInterviewerSelect('panelistAddSel');
      loadRecSlots();
    }
    if (name === 'config')   loadRecStageConfig();
    if (name === 'employmentdocs') loadEmploymentDocRoles();
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
        <td><span class="rec-pill ${stagePill(c.stage)}">${formatStageText(c.stage)}</span></td>
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
    ].map(s => `<option value="${s}" ${s === c.stage ? 'selected' : ''}>${formatStageText(s)}</option>`).join('');

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
              <td style="color:#888">${formatWAT(s.taken_at)}</td>
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
              <td>${formatWAT(s.start_time)}</td>
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
              <td style="color:#888">${formatWAT(h.at)}</td>
            </tr>`).join('')}</tbody>
          </table>
        </div>
      </details>` : '';

    document.getElementById('recCandModalContent').innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px">
        <div>
          <label style="font-size:.75rem;color:#888;display:block;margin-bottom:2px">Stage</label>
          <span class="rec-pill ${stagePill(c.stage)}">${formatStageText(c.stage)}</span>
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
      cvBaseUrl = url;
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

  // ── State-driven Calendar Redesign ──────────────────────────────────
  window.calendarState = window.calendarState || {
    view: 'week',
    currentDate: new Date(),
    slots: [],
    rules: [],
    interviewers: [],
    selectedInterviewers: new Set(),
    sidebarCollapsed: true,
    leftCalOpen: true,
    draggedSlot: null,
    selectionStart: null,
    selectionEnd: null,
    selectionColumn: null,
    selectedSlotIds: new Set()
  };

  function getMonday(d) {
    d = new Date(d);
    const day = d.getDay();
    const diff = d.getDate() - day + (day === 0 ? -6 : 1);
    return new Date(d.setDate(diff));
  }

  function formatTime(str) {
    if (!str) return '';
    const parts = str.split(':');
    return `${parts[0]}:${parts[1]}`;
  }

  function esc(s) {
    if (!s) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  window.loadRecSlots = async function () {
    // Ensure container has collapsed classes when active
    const dashboardContainer = document.querySelector('.admin-dashboard-container');
    if (dashboardContainer) {
      dashboardContainer.classList.add('fullscreen-slots');
      dashboardContainer.classList.add('sidebar-collapsed');
    }

    // 1. Fetch active interviewers if empty
    if (!window.calendarState.interviewers.length) {
      const data = await recApiGet('/api/admin/recruitment/interviewers');
      if (data) {
        window.calendarState.interviewers = data;
        const colors = ['#89268B', '#1E7A45', '#B8790A', '#2B6CB0', '#319795', '#D53F8C', '#4A5568'];
        window.calendarState.interviewers.forEach((it, idx) => {
          it.color = colors[idx % colors.length];
          window.calendarState.selectedInterviewers.add(it.id);
        });
      }
    }

    // 2. Fetch active rules
    if (!window.calendarState.rules.length) {
      const data = await recApiGet('/api/admin/recruitment/slots/rules');
      if (data) {
        window.calendarState.rules = data;
      }
    }



    // 3. Compute ranges
    let fromDate, toDate;
    const curr = new Date(window.calendarState.currentDate);
    if (window.calendarState.view === 'day') {
      fromDate = new Date(curr.setHours(0,0,0,0));
      toDate = new Date(curr.setHours(23,59,59,999));
    } else if (window.calendarState.view === 'week') {
      const mon = getMonday(curr);
      fromDate = new Date(mon.setHours(0,0,0,0));
      const sun = new Date(mon);
      sun.setDate(mon.getDate() + 6);
      toDate = new Date(sun.setHours(23,59,59,999));
    } else { // month
      fromDate = new Date(curr.getFullYear(), curr.getMonth(), 1, 0,0,0,0);
      toDate = new Date(curr.getFullYear(), curr.getMonth() + 1, 0, 23,59,59,999);
    }

    const fromStr = getLocalDateString(fromDate);
    const toStr = getLocalDateString(toDate);

    const data = await recApiGet(`/api/admin/recruitment/slots?from=${fromStr}&to=${toStr}`);
    window.calendarState.slots = data || [];

    const wrap = document.getElementById('recSlotsTableWrap') || document.getElementById('slotsTableWrap');
    if (!wrap) return;

    wrap.innerHTML = renderCalendarHTML();
    attachCalendarEvents();
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

  function renderCalendarHTML() {
    const state = window.calendarState;
    const curr = new Date(state.currentDate);

    // Compute Date range label
    let dateLabel = '';
    if (state.view === 'day') {
      dateLabel = curr.toLocaleDateString('en-NG', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    } else if (state.view === 'week') {
      const mon = getMonday(curr);
      const sun = new Date(mon);
      sun.setDate(mon.getDate() + 6);
      dateLabel = `${mon.toLocaleDateString('en-NG', { day: 'numeric', month: 'short' })} – ${sun.toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' })}`;
    } else {
      dateLabel = curr.toLocaleDateString('en-NG', { month: 'long', year: 'numeric' });
    }

    // Dynamic stats computation
    let openCount = 0, bookedCount = 0, blockedCount = 0;
    state.slots.forEach(s => {
      const iid = s.interviewer_id;
      if (!state.selectedInterviewers.has(iid)) return;
      if (s.is_blocked) blockedCount++;
      else if (s.is_booked) bookedCount++;
      else openCount++;
    });

    // Summary strip ( rls ratio )
    let summaryHtml = '';
    if (state.rules.length) {
      summaryHtml = state.rules.map(r => {
        return `<span class="summary-chip">${esc(r.interviewer_name)}: ${r.slot_duration}m slots · ${r.buffer}m breaks · ${formatTime(r.start_time)}–${formatTime(r.end_time)}</span>`;
      }).join(' ');
    } else {
      summaryHtml = 'No active availability configurations.';
    }

    // Interviewer Filter Chips
    const filterHtml = state.interviewers.map(it => {
      const isActive = state.selectedInterviewers.has(it.id);
      return `<button class="filter-chip ${isActive ? 'active' : ''}" style="color: ${it.color}" onclick="toggleInterviewerFilter(${it.id})">
        <span class="filter-chip-dot"></span>
        <span>${esc(it.name)}</span>
      </button>`;
    }).join('');

    return `
      <div class="cal-container">
        <!-- Top navigation and actions bar -->
        <div class="cal-topbar">
          <div class="cal-topbar-left">
            <button class="cal-menu-toggle" type="button" onclick="toggleSidebarMenu()" title="Toggle Sidebar">☰ Menu</button>
            <button class="cal-menu-toggle" type="button" onclick="toggleLeftMiniCal()" title="Toggle Mini Calendar"><i class="ti-calendar"></i> Mini-Cal</button>
            <span class="cal-wordmark">MMFB Calendar</span>
          </div>

          <div class="cal-topbar-center" style="display:flex;align-items:center;gap:14px">
            <div class="cal-view-switcher">
              <button class="cal-view-btn ${state.view === 'day' ? 'active' : ''}" onclick="switchCalView('day')">Day</button>
              <button class="cal-view-btn ${state.view === 'week' ? 'active' : ''}" onclick="switchCalView('week')">Week</button>
              <button class="cal-view-btn ${state.view === 'month' ? 'active' : ''}" onclick="switchCalView('month')">Month</button>
            </div>
            <div class="cal-nav">
              <button class="cal-nav-btn" onclick="navigateCalDate(-1)">‹</button>
              <button class="cal-nav-btn" style="width:auto;padding:0 12px;font-size:0.8rem;font-weight:600" onclick="navigateCalToday()">Today</button>
              <button class="cal-nav-btn" onclick="navigateCalDate(1)">›</button>
            </div>
            <span class="cal-date-label">${dateLabel}</span>
          </div>

          <div class="cal-topbar-right">
            <input class="rec-ctrl" type="date" id="jumpDate" style="width:140px;height:34px;padding:4px 10px" onchange="jumpToCalDate(this.value)">
            <button class="btn btn-primary" style="background:#276749;padding:6px 14px;font-size:0.82rem" onclick="triggerRecGenerate()">↻ Generate Slots</button>
            <button class="btn btn-ghost" style="padding:6px 14px;font-size:0.82rem;border:1px solid var(--mfb-gray-300)" onclick="printSchedule()">Print View</button>
          </div>
        </div>

        <!-- Summary bar ratio -->
        <div class="cal-summary-strip">
          <strong>Active Split Configurations WAT:</strong> ${summaryHtml}
        </div>

        <!-- Interviewer filters strip -->
        <div class="cal-filter-chips">
          <strong style="font-size:0.8rem;color:var(--mfb-gray-600);margin-right:8px">Panelists:</strong>
          ${filterHtml}
        </div>

        <!-- Live counts strip -->
        <div class="cal-stats-strip">
          <div class="stat-item open">● ${openCount} Open Available</div>
          <div class="stat-item booked">● ${bookedCount} Booked</div>
          <div class="stat-item blocked">● ${blockedCount} Blocked</div>
        </div>

        <!-- Calendar Area -->
        <div class="cal-body">
          <!-- Mini Month Grid Picker -->
          <div class="cal-sidebar ${state.leftCalOpen ? '' : 'collapsed'}" id="miniCalSidebar">
            ${renderMiniMonthHTML()}
          </div>

          <!-- Main Grid -->
          <div class="cal-grid-wrap" id="mainGridWrap">
            <span class="wat-label-corner">All times WAT (Africa/Lagos)</span>
            ${state.view === 'month' ? renderMonthViewHTML() : renderGridHTML()}
          </div>
        </div>
      </div>

      <!-- Print Layout (Hidden on Screen, visible on Print) -->
      ${renderPrintLayoutHTML()}
    `;
  }

  function renderMiniMonthHTML() {
    const state = window.calendarState;
    const center = new Date(state.currentDate);
    const year = center.getFullYear();
    const month = center.getMonth();

    const monthStart = new Date(year, month, 1);
    const monthEnd = new Date(year, month + 1, 0);

    const firstDayIndex = (monthStart.getDay() + 6) % 7; // Monday start index
    const daysInMonth = monthEnd.getDate();

    const prevMonthEnd = new Date(year, month, 0);
    const prevDays = prevMonthEnd.getDate();

    let cellsHtml = '';

    // Render day header names
    const days = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
    const headerHtml = days.map(d => `<div class="mini-day-name">${d}</div>`).join('');

    // Previous month filler days
    for (let i = firstDayIndex; i > 0; i--) {
      const dNum = prevDays - i + 1;
      cellsHtml += `<div class="mini-day-cell other-month" onclick="jumpToMiniDate(${year}, ${month - 1}, ${dNum})">${dNum}</div>`;
    }

    // Days in current month
    const today = new Date();
    for (let d = 1; d <= daysInMonth; d++) {
      const isSelected = center.getDate() === d;
      
      // density calculation for dots on this day
      const dDateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      let hasOpen = false, hasBooked = false;
      state.slots.forEach(s => {
        if (s.start_time.startsWith(dDateStr)) {
          if (s.is_booked) hasBooked = true;
          else if (!s.is_blocked) hasOpen = true;
        }
      });

      let dotClass = '';
      if (hasOpen) dotClass = 'success';
      else if (hasBooked) dotClass = 'booked';

      cellsHtml += `
        <div class="mini-day-cell ${isSelected ? 'selected' : ''}" onclick="jumpToMiniDate(${year}, ${month}, ${d})">
          <span>${d}</span>
          ${dotClass ? `<span class="mini-day-dot ${dotClass}"></span>` : ''}
        </div>
      `;
    }

    // Next month filler
    const totalCells = firstDayIndex + daysInMonth;
    const nextFiller = (7 - (totalCells % 7)) % 7;
    for (let d = 1; d <= nextFiller; d++) {
      cellsHtml += `<div class="mini-day-cell other-month" onclick="jumpToMiniDate(${year}, ${month + 1}, ${d})">${d}</div>`;
    }

    const monthLabel = center.toLocaleDateString('en-NG', { month: 'short', year: 'numeric' });

    return `
      <div class="mini-month-header">
        <span>${monthLabel}</span>
        <div style="display:flex;gap:4px">
          <button class="cal-nav-btn" style="width:20px;height:20px;font-size:0.6rem" onclick="navigateMiniMonth(-1)">‹</button>
          <button class="cal-nav-btn" style="width:20px;height:20px;font-size:0.6rem" onclick="navigateMiniMonth(1)">›</button>
        </div>
      </div>
      <div class="mini-month-grid">
        ${headerHtml}
        ${cellsHtml}
      </div>
    `;
  }

  function renderMonthViewHTML() {
    const state = window.calendarState;
    const center = new Date(state.currentDate);
    const year = center.getFullYear();
    const month = center.getMonth();

    const start = new Date(year, month, 1);
    const end = new Date(year, month + 1, 0);

    const firstDayIndex = (start.getDay() + 6) % 7;
    const daysInMonth = end.getDate();

    const prevEnd = new Date(year, month, 0);
    const prevDays = prevEnd.getDate();

    let gridCells = '';

    // Day headers
    const dayLabels = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
    const headerHtml = dayLabels.map(l => `<div class="cal-header-cell">${l}</div>`).join('');

    // Prev month filler
    for (let i = firstDayIndex; i > 0; i--) {
      const dNum = prevDays - i + 1;
      gridCells += `<div class="month-cell other-month">
        <span class="month-cell-num">${dNum}</span>
      </div>`;
    }

    // Days in current month
    for (let d = 1; d <= daysInMonth; d++) {
      const dayDate = new Date(year, month, d);
      const dayDateStr = getLocalDateString(dayDate);

      let openCount = 0, bookedCount = 0;
      state.slots.forEach(s => {
        if (s.start_time.startsWith(dayDateStr) && state.selectedInterviewers.has(s.interviewer_id)) {
          if (s.is_booked) bookedCount++;
          else if (!s.is_blocked) openCount++;
        }
      });

      let dotsHtml = '';
      for (let i = 0; i < Math.min(openCount, 5); i++) {
        dotsHtml += '<span class="density-dot open"></span>';
      }
      for (let i = 0; i < Math.min(bookedCount, 5); i++) {
        dotsHtml += '<span class="density-dot booked"></span>';
      }

      gridCells += `
        <div class="month-cell" onclick="jumpToMonthCell('${dayDateStr}')">
          <span class="month-cell-num">${d}</span>
          <div style="font-size:0.7rem;color:var(--mfb-gray-600);font-weight:600">
            ${openCount > 0 ? `<div>${openCount} open</div>` : ''}
            ${bookedCount > 0 ? `<div>${bookedCount} booked</div>` : ''}
          </div>
          <div class="month-density-dots">${dotsHtml}</div>
        </div>
      `;
    }

    return `
      <div class="month-view-grid" style="display:grid;grid-template-columns:repeat(7,1fr)">
        ${headerHtml}
        ${gridCells}
      </div>
    `;
  }

  function renderGridHTML() {
    const state = window.calendarState;
    const curr = new Date(state.currentDate);

    // Compute working range hours
    let minHour = 8;
    let maxHour = 17;
    if (state.rules.length) {
      state.rules.forEach(r => {
        if (r.start_time) {
          const h = parseInt(r.start_time.split(':')[0]);
          if (h < minHour) minHour = h;
        }
        if (r.end_time) {
          const h = parseInt(r.end_time.split(':')[0]);
          if (h > maxHour) maxHour = h;
        }
      });
    }

    const startMinutes = minHour * 60;
    const endMinutes = maxHour * 60;
    const gridDuration = endMinutes - startMinutes;

    // Build Time axis column
    let timeAxisHtml = '<div class="time-axis-col" style="grid-row:2">';
    for (let h = minHour; h < maxHour; h++) {
      timeAxisHtml += `
        <div class="time-axis-cell">${String(h).padStart(2, '0')}:00</div>
      `;
    }
    timeAxisHtml += '</div>';

    // Columns
    let columns = [];
    if (state.view === 'day') {
      columns = [new Date(curr)];
    } else { // week
      const mon = getMonday(curr);
      for (let i = 0; i < 7; i++) {
        const colDay = new Date(mon);
        colDay.setDate(mon.getDate() + i);
        columns.push(colDay);
      }
    }

    // Grid layout CSS settings
    const colCount = columns.length;
    const gridStyle = `grid-template-columns: 60px repeat(${colCount}, 1fr);`;

    // Header cells
    let headerCellsHtml = '<div class="cal-header-cell"></div>'; // empty corner cell
    columns.forEach(colDate => {
      const label = colDate.toLocaleDateString('en-NG', { weekday: 'short', day: 'numeric', month: 'numeric' });
      headerCellsHtml += `<div class="cal-header-cell">${label}</div>`;
    });

    // Content cells
    let contentColsHtml = '';
    columns.forEach((colDate, colIdx) => {
      const colDateStr = getLocalDateString(colDate);

      // Filter slots for this column date and selected interviewers
      const colSlots = state.slots.filter(s => {
        const d = s.start_time.split('T')[0];
        return d === colDateStr && state.selectedInterviewers.has(s.interviewer_id);
      });

      // Render slots inside this column
      let slotBlocksHtml = '';
      colSlots.forEach(slot => {
        const sTime = new Date(slot.start_time);
        const eTime = new Date(slot.end_time);

        // Convert times into minutes since midnight (WAT zone base)
        // Note: New Date converts UTC strings to local browser timezone.
        // We calculate delta minutes in local browser representation.
        const sMins = sTime.getHours() * 60 + sTime.getMinutes();
        const eMins = eTime.getHours() * 60 + eTime.getMinutes();

        const top = sMins - startMinutes;
        const height = eMins - sMins;

        // Clip block if outside the working hours window
        if (top < 0 || top + height > gridDuration) return;

        // Check conflicts (overlapping times for the same interviewer)
        const overlap = colSlots.some(other => {
          if (other.id === slot.id || other.interviewer_id !== slot.interviewer_id) return false;
          const s1 = new Date(slot.start_time).getTime();
          const e1 = new Date(slot.end_time).getTime();
          const s2 = new Date(other.start_time).getTime();
          const e2 = new Date(other.end_time).getTime();
          return (s1 < e2 && s2 < e1);
        });

        // Determine title
        const interviewerColor = getInterviewerColor(slot.interviewer_id);
        const initials = getInterviewerInitials(slot.interviewer);
        const titleStr = slot.title || `${esc(slot.interviewer)} — Slot`;

        // Status class
        let statusClass = 'open';
        if (slot.is_blocked) statusClass = 'blocked';
        else if (slot.is_booked) statusClass = 'booked';

        const timeStr = `${sTime.toLocaleTimeString('en-NG', {hour:'2-digit', minute:'2-digit'})} – ${eTime.toLocaleTimeString('en-NG', {hour:'2-digit', minute:'2-digit'})}`;

        slotBlocksHtml += `
          <div class="slot-block ${statusClass} ${overlap ? 'conflict' : ''}" 
               style="top: ${top}px; height: ${height}px; border-left-color: ${interviewerColor}; color: ${interviewerColor}" 
               id="slot-${slot.id}"
               draggable="${!slot.is_blocked}"
               ondragstart="onSlotDragStart(event, ${slot.id})"
               onclick="onSlotClick(event, ${slot.id})">
            
            <div class="slot-block-header">
              <span class="slot-title" contenteditable="true" 
                    onblur="onSlotRename(event, ${slot.id})" 
                    onclick="event.stopPropagation()"
                    onkeydown="onSlotRenameKey(event, ${slot.id})">${titleStr}</span>
              ${overlap ? '<i class="ti-alert-triangle" style="color:var(--mfb-error);font-size:0.9rem" title="Conflict: Overlapping Interviewer Slot"></i>' : ''}
              <span class="avatar-chip" style="background: ${interviewerColor}">${initials}</span>
            </div>
            
            <div style="display:flex; justify-content:space-between; align-items:flex-end">
              <span class="slot-time">${timeStr}</span>
              ${slot.is_booked ? `<span class="slot-candidate">${esc(slot.candidate_name)}</span>` : ''}
            </div>
          </div>

          <!-- Breaks Buffer thin strip (only renders if buffer > 0) -->
          <div class="cal-break" style="top: ${top + height}px; height: 10px;" title="Break Buffer" onclick="event.stopPropagation()"></div>
        `;
      });

      contentColsHtml += `
        <div class="cal-column" style="height: ${gridDuration}px" 
             data-date="${colDateStr}" 
             data-column="${colIdx}"
             ondragover="onColDragOver(event)"
             ondrop="onColDrop(event, '${colDateStr}')"
             onmousedown="onGridMouseDown(event, ${colIdx})"
             onmousemove="onGridMouseMove(event)"
             onmouseup="onGridMouseUp(event)">
          ${slotBlocksHtml}
        </div>
      `;
    });

    return `
      <div class="cal-grid" style="${gridStyle}">
        <div class="cal-header-row" style="${gridStyle} grid-column:1 / -1">
          ${headerCellsHtml}
        </div>
        ${timeAxisHtml}
        <div class="cal-grid-content" style="grid-row:2; grid-column:2 / -1; grid-template-columns: repeat(${colCount}, 1fr)">
          ${contentColsHtml}
        </div>
      </div>
    `;
  }

  function renderPrintLayoutHTML() {
    const state = window.calendarState;
    
    // Header cells
    let colDates = [];
    const curr = new Date(state.currentDate);
    if (state.view === 'day') {
      colDates = [new Date(curr)];
    } else {
      const mon = getMonday(curr);
      for (let i = 0; i < 7; i++) {
        const c = new Date(mon);
        c.setDate(mon.getDate() + i);
        colDates.push(c);
      }
    }

    // List out slots formatted for table
    const tableRows = state.slots
      .filter(s => state.selectedInterviewers.has(s.interviewer_id))
      .map(s => {
        const sTime = new Date(s.start_time);
        const eTime = new Date(s.end_time);
        const dateStr = sTime.toLocaleDateString('en-NG', { day: 'numeric', month: 'short' });
        const timeStr = `${sTime.toLocaleTimeString('en-NG', {hour:'2-digit', minute:'2-digit'})} – ${eTime.toLocaleTimeString('en-NG', {hour:'2-digit', minute:'2-digit'})}`;
        
        let status = 'Available';
        if (s.is_blocked) status = 'Blocked';
        else if (s.is_booked) status = `Booked by ${s.candidate_name}`;

        return `
          <tr>
            <td>${dateStr}</td>
            <td>${timeStr}</td>
            <td>${esc(s.title || 'Interview Slot')}</td>
            <td>${esc(s.interviewer)}</td>
            <td>${status}</td>
          </tr>
        `;
      }).join('');

    return `
      <div class="print-schedule-layout" id="printLayout">
        <h1 class="print-title">Mainstreet MMFB Interview Schedule</h1>
        <p class="print-meta">Generated on ${new Date().toLocaleDateString('en-NG')} | WAT (Africa/Lagos) Timezone</p>
        <table class="print-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Time</th>
              <th>Slot Title</th>
              <th>Interviewer / Panel</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows || '<tr><td colspan="5" style="text-align:center">No slots scheduled in this view range.</td></tr>'}
          </tbody>
        </table>
      </div>
    `;
  }

  function getInterviewerColor(id) {
    const state = window.calendarState;
    const found = state.interviewers.find(i => i.id === id);
    return found ? found.color : '#6B6470';
  }

  function getInterviewerInitials(name) {
    if (!name) return 'I';
    const parts = name.split(' ');
    if (parts.length > 1) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  }

  // Event handlers
  window.toggleInterviewerFilter = function (id) {
    const state = window.calendarState;
    if (state.selectedInterviewers.has(id)) {
      state.selectedInterviewers.delete(id);
    } else {
      state.selectedInterviewers.add(id);
    }
    loadRecSlots();
  };

  window.switchCalView = function (viewName) {
    window.calendarState.view = viewName;
    loadRecSlots();
  };

  window.navigateCalDate = function (direction) {
    const state = window.calendarState;
    const curr = new Date(state.currentDate);
    if (state.view === 'day') {
      curr.setDate(curr.getDate() + direction);
    } else if (state.view === 'week') {
      curr.setDate(curr.getDate() + (direction * 7));
    } else { // month
      curr.setMonth(curr.getMonth() + direction);
    }
    state.currentDate = curr;
    loadRecSlots();
  };

  window.navigateCalToday = function () {
    window.calendarState.currentDate = new Date();
    loadRecSlots();
  };

  window.jumpToCalDate = function (dateStr) {
    if (!dateStr) return;
    window.calendarState.currentDate = new Date(dateStr);
    loadRecSlots();
  };

  window.toggleLeftMiniCal = function () {
    window.calendarState.leftCalOpen = !window.calendarState.leftCalOpen;
    loadRecSlots();
  };

  window.toggleSidebarMenu = function () {
    const dashboardContainer = document.querySelector('.admin-dashboard-container');
    if (dashboardContainer) {
      dashboardContainer.classList.toggle('sidebar-collapsed');
    }
  };

  window.jumpToMiniDate = function (year, month, day) {
    window.calendarState.currentDate = new Date(year, month, day);
    loadRecSlots();
  };

  window.navigateMiniMonth = function (direction) {
    const curr = new Date(window.calendarState.currentDate);
    curr.setMonth(curr.getMonth() + direction);
    window.calendarState.currentDate = curr;
    loadRecSlots();
  };

  window.jumpToMonthCell = function (dateStr) {
    window.calendarState.currentDate = new Date(dateStr);
    window.calendarState.view = 'day';
    loadRecSlots();
  };

  // Editable slot titles
  window.onSlotRenameKey = function (event, slotId) {
    if (event.key === 'Enter') {
      event.preventDefault();
      event.target.blur();
    }
  };

  window.onSlotRename = async function (event, slotId) {
    const newTitle = event.target.textContent.trim();
    if (!newTitle) return;
    
    // PUT update
    await recApiPost(`/api/admin/recruitment/slots/${slotId}`, { title: newTitle }, 'PUT');
  };

  // Drag and Drop (reschedule)
  window.onSlotDragStart = function (event, slotId) {
    window.calendarState.draggedSlot = window.calendarState.slots.find(s => s.id === slotId);
    event.dataTransfer.setData('text/plain', slotId);
  };

  window.onColDragOver = function (event) {
    event.preventDefault();
  };

  window.onColDrop = async function (event, dateStr) {
    event.preventDefault();
    const slot = window.calendarState.draggedSlot;
    if (!slot) return;

    // Calculate Y coordinates relative to column element
    const rect = event.currentTarget.getBoundingClientRect();
    const y = event.clientY - rect.top; // pixel position

    // Working hours offset
    let minHour = 8;
    if (window.calendarState.rules.length) {
      window.calendarState.rules.forEach(r => {
        if (r.start_time) {
          const h = parseInt(r.start_time.split(':')[0]);
          if (h < minHour) minHour = h;
        }
      });
    }

    const startMinutes = minHour * 60;
    const droppedMinutes = Math.round(y) + startMinutes;

    // Convert slot start and end to datetime objects
    const originalDuration = (new Date(slot.end_time).getTime() - new Date(slot.start_time).getTime());

    // Construct new start and end times local
    const droppedHour = Math.floor(droppedMinutes / 60);
    const droppedMin = droppedMinutes % 60;

    const newStartLocal = new Date(`${dateStr}T${String(droppedHour).padStart(2,'0')}:${String(droppedMin).padStart(2,'0')}:00`);
    const newEndLocal = new Date(newStartLocal.getTime() + originalDuration);

    const newStartISO = newStartLocal.toISOString();
    const newEndISO = newEndLocal.toISOString();

    const doReschedule = async () => {
      const res = await recApiPost(`/api/admin/recruitment/slots/${slot.id}`, {
        start_time: newStartISO,
        end_time: newEndISO
      }, 'PUT');
      if (res?.status === 'success') {
        loadRecSlots();
      } else {
        alert(res?.error || 'Failed to reschedule slot.');
      }
    };

    if (slot.is_booked) {
      const confirmStr = `Are you sure you want to reschedule this BOOKED slot?\nCandidate: ${slot.candidate_name}\nOriginal Time: ${formatWAT(slot.start_time)}\nNew Time: ${formatWAT(newStartLocal)}\n\nProceeding will automatically trigger an email notification to the candidate.`;
      if (confirm(confirmStr)) {
        await doReschedule();
      }
    } else {
      await doReschedule();
    }

    window.calendarState.draggedSlot = null;
  };

  // Hover Popovers for Booked Slots
  window.onSlotClick = function (event, slotId) {
    event.stopPropagation();
    const slot = window.calendarState.slots.find(s => s.id === slotId);
    if (!slot || !slot.is_booked) return;

    // Remove any existing popovers
    document.querySelectorAll('.cal-popover').forEach(p => p.remove());

    const popover = document.createElement('div');
    popover.className = 'cal-popover';

    const viewerUrl = `/admin#candidates`; // fallback navigation or detail view
    const meetingLinkHtml = slot.meeting_link 
      ? `<a href="${slot.meeting_link}" target="_blank" class="cal-popover-link" style="margin-right:12px">Join Meeting</a>`
      : '<em>No meeting link</em>';

    popover.innerHTML = `
      <div class="cal-popover-header">
        <span>Booked Interview</span>
        <button class="cal-popover-close" onclick="closeCalPopover(event)">✕</button>
      </div>
      <div class="cal-popover-row">Candidate: <strong>${esc(slot.candidate_name)}</strong></div>
      <div class="cal-popover-row">Role: <strong>${esc(slot.candidate_role || 'General')}</strong></div>
      <div class="cal-popover-row">Email: <strong>${esc(slot.candidate_email)}</strong></div>
      <div class="cal-popover-row">Panel: <strong>${esc(slot.interviewers || slot.interviewer)}</strong></div>
      <div class="cal-popover-row">Provider: <strong>${esc(slot.meeting_provider || 'Google Meet')}</strong></div>
      <div style="margin-top:12px; display:flex; align-items:center;">
        ${meetingLinkHtml}
        <a href="/admin" onclick="viewCandidateDetails(${slot.candidate_id})" class="cal-popover-link">View Detail</a>
      </div>
    `;

    // Position popover next to clicked block
    const rect = event.currentTarget.getBoundingClientRect();
    popover.style.top = `${rect.top + window.scrollY + 10}px`;
    popover.style.left = `${rect.left + window.scrollX + 20}px`;

    document.body.appendChild(popover);
  };

  window.closeCalPopover = function (event) {
    if (event) event.stopPropagation();
    document.querySelectorAll('.cal-popover').forEach(p => p.remove());
  };

  window.viewCandidateDetails = function (candidateId) {
    // Triggers candidates tab view in standard admin page
    closeCalPopover();
    switchRecTab('candidates');
    // Open standard profile viewer
    if (window.openRecCandModal) {
      window.openRecCandModal(candidateId);
    }
  };

  // Close popover on document click
  document.addEventListener('click', () => {
    closeCalPopover();
  });

  // Range select blocking/unblocking
  window.onGridMouseDown = function (event, colIdx) {
    if (event.target !== event.currentTarget) return; // only select on empty space
    const rect = event.currentTarget.getBoundingClientRect();
    const y = event.clientY - rect.top;

    window.calendarState.selectionStart = y;
    window.calendarState.selectionColumn = colIdx;

    // Create a selection overlay helper
    const colEl = event.currentTarget;
    let overlay = colEl.querySelector('.cal-selection-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'cal-selection-overlay';
      colEl.appendChild(overlay);
    }
    overlay.style.top = `${y}px`;
    overlay.style.height = '0px';
  };

  window.onGridMouseMove = function (event) {
    const state = window.calendarState;
    if (state.selectionStart === null) return;

    const colEl = event.currentTarget;
    const rect = colEl.getBoundingClientRect();
    const y = event.clientY - rect.top;

    const overlay = colEl.querySelector('.cal-selection-overlay');
    if (overlay) {
      const top = Math.min(state.selectionStart, y);
      const height = Math.abs(y - state.selectionStart);
      overlay.style.top = `${top}px`;
      overlay.style.height = `${height}px`;
    }
  };

  window.onGridMouseUp = async function (event) {
    const state = window.calendarState;
    if (state.selectionStart === null) return;

    const colEl = event.currentTarget;
    const rect = colEl.getBoundingClientRect();
    const y = event.clientY - rect.top;

    const overlay = colEl.querySelector('.cal-selection-overlay');
    if (overlay) overlay.remove();

    // Map starting/ending range minutes
    let minHour = 8;
    if (state.rules.length) {
      state.rules.forEach(r => {
        if (r.start_time) {
          const h = parseInt(r.start_time.split(':')[0]);
          if (h < minHour) minHour = h;
        }
      });
    }

    const startMinutes = minHour * 60;
    const minMins = Math.min(state.selectionStart, y) + startMinutes;
    const maxMins = Math.max(state.selectionStart, y) + startMinutes;

    const colDateStr = colEl.dataset.date;
    
    // Find all slots falling inside this timeframe
    const targetSlots = state.slots.filter(s => {
      const d = s.start_time.split('T')[0];
      if (d !== colDateStr) return false;

      const sTime = new Date(s.start_time);
      const eTime = new Date(s.end_time);
      const sMins = sTime.getHours() * 60 + sTime.getMinutes();
      const eMins = eTime.getHours() * 60 + eTime.getMinutes();

      // Check if slot overlaps selected range
      return (sMins >= minMins && eMins <= maxMins) && !s.is_booked;
    });

    if (targetSlots.length > 0) {
      const slotIds = targetSlots.map(s => s.id);
      const action = confirm(`Do you want to BLOCK ${slotIds.length} slots in this range?`) ? true : false;
      
      // Call batch post
      await recApiPost('/api/admin/recruitment/slots/batch-block', {
        slot_ids: slotIds,
        blocked: action
      });
      loadRecSlots();
    }

    // Reset selection state
    state.selectionStart = null;
    state.selectionColumn = null;
  };

  // Print schedule launcher
  window.printSchedule = function () {
    window.print();
  };

  function attachCalendarEvents() {
    // Add jumpDate value listener sync
    const jump = document.getElementById('jumpDate');
    if (jump) {
      const year = window.calendarState.currentDate.getFullYear();
      const month = String(window.calendarState.currentDate.getMonth() + 1).padStart(2,'0');
      const day = String(window.calendarState.currentDate.getDate()).padStart(2,'0');
      jump.value = `${year}-${month}-${day}`;
    }
  }

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
  window.stageExpandedState = window.stageExpandedState || {};
  window.stageOriginalData = window.stageOriginalData || {};
  window.showExpiredStages = window.showExpiredStages || false;

  window.toggleStageConfig = function (stageName) {
    const body = document.getElementById(`sbody-${stageName}`);
    const chev = document.getElementById(`chev-${stageName}`);
    if (!body) return;
    
    const isExpanded = body.classList.contains('expanded');
    if (isExpanded) {
      body.classList.remove('expanded');
      body.style.maxHeight = '0px';
      if (chev) chev.classList.remove('expanded');
      window.stageExpandedState[stageName] = false;
    } else {
      body.classList.add('expanded');
      body.style.maxHeight = body.scrollHeight + 'px';
      if (chev) chev.classList.add('expanded');
      window.stageExpandedState[stageName] = true;
    }
  };

  window.checkUnsavedConfig = function (stageName) {
    const orig = window.stageOriginalData[stageName];
    if (!orig) return;

    const oa = document.getElementById(`oa-${stageName}`)?.value || '';
    const ca = document.getElementById(`ca-${stageName}`)?.value || '';
    const pm = document.getElementById(`pm-${stageName}`)?.value || '';
    const dm = document.getElementById(`dm-${stageName}`)?.value || '';
    const rd = document.getElementById(`rd-${stageName}`)?.value || '';
    const minage = document.getElementById(`minage-${stageName}`)?.value || '';
    const maxage = document.getElementById(`maxage-${stageName}`)?.value || '';

    let isChanged = false;
    if (oa !== orig.opens_at) isChanged = true;
    if (ca !== orig.closes_at) isChanged = true;
    if (pm !== orig.pass_mark) isChanged = true;
    if (dm !== orig.duration_minutes) isChanged = true;
    if (rd !== orig.relative_deadline) isChanged = true;
    if (minage !== orig.min_age) isChanged = true;
    if (maxage !== orig.max_age) isChanged = true;

    const unsavedMsg = document.getElementById(`unsaved-${stageName}`);
    if (unsavedMsg) {
      unsavedMsg.style.display = isChanged ? 'inline' : 'none';
    }
  };

  window.toggleExpiredStages = function () {
    window.showExpiredStages = !window.showExpiredStages;
    const body = document.getElementById('expired-stages-body');
    const btn = document.getElementById('expired-toggle-btn');
    if (body) {
      if (window.showExpiredStages) {
        body.style.display = 'block';
        if (btn) btn.textContent = 'Hide expired stages';
      } else {
        body.style.display = 'none';
        if (btn) btn.textContent = 'Show expired stages';
      }
    }
  };

  window.loadRecStageConfig = async function () {
    const wrap = document.getElementById('recConfigGrid');
    const data = await recApiGet('/api/admin/recruitment/stage-config');
    if (!data) { wrap.innerHTML = '<p style="color:#c53030;font-family:var(--font-body)">Error loading config.</p>'; return; }

    // 1. Compute status for each stage
    const now = Date.now();
    data.forEach(cfg => {
      const o = cfg.opens_at ? new Date(cfg.opens_at).getTime() : null;
      const c = cfg.closes_at ? new Date(cfg.closes_at).getTime() : null;
      
      if (o && o > now) {
        cfg.computedStatus = 'not-open';
        cfg.statusLabel = 'Not yet open';
      } else if (c && c < now) {
        cfg.computedStatus = 'closed';
        cfg.statusLabel = 'Closed';
      } else {
        cfg.computedStatus = 'open';
        cfg.statusLabel = 'Open now';
      }
    });

    // 2. Sort stages to find Current and Next
    const STAGE_PIPELINE_ORDER = ['application', 'screening', 'assessment', 'interview', 'documents', 'final_decision'];
    const sortedStages = [...data].sort((a, b) => {
      if (a.cycle_id !== b.cycle_id) return a.cycle_id - b.cycle_id;
      const ai = STAGE_PIPELINE_ORDER.indexOf(a.stage_name);
      const bi = STAGE_PIPELINE_ORDER.indexOf(b.stage_name);
      return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    });

    let currentIdx = sortedStages.findIndex(s => s.computedStatus === 'open');
    let currentStage = null;
    let nextStage = null;
    if (currentIdx !== -1) {
      currentStage = sortedStages[currentIdx];
      if (currentIdx + 1 < sortedStages.length) {
        nextStage = sortedStages[currentIdx + 1];
      }
    }

    // 3. Define phases
    const PHASES = [
      { id: 'application', name: 'Application', dotClass: 'application', stages: ['application'] },
      { id: 'screening', name: 'Screening', dotClass: 'screening', stages: ['screening'] },
      { id: 'assessment', name: 'Assessment', dotClass: 'assessment', stages: ['assessment'] },
      { id: 'interview', name: 'Interview', dotClass: 'interview', stages: ['interview'] },
      { id: 'documents', name: 'Documents', dotClass: 'documents', stages: ['documents'] },
      { id: 'decision', name: 'Decision', dotClass: 'decision', stages: ['final_decision', 'decision'] },
      { id: 'expired', name: 'Expired', dotClass: 'expired', stages: [] } // dynamically populated
    ];

    // Assign stages to phases
    PHASES.forEach(p => p.stageConfigs = []);
    data.forEach(cfg => {
      const name = cfg.stage_name.toLowerCase();
      if (name.includes('expired')) {
        PHASES.find(p => p.id === 'expired').stageConfigs.push(cfg);
      } else {
        const matchedPhase = PHASES.find(p => p.stages.includes(name));
        if (matchedPhase) {
          matchedPhase.stageConfigs.push(cfg);
        } else {
          // Default fallback
          PHASES.find(p => p.id === 'application').stageConfigs.push(cfg);
        }
      }
    });

    // 4. Render phases
    let html = '<div class="stage-pipeline-container">';
    
    PHASES.forEach(phase => {
      if (phase.stageConfigs.length === 0 && phase.id !== 'expired') return;
      
      const isExpiredPhase = phase.id === 'expired';
      
      if (isExpiredPhase) {
        if (phase.stageConfigs.length === 0) return; // Only show expired header if there are actually expired stages
        
        html += `
        <div class="phase-group">
          <div class="phase-header" style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1.5px solid var(--mfb-gray-300); padding-bottom: 6px; margin-top: 16px;">
            <div style="display:flex; align-items:center; gap:8px;">
              <span class="phase-dot ${phase.dotClass}"></span>
              <span>${phase.name}</span>
            </div>
            <button id="expired-toggle-btn" class="expired-toggle-btn" type="button" onclick="toggleExpiredStages()">
              ${window.showExpiredStages ? 'Hide expired stages' : 'Show expired stages'}
            </button>
          </div>
          <div id="expired-stages-body" style="display: ${window.showExpiredStages ? 'block' : 'none'};">
        `;
      } else {
        html += `
        <div class="phase-group">
          <div class="phase-header">
            <span class="phase-dot ${phase.dotClass}"></span>
            <span>${phase.name}</span>
          </div>
        `;
      }

      phase.stageConfigs.forEach(cfg => {
        const isCurrent = currentStage && currentStage.stage_name === cfg.stage_name && currentStage.cycle_id === cfg.cycle_id;
        const isNext = nextStage && nextStage.stage_name === cfg.stage_name && nextStage.cycle_id === cfg.cycle_id;

        const oa = cfg.opens_at ? cfg.opens_at.slice(0, 16) : '';
        const ca = cfg.closes_at ? cfg.closes_at.slice(0, 16) : '';
        const datesOnly = DATE_ONLY_STAGES.has(cfg.stage_name);
        const daysMode = DEADLINE_IN_DAYS.has(cfg.stage_name);
        
        const rdVal = cfg.relative_deadline_hours !== null
          ? (daysMode ? Math.round(cfg.relative_deadline_hours / 24) : cfg.relative_deadline_hours)
          : '';
        const label = cfg.stage_name.replace(/_/g, ' ');

        const idxInSorted = sortedStages.findIndex(s => s.stage_name === cfg.stage_name);
        const nextStageObj = idxInSorted !== -1 && idxInSorted + 1 < sortedStages.length ? sortedStages[idxInSorted + 1] : null;
        const nextStageName = nextStageObj ? nextStageObj.stage_name : null;

        // Save original data for unsaved checking
        window.stageOriginalData[cfg.stage_name] = {
          opens_at: oa,
          closes_at: ca,
          pass_mark: cfg.pass_mark !== null ? String(cfg.pass_mark) : '',
          duration_minutes: cfg.duration_minutes !== null ? String(cfg.duration_minutes) : '',
          relative_deadline: String(rdVal),
          min_age: cfg.min_age !== null ? String(cfg.min_age) : '',
          max_age: cfg.max_age !== null ? String(cfg.max_age) : ''
        };

        const isExpanded = !!window.stageExpandedState[cfg.stage_name];

        html += `
        <div class="stg-row ${isCurrent ? 'is-current' : ''} ${isNext ? 'is-next' : ''}" id="row-${cfg.stage_name}">
          <div class="stg-header" onclick="toggleStageConfig('${cfg.stage_name}')">
            <div class="stg-header-left">
              <span class="phase-dot ${phase.dotClass}"></span>
              <span class="stg-name" style="text-transform: capitalize;">${esc(label)}</span>
              <span class="cycle-badge">cycle ${cfg.cycle_id}</span>
            </div>
            <div class="stg-header-right">
              ${isCurrent ? '<span class="badge-current">Current</span>' : ''}
              ${isNext ? '<span class="badge-next">Next</span>' : ''}
              <span class="status-chip ${cfg.computedStatus}">
                ${cfg.computedStatus === 'open' ? '●' : cfg.computedStatus === 'closed' ? '✕' : '○'} ${cfg.statusLabel}
              </span>
              <span class="stg-chevron ${isExpanded ? 'expanded' : ''}" id="chev-${cfg.stage_name}"><i class="ti-angle-right"></i></span>
            </div>
          </div>
          <div class="stg-body ${isExpanded ? 'expanded' : ''}" id="sbody-${cfg.stage_name}" style="max-height: ${isExpanded ? '650px' : '0px'}">
            <div class="stg-body-inner">
              <div class="stg-fields">
                <div class="stg-field">
                  <label>Opens At</label>
                  <input id="oa-${cfg.stage_name}" type="datetime-local" value="${oa}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>
                <div class="stg-field">
                  <label>Closes At</label>
                  <input id="ca-${cfg.stage_name}" type="datetime-local" value="${ca}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>
                ${!datesOnly && cfg.pass_mark !== null ? `
                <div class="stg-field">
                  <label>Pass Mark %</label>
                  <input id="pm-${cfg.stage_name}" type="number" step="0.5" min="0" max="100" value="${cfg.pass_mark}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>` : ''}
                ${!datesOnly && cfg.duration_minutes !== null ? `
                <div class="stg-field">
                  <label>Duration (min)</label>
                  <input id="dm-${cfg.stage_name}" type="number" min="1" value="${cfg.duration_minutes}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>` : ''}
                ${!datesOnly && cfg.relative_deadline_hours !== null ? `
                <div class="stg-field">
                  <label>Deadline (${daysMode ? 'days' : 'hrs'})</label>
                  <input id="rd-${cfg.stage_name}" type="number" min="0" value="${rdVal}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>` : ''}
                ${cfg.stage_name === 'screening' ? `
                <div class="stg-field">
                  <label>Min Age</label>
                  <input id="minage-${cfg.stage_name}" type="number" min="16" max="60" value="${cfg.min_age || 18}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>
                <div class="stg-field">
                  <label>Max Age</label>
                  <input id="maxage-${cfg.stage_name}" type="number" min="16" max="60" value="${cfg.max_age || 35}" oninput="checkUnsavedConfig('${cfg.stage_name}')">
                </div>` : ''}
              </div>
              <div class="stg-save-row" style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-top:16px;">
                <div style="display:flex; gap:8px;">
                  <button class="btn btn-sm" style="background:#e5f3ea; color:#1e7a45; font-size:0.75rem; border:1px solid #9ae6b4; padding:6px 12px; font-weight:600; border-radius:6px; cursor:pointer;" type="button" onclick="instantOpen('${esc(cfg.stage_name)}')">⚡ Instant Open</button>
                  <button class="btn btn-sm" style="background:#fbe9e8; color:#b3261e; font-size:0.75rem; border:1px solid #f5c2c0; padding:6px 12px; font-weight:600; border-radius:6px; cursor:pointer;" type="button" onclick="instantClose('${esc(cfg.stage_name)}')">⚡ Instant Close</button>
                  ${nextStageName ? `<button class="btn btn-sm" style="background:var(--mfb-purple-tint); color:var(--mfb-purple); font-size:0.75rem; border:1px solid var(--mfb-purple); padding:6px 12px; font-weight:600; border-radius:6px; cursor:pointer;" type="button" onclick="advanceToNext('${esc(cfg.stage_name)}', '${esc(nextStageName)}')">Next Stage →</button>` : ''}
                </div>
                <div style="display:flex; align-items:center; gap:8px;">
                  <span class="stg-unsaved-msg" id="unsaved-${cfg.stage_name}" style="display:none; color:var(--mfb-warning); font-size:0.8rem;">Unsaved changes</span>
                  <span class="stg-save-msg ok" id="cfgMsg-${cfg.stage_name}">✓ Saved!</span>
                  <button class="stg-save-btn" type="button" onclick="saveRecConfig('${esc(cfg.stage_name)}')">Save Changes</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        `;
      });

      if (isExpiredPhase) {
        html += '</div></div>';
      } else {
        html += '</div>';
      }
    });

    html += '</div>';
    wrap.innerHTML = html;
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

    const saveBtn = document.querySelector(`#row-${stageName} .stg-save-btn`);
    if (saveBtn) saveBtn.disabled = true;

    const data = await recApiPost(`/api/admin/recruitment/stage-config/${stageName}`, body, 'PUT');
    
    if (saveBtn) saveBtn.disabled = false;
    
    const msg = document.getElementById(`cfgMsg-${stageName}`);
    if (data?.status === 'success') {
      if (msg) {
        msg.className = 'stg-save-msg ok';
        msg.textContent = '✓ Saved!';
        msg.style.display = 'inline';
        setTimeout(() => { msg.style.display = 'none'; }, 2500);
      }
      // Re-load to update statuses and clear unsaved warnings
      await loadRecStageConfig();
    } else {
      if (msg) {
        msg.className = 'stg-save-msg err';
        msg.textContent = data?.error || 'Error.';
        msg.style.display = 'inline';
      }
    }
  };

  // ── Email Log ─────────────────────────────────────────────────────────
  const EMP_DOC_FORMATS = ['PDF', 'JPG', 'PNG'];
  const EMP_DOC_DEFAULTS = [
    ['nysc_certificate', 'NYSC certificate', ['PDF', 'JPG', 'PNG']],
    ['guarantor_form', 'Guarantor form', ['PDF', 'JPG', 'PNG']],
    ['utility_bill', 'Utility bill', ['PDF', 'JPG', 'PNG']],
    ['bank_statement', 'Bank statement', ['PDF']],
    ['passport_photograph', 'Passport photograph', ['JPG', 'PNG']],
  ];
  window.loadEmploymentDocRoles = async function () {
    const data = await recApiGet('/api/admin/recruitment/role-document-requirements');
    renderEmploymentDocRows((data?.documents?.length ? data.documents : defaultEmploymentDocs()).slice(0, 5));
  };

  window.loadEmploymentDocsForRole = async function (role) {
    const rows = document.getElementById('empDocRows');
    const status = document.getElementById('empDocStatus');
    if (!rows || !role) return;
    rows.innerHTML = '<p style="color:#888">Loading...</p>';
    if (status) status.textContent = '';
    const data = await recApiGet(`/api/admin/recruitment/role-document-requirements?role=${encodeURIComponent(role)}`);
    renderEmploymentDocRows((data?.documents?.length ? data.documents : defaultEmploymentDocs()).slice(0, 5));
  };

  window.saveEmploymentDocs = async function () {
    const status = document.getElementById('empDocStatus');
    const docs = Array.from(document.querySelectorAll('.emp-doc-row')).map((row, idx) => {
      const label = row.querySelector('[data-field="label"]')?.value.trim() || '';
      const documentType = (row.querySelector('[data-field="document_type"]')?.value.trim() || label)
        .toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
      const formats = Array.from(row.querySelectorAll('[data-field="format"]:checked')).map(cb => cb.value);
      return {
        document_type: documentType || `document_${idx + 1}`,
        label: label || `Document ${idx + 1}`,
        accepted_formats: formats.length ? formats : ['PDF'],
        required: true,
        position: idx + 1,
      };
    });
    if (docs.length !== 5) {
      if (status) status.textContent = 'Exactly five document rows are required.';
      return;
    }
    const data = await recApiPost('/api/admin/recruitment/role-document-requirements', { documents: docs }, 'PUT');
    if (status) {
      status.textContent = data?.status === 'success' ? 'Saved.' : (data?.message || 'Save failed.');
      status.style.color = data?.status === 'success' ? '#1E7A45' : '#B3261E';
    }
  };

  function defaultEmploymentDocs() {
    return EMP_DOC_DEFAULTS.map((d, idx) => ({
      document_type: d[0],
      label: d[1],
      accepted_formats: d[2],
      required: true,
      position: idx + 1,
    }));
  }

  function renderEmploymentDocRows(docs) {
    const rows = document.getElementById('empDocRows');
    if (!rows) return;
    rows.innerHTML = docs.map((doc, idx) => {
      const formats = doc.accepted_formats || [];
      return `<div class="emp-doc-row" style="border:1px solid var(--color-border);border-radius:8px;padding:12px;background:#fff">
        <div style="display:grid;grid-template-columns:56px 1fr 1fr;gap:12px;align-items:end">
          <div style="font-weight:700;color:var(--mfb-purple)">#${idx + 1}</div>
          <div class="form-group" style="margin:0">
            <label>Label</label>
            <input class="rec-ctrl" data-field="label" type="text" value="${esc(doc.label || '')}">
          </div>
          <div class="form-group" style="margin:0">
            <label>Document type</label>
            <input class="rec-ctrl" data-field="document_type" type="text" value="${esc(doc.document_type || '')}">
          </div>
        </div>
        <div style="display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:.85rem;color:#555">
          ${EMP_DOC_FORMATS.map(fmt => `<label style="display:flex;align-items:center;gap:6px">
            <input data-field="format" type="checkbox" value="${fmt}" ${formats.includes(fmt) ? 'checked' : ''}> ${fmt}
          </label>`).join('')}
          <label style="display:flex;align-items:center;gap:6px;color:#888">
            <input type="checkbox" checked disabled> Required
          </label>
        </div>
      </div>`;
    }).join('');
  }

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
    try {
      if (window.getAdminCached) return await window.getAdminCached(url);
      const r = await fetch(url);
      if (r.status === 401) { window.location.href = '/admin/login'; return new Promise(() => {}); }
      return r.ok ? await r.json() : null;
    }
    catch (e) { return null; }
  }

  async function recApiPost(url, body, method = 'POST') {
    try {
      const r = await fetch(url, {
        method,
        headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (r.status === 401) { window.location.href = '/admin/login'; return new Promise(() => {}); }
      return await r.json();
    } catch (e) { return null; }
  }

  async function recApiFetch(url, method) {
    try {
      const r = await fetch(url, { method, headers: { 'X-CSRF-Token': csrf } });
      if (r.status === 401) { window.location.href = '/admin/login'; return new Promise(() => {}); }
      return await r.json();
    } catch (e) { return null; }
  }

  function showRecErr(el, msg) { el.textContent = msg; el.style.display = 'block'; }

  window.instantOpen = async function (stageName) {
    await recApiPost(`/api/admin/recruitment/stage-config/${stageName}/open`, {});
    await window.loadRecStageConfig();
  };

  window.instantClose = async function (stageName) {
    await recApiPost(`/api/admin/recruitment/stage-config/${stageName}/close`, {});
    await window.loadRecStageConfig();
  };

  window.advanceToNext = async function (currentStageName, nextStageName) {
    await recApiPost(`/api/admin/recruitment/stage-config/${currentStageName}/next`, {});
    await window.loadRecStageConfig();
  };

})();
