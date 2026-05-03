(function () {
  'use strict';

  /* ── State ──────────────────────────────────────────────────── */
  let allJobs = [];
  let currentPage = 1;
  let totalJobs = 0;
  let pageSize = 50;
  let debounceTimer = null;
  let fetchJobsController = null;
  let logoDevPublishableKey = null;
  let hasLogoDevBrandSearch = false;
  let matcherEnabled = false;
  const activeRuns = new Map();         // runId -> { job, mode, startedAt, notifId }
  const activeAnalysisJobs = new Map(); // jobKey -> label (spinner state)
  let autoAnalyzerNotifId = null;
  let autoAnalyzerLastJobKey = null;
  let autoAnalyzerLastActive = false;
  let autoAnalyzerToastSig = null;

  const LOGO_BRAND_CACHE_MAX = 2000;
  const logoDevBrandDomains = new Map();
  const logoDevBrandLookupsInFlight = new Set();
  function logoBrandGet(key) {
    if (!logoDevBrandDomains.has(key)) return undefined;
    const val = logoDevBrandDomains.get(key);
    logoDevBrandDomains.delete(key);
    logoDevBrandDomains.set(key, val);
    return val;
  }
  function logoBrandSet(key, val) {
    if (logoDevBrandDomains.has(key)) logoDevBrandDomains.delete(key);
    else if (logoDevBrandDomains.size >= LOGO_BRAND_CACHE_MAX)
      logoDevBrandDomains.delete(logoDevBrandDomains.keys().next().value);
    logoDevBrandDomains.set(key, val);
  }

  const HIDDEN_KEY        = 'job-viewer:hidden';
  const VISITED_KEY       = 'job-viewer:visited';
  const FAV_COMPANIES_KEY = 'job-viewer:favorite-companies';

  let hiddenJobs        = loadSet(HIDDEN_KEY);
  let visitedJobs       = loadSet(VISITED_KEY);
  let favoriteCompanies = loadFaveMap();

  let lastHidden   = null;
  let panelJobData = null;
  let notifSeq     = 0;

  /* ── Storage helpers ─────────────────────────────────────────── */
  function loadSet(key) {
    try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')); }
    catch { return new Set(); }
  }
  function saveSet(key, set) {
    localStorage.setItem(key, JSON.stringify([...set]));
  }
  function loadFaveMap() {
    const map = new Map();
    try {
      const raw = JSON.parse(localStorage.getItem(FAV_COMPANIES_KEY) || '[]');
      if (!Array.isArray(raw)) return map;
      for (const item of raw) {
        const label = String(item || '').trim().replace(/\s+/g, ' ');
        const key = normCompany(label);
        if (!key || map.has(key)) continue;
        map.set(key, label);
      }
    } catch {}
    return map;
  }
  function saveFaveMap() {
    localStorage.setItem(FAV_COMPANIES_KEY, JSON.stringify([...favoriteCompanies.values()]));
  }

  /* ── Company helpers ─────────────────────────────────────────── */
  function normCompany(v) { return String(v || '').trim().replace(/\s+/g, ' ').toLowerCase(); }
  function companyName(job) {
    if (job.provider === 'workday') return job.source_key.split('/')[0];
    return job.source_key;
  }
  function isFav(company) { return favoriteCompanies.has(normCompany(company)); }
  function toggleFav(company) {
    const k = normCompany(company);
    if (favoriteCompanies.has(k)) { favoriteCompanies.delete(k); return false; }
    favoriteCompanies.set(k, String(company).trim().replace(/\s+/g, ' '));
    saveFaveMap();
    return true;
  }
  function addFav(company) {
    const label = String(company || '').trim().replace(/\s+/g, ' ');
    const k = normCompany(label);
    if (!k || favoriteCompanies.has(k)) return false;
    favoriteCompanies.set(k, label);
    saveFaveMap();
    return true;
  }
  function removeFav(key) { favoriteCompanies.delete(key); saveFaveMap(); }

  /* ── Logo helpers ────────────────────────────────────────────── */
  function hasLogo() { return typeof logoDevPublishableKey === 'string' && logoDevPublishableKey.length > 0; }
  function logoUrl(company) {
    if (!hasLogo()) return null;
    const cached = logoBrandGet(normCompany(company));
    if (cached) return `https://img.logo.dev/${encodeURIComponent(cached)}?token=${encodeURIComponent(logoDevPublishableKey)}&size=32&format=png&fallback=404`;
    const name = encodeURIComponent(String(company || '').trim());
    return `https://img.logo.dev/name/${name}?token=${encodeURIComponent(logoDevPublishableKey)}&size=32&format=png&fallback=404`;
  }
  function companyWebsite(company) {
    const d = logoBrandGet(normCompany(company));
    return d ? `https://${d}` : null;
  }
  function ensureBrand(company) {
    if (!hasLogoDevBrandSearch) return;
    const k = normCompany(company);
    if (!k || logoDevBrandDomains.has(k) || logoDevBrandLookupsInFlight.has(k)) return;
    logoDevBrandLookupsInFlight.add(k);
    fetch(`/api/logo-dev/brand?company=${encodeURIComponent(company)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const d = typeof data?.domain === 'string' && data.domain.trim() ? data.domain.trim() : null;
        logoBrandSet(k, d);
      })
      .catch(() => logoBrandSet(k, null))
      .finally(() => { logoDevBrandLookupsInFlight.delete(k); renderCurrentView(); });
  }

  /* ── Key / visited ───────────────────────────────────────────── */
  function jobKey(job) { return `${job.provider}|${job.source_key}|${job.job_id}`; }
  function markVisited(key) {
    visitedJobs.delete(key); visitedJobs.add(key);
    saveSet(VISITED_KEY, new Set([...visitedJobs].slice(-500)));
  }

  async function syncHiddenJobs() {
    try {
      await fetch('/api/hidden-jobs', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hidden: [...hiddenJobs] })
      });
    } catch {
      // Hiding remains local even if the background analyzer sync is temporarily unavailable.
    }
  }

  /* ── Age badge ───────────────────────────────────────────────── */
  function ageBadgeHtml(dateStr) {
    if (!dateStr) return '<span class="ats-pill">unknown</span>';
    const dt = new Date(dateStr);
    const days = Math.floor((Date.now() - dt.getTime()) / 86400000);
    const label = days === 0 ? 'today' : days === 1 ? '1d ago' : `${days}d ago`;
    const color = days <= 3 ? '#16a34a' : days <= 14 ? '#d97706' : '#b91c1c';
    const tip = dt.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
    return `<span class="ats-pill" style="color:${color};border-color:${color}22;background:${color}0d;" title="${esc(tip)}">${label}</span>`;
  }

  /* ── Work mode ───────────────────────────────────────────────── */
  function workMode(job, analysis) {
    const rp = String(analysis?.role_summary?.remote_policy || '').toLowerCase();
    const loc = String(job.location || '').toLowerCase();
    const v = `${rp} ${loc}`;
    if (v.includes('hybrid')) return 'Hybrid';
    if (v.includes('remote')) return 'Remote';
    if (v.includes('on-site') || v.includes('onsite') || v.includes('in office')) return 'On-site';
    return 'Unknown';
  }
  function empType(v) {
    const r = String(v || '').trim().toLowerCase();
    if (!r) return 'Unknown';
    if (r.includes('full')) return 'Full-time';
    if (r.includes('part')) return 'Part-time';
    return r.replace(/\b\w/g, c => c.toUpperCase());
  }

  /* ── Logo frame HTML ─────────────────────────────────────────── */
  function logoFrameHtml(company) {
    const url = logoUrl(company);
    const initials = esc((String(company || '').trim().charAt(0) || '?').toUpperCase());
    if (url) {
      return `<span class="company-logo-frame" data-fallback="${initials}"><img src="${esc(url)}" alt="" loading="lazy" referrerpolicy="no-referrer"></span>`;
    }
    return `<span class="company-logo-frame">${initials}</span>`;
  }

  /* ── Score pill HTML ─────────────────────────────────────────── */
  function scorePillHtml(score, jobKey_) {
    const tier = score >= 4 ? 'high' : score >= 3 ? 'mid' : 'low';
    return `<span class="score-pill" data-tier="${tier}" data-jkey="${esc(jobKey_)}">${score.toFixed(1)}<span class="max">/5</span></span>`;
  }

  /* ── Footer HTML ─────────────────────────────────────────────── */
  // Pipeline metadata: color, label, CSS class, spark color class
  const PIPELINES = {
    'claude':          { color: '#0d9488', label: 'Quick',  btnClass: 'btn-analyze--claude',     spark: 'btn-spark--teal',   dur: '~25s',  swatchClass: 'menu-swatch--claude' },
    'claude-ensemble': { color: '#4338ca', label: 'Full',   btnClass: 'btn-analyze--claude-ens', spark: 'btn-spark--indigo', dur: '~2min', swatchClass: 'menu-swatch--claude-ens' },
  };

  function footerHtml(job) {
    const pipelines = job.pipelines || {};
    const btn = (mode, jsClass) => {
      const p = PIPELINES[mode];
      const result = pipelines[mode];
      const score = Number(result?.analysis?.score_5 || 0);
      const scoreBadge = score > 0
        ? `<button class="btn-score-badge js-open-panel-pipeline" data-pipeline="${esc(mode)}" style="background:${p.color}" title="Open analysis">${score.toFixed(1)}<span class="btn-score-badge-max">/5</span></button>`
        : '';
      return `
      <div class="btn-analyze-wrap">
        <button class="btn btn-analyze ${p.btnClass} ${jsClass}${score > 0 ? ' ran' : ''}" title="${p.label} analysis · ${p.dur}">
          <span class="btn-spark ${p.spark}">✦</span> ${esc(p.label)} analyze
        </button>
        ${scoreBadge}
      </div>`;
    };

    return `
      ${btn('claude',          'js-analyze-claude')}
      ${btn('claude-ensemble', 'js-analyze-claude-ens')}
      <button class="btn btn-ghost js-jd-data" title="Extracted JD data">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg> JD data
      </button>
      <button class="btn btn-ghost js-hide">Not interested</button>`;
  }

  function bindFooterEvents(footer, job) {
    footer.querySelectorAll('.js-open-panel-pipeline').forEach(el => {
      el.addEventListener('click', () => openPanel(job, el.dataset.pipeline));
    });
    footer.querySelector('.js-analyze-claude')?.addEventListener('click',     () => analyzeJob(job, null, 'claude'));
    footer.querySelector('.js-analyze-claude-ens')?.addEventListener('click', () => analyzeJob(job, null, 'claude-ensemble'));
    footer.querySelector('.js-jd-data')?.addEventListener('click',            () => openJdModal(job));
    footer.querySelector('.js-hide')?.addEventListener('click',               () => hideJob(jobKey(job), job));
  }

  /* ── Recommendation label ────────────────────────────────────── */
  function recLabel(v) {
    const m = { apply_now:'Apply now', worth_applying:'Worth applying', only_if_strategic:'Only if strategic', do_not_apply:'Do not apply' };
    return m[v] || v || 'n/a';
  }

  /* ── esc ─────────────────────────────────────────────────────── */
  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── Render jobs ─────────────────────────────────────────────── */
  function renderJobs(jobs) {
    const list = document.getElementById('jobs-list');
    list.innerHTML = '';
    for (const job of jobs) {
      const key     = jobKey(job);
      const comp    = companyName(job);
      const fav     = isFav(comp);
      const vis     = visitedJobs.has(key);
      const anal    = job.analysis || null;
      const score   = Number(anal?.score_5 || 0);
      const hasAnal = anal && score > 0;
      const mode    = workMode(job, anal);
      const type    = empType(job.employment_type);
      const website = companyWebsite(comp);
      ensureBrand(comp);

      const compLogoFrame = logoFrameHtml(comp);
      const compNameHtml = website
        ? `<a class="company-link" href="${esc(website)}" target="_blank" rel="noopener">${compLogoFrame}<span class="company-name">${esc(comp)}</span></a>`
        : `<span style="display:inline-flex;align-items:center;gap:10px;">${compLogoFrame}<span class="company-name">${esc(comp)}</span></span>`;
      const metaText = (value, max = 40) => {
        const text = String(value || '').trim();
        if (!text) return '';
        const short = text.length > max ? text.slice(0, max - 3) + '…' : text;
        return short === text ? `<span>${esc(text)}</span>` : `<span title="${esc(text)}">${esc(short)}</span>`;
      };
      const cleanCompensation = isRealCompensation(job.compensation) ? job.compensation : null;
      const salaryRange = extractSalaryRange(cleanCompensation);
      const jdMeta = [
        metaText(salaryRange || cleanCompensation, 34),
        metaText(job.location, 40),
      ].filter(Boolean).join('<span class="dot"></span>');

      const card = document.createElement('article');
      card.className = `job-card${fav ? ' fav' : ''}`;
      card.dataset.key = key;

      card.innerHTML = `
        <button class="hide-btn js-hide" title="Not interested" aria-label="Hide">✕</button>
        <div class="job-main">
          <div class="job-top">
            <div class="job-title-wrap">
              ${job.job_url
                ? `<a class="job-title js-visit" href="${esc(job.job_url)}" target="_blank" rel="noopener">${esc(job.title ?? '—')}<span class="ext" aria-hidden="true">↗</span></a>${vis ? '<span class="visited-flag">Viewed</span>' : ''}`
                : `<span class="job-title">${esc(job.title ?? '—')}</span>`}
              <div class="job-meta-row">
                ${jdMeta ? `${jdMeta}<span class="dot"></span>` : ''}
                <span class="mode-pill" data-mode="${esc(mode)}"><span class="swatch"></span>${esc(mode)}</span>
                <span class="dot"></span>
                <span class="ats-pill">${esc(job.provider || '—')}</span>
                <span class="dot"></span>
                ${ageBadgeHtml(job.posted_at || job.first_seen_at)}
              </div>
            </div>
          </div>

          ${hasAnal ? `
          <div class="job-content">
            <div class="jc-block">
              <div class="jc-label">Summary</div>
              <p class="jc-text">${esc(anal.role_summary?.tldr || anal.standout_differentiator || '—')}</p>
            </div>
            <div class="jc-block">
              <div class="jc-label">Verdict</div>
              <p class="jc-text">${esc(recLabel(anal.application_recommendation))}</p>
            </div>
            <div class="jc-block">
              <div class="jc-label">Gaps</div>
              <p class="jc-text">${Array.isArray(anal.gaps) && anal.gaps.length ? esc(anal.gaps.map(g => g.gap || g).join(', ')) : '—'}</p>
            </div>
          </div>
          ` : ''}

          <div class="job-footer"></div>
        </div>

        <aside class="job-rail">
          <div class="company-row">
            ${compNameHtml}
            <button class="fav-btn js-fav ${fav ? 'active' : ''}" title="${fav ? 'Remove from favorites' : 'Add to favorites'}" aria-pressed="${fav}">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="${fav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17.3 6.2 20.5l1.1-6.5L2.6 9.5l6.5-.9L12 2.7l2.9 5.9 6.5.9-4.7 4.5 1.1 6.5z"/></svg>
            </button>
          </div>
        </aside>
      `;

      /* footer */
      const footerEl = card.querySelector('.job-footer');
      footerEl.innerHTML = footerHtml(job);
      bindFooterEvents(footerEl, job);

      /* events */
      card.querySelectorAll('.js-visit').forEach(el => {
        el.addEventListener('click', () => {
          markVisited(key);
          card.querySelector('.visited-flag') || el.insertAdjacentHTML('afterend', '<span class="visited-flag">Viewed</span>');
        });
      });
      card.querySelectorAll('.js-fav').forEach(el => {
        el.addEventListener('click', () => {
          toggleFav(comp);
          saveFaveMap();
          renderFavChips();
          renderCurrentView();
        });
      });
      card.querySelectorAll('.company-logo-frame img').forEach(img => {
        img.addEventListener('error', e => {
          const frame = e.target.closest('.company-logo-frame');
          if (frame) { frame.textContent = frame.dataset.fallback || '?'; }
        });
      });

      list.appendChild(card);
    }
    reapplySpinners();
  }

  /* ── Hide / undo ─────────────────────────────────────────────── */
  function hideJob(key, job) {
    hiddenJobs.add(key);
    saveSet(HIDDEN_KEY, hiddenJobs);
    syncHiddenJobs();
    lastHidden = { key, job };
    renderCurrentView();
    const nid = pushNotif('neutral', `Hidden "${job.title ?? ''}"`, null, true, 5000);
    lastHidden._notifId = nid;
  }
  function undoHide() {
    if (!lastHidden) return;
    hiddenJobs.delete(lastHidden.key);
    saveSet(HIDDEN_KEY, hiddenJobs);
    syncHiddenJobs();
    if (lastHidden._notifId) dismissNotif(lastHidden._notifId);
    lastHidden = null;
    renderCurrentView();
  }

  /* ── Notification stack ──────────────────────────────────────── */
  // pushNotif(kind, title, body, withUndo, autoDismissMs, actions, options) -> notifId
  // kind: 'neutral' | 'success' | 'error'
  // actions: optional array of { label, className?, onClick?, autoDismiss?:boolean }
  function pushNotif(kind, title, body, withUndo, autoDismissMs, actions, options) {
    const id = ++notifSeq;
    const stack = document.getElementById('notif-stack');

    const el = document.createElement('div');
    el.className = `notif notif-${kind}`;
    el.dataset.nid = id;

    const textWrap = document.createElement('div');
    textWrap.className = 'notif-text';

    const titleEl = document.createElement('div');
    titleEl.className = 'notif-title';
    titleEl.textContent = title;
    textWrap.appendChild(titleEl);

    if (body) {
      const bodyEl = document.createElement('div');
      bodyEl.className = 'notif-body';
      bodyEl.textContent = body;
      textWrap.appendChild(bodyEl);
    }

    const actionsEl = document.createElement('div');
    actionsEl.className = 'notif-actions';

    if (withUndo) {
      const undoBtn = document.createElement('button');
      undoBtn.className = 'notif-undo';
      undoBtn.textContent = 'Undo';
      undoBtn.addEventListener('click', () => { undoHide(); });
      actionsEl.appendChild(undoBtn);
    }

    if (!options?.hideClose) {
      const closeBtn = document.createElement('button');
      closeBtn.className = 'notif-close';
      closeBtn.innerHTML = '✕';
      closeBtn.addEventListener('click', () => dismissNotif(id));
      actionsEl.appendChild(closeBtn);
    }

    el.appendChild(textWrap);
    el.appendChild(actionsEl);
    stack.appendChild(el);

    // Trigger enter animation
    requestAnimationFrame(() => el.classList.add('notif-visible'));

    if (autoDismissMs) {
      setTimeout(() => dismissNotif(id), autoDismissMs);
    }

    // attach custom action buttons (6th arg)
    if (Array.isArray(actions) && actions.length) {
      const close = el.querySelector('.notif-close');
      for (const act of actions) {
        const b = document.createElement('button');
        b.className = act.className ? act.className : 'notif-action';
        b.textContent = act.label || 'Action';
        b.addEventListener('click', () => {
          try { if (typeof act.onClick === 'function') act.onClick(); } catch (e) { /* swallow */ }
          if (act.autoDismiss !== false) dismissNotif(id);
        });
        if (close) actionsEl.insertBefore(b, close);
        else actionsEl.appendChild(b);
      }
    }

    return id;
  }

  function dismissNotif(id) {
    const el = document.querySelector(`#notif-stack .notif[data-nid="${id}"]`);
    if (!el) return;
    el.classList.remove('notif-visible');
    el.classList.add('notif-exit');
    setTimeout(() => el.remove(), 300);
  }

  /* ── Analysis side panel ─────────────────────────────────────── */
  function scoreTier(s) { return s >= 4 ? 'high' : s >= 3 ? 'mid' : 'low'; }

  function renderPanelBody(job, activeTag) {
    const pipelines = job.pipelines || {};
    const pipelineTags = Object.keys(pipelines);

    // Resolve which tag to show: prefer given tag, else first available, else fall back to job.analysis
    let tag = activeTag;
    if (!tag || !pipelines[tag]) {
      tag = pipelineTags[0] || null;
    }

    const analysis = tag ? (pipelines[tag]?.analysis || null) : (job.analysis || null);
    if (!analysis) return;

    // Update stored active tag
    if (panelJobData) panelJobData.activeTag = tag;

    const score = Number(analysis.score_5 || 0);
    const tier  = scoreTier(score);
    const tierLabel = tier === 'high' ? 'Strong fit' : tier === 'mid' ? 'Partial fit' : 'Weak fit';
    const pct   = Math.round((score / 5) * 100);
    const pipeline = tag || analysis.pipeline || 'claude';

    const strengths = Array.isArray(analysis.requirement_match)
      ? analysis.requirement_match.slice(0, 4).map(m => `${m.requirement || '—'}: ${m.profile_evidence || '—'}`)
      : [];
    const rawGaps = Array.isArray(analysis.gaps) ? analysis.gaps.slice(0, 4) : [];
    const gaps = rawGaps.map(g => (typeof g === 'string' ? { gap: g, severity: null, mitigation: '' } : g));
    const blockers = Array.isArray(analysis.blockers) ? analysis.blockers : [];

    const SCORECARD_LABELS = {
      core_skills:           'Core skills',
      relevant_experience:   'Relevant exp.',
      target_alignment:      'Target align.',
      seniority_fit:         'Seniority fit',
      workplace_fit:         'Workplace fit',
      requirements_coverage: 'Req. coverage',
    };
    const scorecard = analysis.scorecard || null;

    const REC_TIER = {
      apply_now:        'high',
      worth_applying:   'mid',
      only_if_strategic:'low',
      do_not_apply:     'low',
    };
    const rec    = analysis.application_recommendation || null;
    const recTier = REC_TIER[rec] || 'mid';

    const toolMatch = Array.isArray(analysis.tool_match) ? analysis.tool_match : [];
    const standout  = analysis.standout_differentiator || analysis.remarques || null;

    // Pipeline tabs (only if multiple pipelines)
    const tabsHtml = pipelineTags.length > 1 ? `
      <div class="pipeline-tabs">
        ${pipelineTags.map(t => {
          const p = PIPELINES[t] || { color: '#6b7280', label: t };
          const isActive = t === tag;
          return `<button class="pipeline-tab${isActive ? ' active' : ''}" data-tab-pipeline="${esc(t)}" style="${isActive ? `border-color:${p.color};color:${p.color};background:${p.color}11;` : ''}">${esc(p.label || t)}</button>`;
        }).join('')}
      </div>` : '';

    const toolMatchHtml = toolMatch.length ? `
      <section class="panel-section">
        <div class="panel-section-label">Tool match</div>
        <div class="tool-chips">
          ${toolMatch.map(t => {
            const str = t.strength || 'partial';
            const imp = t.importance || '';
            const title = [t.profile_evidence, imp ? `importance: ${imp}` : ''].filter(Boolean).join(' · ');
            return `<span class="tool-chip" data-strength="${esc(str)}" title="${esc(title)}">${esc(t.tool || '?')}</span>`;
          }).join('')}
        </div>
      </section>` : '';

    const standoutHtml = standout ? `
      <section class="panel-section">
        <div class="panel-section-label">Standout</div>
        <blockquote class="standout-callout">${esc(standout)}</blockquote>
      </section>` : '';

    const scorecardHtml = scorecard ? `
      <section class="panel-section">
        <div class="panel-section-label">Scorecard</div>
        <div class="scorecard-rows">
          ${Object.entries(SCORECARD_LABELS).map(([key, label]) => {
            const dim = scorecard[key];
            if (!dim) return '';
            const s = Number(dim.score || 0);
            const pctDim = Math.round((s / 5) * 100);
            const dimTier = s >= 4 ? 'high' : s >= 3 ? 'mid' : 'low';
            const reason = dim.reason ? esc(dim.reason) : '';
            return `<div class="sc-row" ${reason ? `title="${reason}"` : ''}>
              <span class="sc-label">${esc(label)}</span>
              <div class="sc-bar-wrap">
                <div class="sc-bar-fill" data-tier="${dimTier}" style="width:${pctDim}%"></div>
              </div>
              <span class="sc-score mono" data-tier="${dimTier}">${s.toFixed(1)}</span>
            </div>`;
          }).join('')}
        </div>
      </section>` : '';

    const allGapsEnhanced = [
      ...gaps.map(g => ({ text: g.gap, severity: g.severity || null, mitigation: g.mitigation || '', blocker: false })),
      ...blockers.map(b => ({ text: typeof b === 'string' ? b : (b.gap || String(b)), severity: 'blocker', mitigation: '', blocker: true })),
    ];
    const gapsEnhancedHtml = allGapsEnhanced.length ? `
      <section class="panel-section">
        <div class="panel-section-label">Gaps &amp; Blockers <span class="section-info" title="Dash color: red = blocker (hard stop), orange = medium gap, grey = minor gap. Italic text = suggested mitigation.">ⓘ</span></div>
        <ul class="bullet-list gap-list">
          ${allGapsEnhanced.map(g => {
            const sevAttr = g.severity ? ` data-severity="${esc(g.severity)}"` : '';
            const mit = g.mitigation ? `<span class="gap-mitigation">${esc(g.mitigation)}</span>` : '';
            return `<li${sevAttr}><span class="gap-content">${esc(g.text)}${mit}</span></li>`;
          }).join('')}
        </ul>
      </section>` : '';

    document.getElementById('panel-body').innerHTML = `
      ${tabsHtml}
      <section class="score-block">
        <div class="score-readout">
          <span class="score-num mono">${score.toFixed(1)}</span>
          <span class="score-max mono">/ 5.0</span>
          <span class="score-tag" data-tier="${esc(tier)}">${esc(tierLabel)}</span>
          ${rec ? `<span class="verdict-badge" data-tier="${esc(recTier)}">${esc(recLabel(rec))}</span>` : ''}
        </div>
        <div class="score-bar"><div class="score-bar-fill" data-tier="${esc(tier)}" style="width:${pct}%"></div></div>
      </section>
      <div class="panel-actions">
        <div class="panel-rerun-wrap">
          <button class="btn btn-ghost" id="panel-reanalyze" data-mode="${esc(pipeline)}">Re-run · ${esc(PIPELINES[pipeline]?.label || pipeline)}</button>
          <button class="panel-rerun-caret" id="panel-rerun-caret" title="Choose pipeline">▾</button>
          <div class="panel-rerun-menu" id="panel-rerun-menu">
            ${Object.entries(PIPELINES).map(([m, p]) => `
              <button data-rerun-mode="${m}">
                <span class="menu-swatch ${p.swatchClass}"></span>
                <span>${esc(p.label)}</span>
                <span style="margin-left:auto;opacity:0.5;font-size:10px;">${esc(p.dur)}</span>
              </button>`).join('')}
          </div>
        </div>
        ${job.job_url ? `<a href="${esc(job.job_url)}" target="_blank" rel="noopener" class="btn btn-primary">Apply ↗</a>` : ''}
      </div>
      <div class="panel-col">
        ${analysis.role_summary?.tldr ? `
        <section class="panel-section">
          <div class="panel-section-label">Role TL;DR</div>
          <p style="font-size:13px;line-height:1.55;color:var(--ink-2);margin:0;">${esc(analysis.role_summary.tldr)}</p>
        </section>` : ''}
        ${scorecardHtml}
        ${toolMatchHtml}
        ${gapsEnhancedHtml}
        ${standoutHtml}
      </div>
    `;

    document.getElementById('panel-footer').innerHTML = '';

    // Tab switching
    document.getElementById('panel-body').querySelectorAll('[data-tab-pipeline]').forEach(btn => {
      btn.addEventListener('click', () => {
        const t = btn.dataset.tabPipeline;
        renderPanelBody(job, t);
      });
    });

    // Re-run main button uses same pipeline as the current analysis
    document.getElementById('panel-reanalyze')?.addEventListener('click', () => {
      closePanel();
      analyzeJob(job, null, pipeline);
    });

    // Caret toggles dropdown
    const caretBtn = document.getElementById('panel-rerun-caret');
    const menu     = document.getElementById('panel-rerun-menu');
    caretBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      menu?.classList.toggle('open');
    });
    // Close on outside click
    document.addEventListener('click', () => menu?.classList.remove('open'), { once: true });

    // Dropdown items
    menu?.querySelectorAll('[data-rerun-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        const m = btn.dataset.rerunMode;
        menu.classList.remove('open');
        closePanel();
        analyzeJob(job, null, m);
      });
    });
  }

  function openPanel(job, pipelineTagOrAnalysis) {
    // Accept either a pipeline tag string or legacy analysis object
    let tag = null;
    if (typeof pipelineTagOrAnalysis === 'string') {
      tag = pipelineTagOrAnalysis;
    } else if (pipelineTagOrAnalysis && typeof pipelineTagOrAnalysis === 'object') {
      // Legacy: received analysis object directly — infer tag from pipeline field
      tag = pipelineTagOrAnalysis.pipeline || null;
    }

    // Ensure there's something to show
    const pipelines = job.pipelines || {};
    const hasPipelines = Object.keys(pipelines).length > 0;
    const hasLegacyAnalysis = job.analysis && Number(job.analysis.score_5 || 0) > 0;
    if (!hasPipelines && !hasLegacyAnalysis) return;

    panelJobData = { job, activeTag: tag };

    const pComp = companyName(job);
    const pLogoUrl = logoUrl(pComp);
    const pLogoHtml = pLogoUrl
      ? `<span style="width:16px;height:16px;border-radius:4px;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;background:#f4f4f4;border:1px solid #e3e3e3;flex-shrink:0;"><img src="${esc(pLogoUrl)}" alt="" width="16" height="16" style="object-fit:contain;display:block;" referrerpolicy="no-referrer"></span>`
      : `<span style="width:16px;height:16px;border-radius:4px;background:#f4f4f4;border:1px solid #e3e3e3;display:inline-flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:#5b5b5b;flex-shrink:0;">${esc((pComp.charAt(0) || '?').toUpperCase())}</span>`;

    const titleEl = document.getElementById('panel-title');
    if (job.job_url) {
      titleEl.innerHTML = `<a href="${esc(job.job_url)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline;text-underline-offset:3px;">${esc(job.title ?? '—')} <span style="font-size:13px;opacity:0.5;">↗</span></a>`;
    } else {
      titleEl.textContent = job.title ?? '—';
    }
    document.getElementById('panel-company').innerHTML = `<span style="display:inline-flex;align-items:center;gap:6px;">${pLogoHtml}<span>${esc(pComp)} · ${esc(job.location || '—')}</span></span>`;

    // Role meta pills — sourced from the first available analysis's role_summary
    const firstAnalysis = (() => {
      const pls = job.pipelines || {};
      const firstTag = Object.keys(pls)[0];
      return firstTag ? (pls[firstTag]?.analysis || null) : (job.analysis || null);
    })();
    const rs = firstAnalysis?.role_summary || {};
    const pillValues = [rs.domain, rs.seniority, rs.remote_policy].filter(Boolean);
    document.getElementById('panel-pills').innerHTML = pillValues.length
      ? pillValues.map(v => `<span class="panel-pill">${esc(v)}</span>`).join('')
      : '';

    renderPanelBody(job, tag);

    document.getElementById('panel-overlay').classList.add('open');
    document.getElementById('side-panel').classList.add('open');
  }

  function closePanel() {
    document.getElementById('panel-overlay').classList.remove('open');
    document.getElementById('side-panel').classList.remove('open');
  }

  /* ── Analyze ─────────────────────────────────────────────────── */
  const MODE_BTN_CLASS = {
    'claude':          'js-analyze-claude',
    'claude-ensemble': 'js-analyze-claude-ens',
  };

  // activeAnalysisJobs is keyed by `jobKey|mode` to support concurrent pipelines per job
  function activeJobRunKey(job, mode) { return `${jobKey(job)}|${mode ?? 'claude'}`; }
  function jobHasActiveRuns(job) {
    const prefix = jobKey(job) + '|';
    for (const k of activeAnalysisJobs.keys()) { if (k.startsWith(prefix)) return true; }
    return false;
  }

  function setMainBtnSpinner(job, label, mode, source = 'manual') {
    activeAnalysisJobs.set(activeJobRunKey(job, mode), { label, mode: mode ?? 'claude', source });
    const card = document.querySelector(`.job-card[data-key="${CSS.escape(jobKey(job))}"]`);
    if (!card) return;
    card.querySelectorAll('.btn-analyze').forEach(b => { b.disabled = true; });
    const jsClass = MODE_BTN_CLASS[mode] || 'js-analyze-quick';
    const activeBtn = card.querySelector(`.${jsClass}`);
    if (activeBtn) activeBtn.innerHTML = `<span class="btn-spinner"></span> ${label}`;
  }

  function restoreMainBtn(job, mode) {
    const jkey = jobKey(job);
    activeAnalysisJobs.delete(activeJobRunKey(job, mode));
    // Only re-render footer when no more active runs for this job
    if (jobHasActiveRuns(job)) {
      // Still running other pipelines — just re-enable the button that just finished
      const card = document.querySelector(`.job-card[data-key="${CSS.escape(jkey)}"]`);
      if (!card) return;
      const jsClass = MODE_BTN_CLASS[mode] || 'js-analyze-quick';
      const btn = card.querySelector(`.${jsClass}`);
      if (btn) { btn.disabled = false; btn.innerHTML = `<span class="btn-spark ${PIPELINES[mode]?.spark || ''}">✦</span> ${PIPELINES[mode]?.label || mode} analyze`; }
      return;
    }
    const footer = document.querySelector(`.job-card[data-key="${CSS.escape(jkey)}"] .job-footer`);
    if (!footer) return;
    footer.innerHTML = footerHtml(job);
    bindFooterEvents(footer, job);
  }

  function reapplySpinners() {
    for (const [runKey, { label, mode }] of activeAnalysisJobs) {
      const jkey = runKey.split('|').slice(0, 3).join('|'); // provider|source_key|job_id
      const card = document.querySelector(`.job-card[data-key="${CSS.escape(jkey)}"]`);
      if (!card) continue;
      card.querySelectorAll('.btn-analyze').forEach(b => { b.disabled = true; });
      const jsClass = MODE_BTN_CLASS[mode] || 'js-analyze-quick';
      const activeBtn = card.querySelector(`.${jsClass}`);
      if (activeBtn) activeBtn.innerHTML = `<span class="btn-spinner"></span> ${label}`;
    }
  }

  function modeLabel(mode) {
    return PIPELINES[mode]?.label || mode;
  }
  function modeDuration(mode) {
    return PIPELINES[mode]?.dur || '~25 sec';
  }

  function renderAutoAnalyzerToast(status) {
    const enabled = Boolean(status?.enabled);
    if (!enabled) return;

    const paused = Boolean(status?.paused);
    const current = status?.current;
    const isRunning = Boolean(current);
    const title = paused
      ? 'Auto analyze fit paused'
      : isRunning
        ? 'Auto analyze fit is running'
        : 'Auto analyze fit is watching saved searches';
    const body = isRunning
      ? `${current.job?.title || 'Job'} · ${current.job?.company || ''}`
      : paused
        ? 'Saved-search full analysis is stopped.'
        : 'Waiting for the next unanalyzed saved-search match.';
    const sig = JSON.stringify([title, body, paused]);
    if (autoAnalyzerNotifId && autoAnalyzerToastSig === sig) return;

    if (autoAnalyzerNotifId) dismissNotif(autoAnalyzerNotifId);
    autoAnalyzerNotifId = pushNotif(
      'neutral',
      title,
      body,
      false,
      null,
      [
        {
          label: paused ? 'Resume auto analyze' : 'Stop auto analyze',
          className: paused ? 'btn btn-success btn-sm' : 'btn btn-danger btn-sm',
          autoDismiss: false,
          onClick: async () => {
            try {
              await fetch('/api/auto-analyzer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ paused: !paused })
              });
            } catch {}
            updateAutoAnalyzerStatus();
          }
        }
      ],
      { hideClose: true }
    );
    autoAnalyzerToastSig = sig;
  }

  async function updateAutoAnalyzerStatus() {
    const res = await fetch('/api/auto-analyzer');
    const status = await res.json();
    if (!res.ok || !status.enabled) return;

    renderAutoAnalyzerToast(status);
    const currentKey = status.current?.jobKey || null;
    const isActive = Boolean(currentKey);

    if (currentKey) {
      autoAnalyzerLastJobKey = currentKey;
      const job = allJobs.find(j => jobKey(j) === currentKey);
      if (job) setMainBtnSpinner(job, 'Analyzing…', 'claude-ensemble', 'auto');
    } else if (autoAnalyzerLastJobKey) {
      const runKey = autoAnalyzerLastJobKey + '|claude-ensemble';
      const state = activeAnalysisJobs.get(runKey);
      if (state?.source === 'auto') {
        activeAnalysisJobs.delete(runKey);
        if (autoAnalyzerLastActive) fetchJobs(currentPage);
        else renderCurrentView();
      }
      autoAnalyzerLastJobKey = null;
    }

    autoAnalyzerLastActive = isActive;
  }

  async function pollAutoAnalyzer() {
    try {
      await updateAutoAnalyzerStatus();
    } catch {
      // Keep the page usable if the status endpoint is temporarily unavailable.
    } finally {
      setTimeout(pollAutoAnalyzer, 5000);
    }
  }

  /* ── Crawl status indicator ─────────────────────────────────── */
  function formatElapsed(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return s > 0 ? `${m}m ${s}s` : `${m}m`;
  }

  function formatNextRun(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    const now = new Date();
    const diffMs = d - now;
    if (diffMs <= 0) return 'soon';
    const diffMin = Math.round(diffMs / 60000);
    if (diffMin < 60) return `in ${diffMin}m`;
    const h = Math.floor(diffMin / 60);
    const m = diffMin % 60;
    return m > 0 ? `in ${h}h ${m}m` : `in ${h}h`;
  }

  async function updateCrawlStatus() {
    const indicator = document.getElementById('crawl-indicator');
    const popover   = document.getElementById('crawl-popover');
    const fill      = document.getElementById('crawl-bar-fill');
    const pctEl     = document.getElementById('crawl-bar-pct');
    if (!indicator || !popover || !fill || !pctEl) return;

    const res = await fetch('/api/crawl-status');
    if (!res.ok) return;
    const data = await res.json();

    if (!data.active) {
      indicator.classList.remove('active');
      if (data.total_jobs) {
        fill.style.width = '100%';
        pctEl.textContent = '100%';
      }
      const nextLabel = data.next_run ? `Next crawl ${formatNextRun(data.next_run)}` : '';
      popover.textContent = nextLabel;
      indicator.dataset.nextRun = nextLabel;
      return;
    }

    indicator.classList.add('active');
    delete indicator.dataset.nextRun;

    const p         = data.progress;
    const percent   = p ? (p.percent ?? 0) : 0;
    const totalJobs = p ? (p.total_jobs ?? 0) : 0;
    const elapsed   = p ? (p.elapsed_seconds ?? 0) : 0;

    fill.style.width  = `${percent}%`;
    pctEl.textContent = `${percent}%`;

    popover.innerHTML =
      `<strong>${totalJobs.toLocaleString()} jobs</strong> · ${formatElapsed(elapsed)}`;
  }

  async function pollCrawlStatus() {
    try {
      await updateCrawlStatus();
    } catch {
      // non-fatal
    } finally {
      setTimeout(pollCrawlStatus, 3000);
    }
  }

  async function analyzeJob(job, _triggerEl, mode) {
    const spinnerLabel = mode === 'claude-ensemble' ? 'Analyzing pipeline…' : 'Analyzing…';
    setMainBtnSpinner(job, spinnerLabel, mode);
    const comp = companyName(job);
    const notifId = pushNotif(
      'neutral',
      `${job.title ?? 'Job'} · ${comp}`,
      `${modeLabel(mode)} · Est. ${modeDuration(mode)}`,
      false,
      5000
    );
    const payload = { job_keys: [{ provider: job.provider, source_key: job.source_key, job_id: job.job_id }], ...(mode ? { mode } : {}) };
    try {
      const res  = await fetch('/api/match-runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      activeRuns.set(data.run_id, { job, mode, startedAt: Date.now(), notifId });
      scheduleRunPoll(data.run_id);
    } catch (e) {
      activeAnalysisJobs.delete(activeJobRunKey(job, mode));
      restoreMainBtn(job, mode);
      dismissNotif(notifId);
      pushNotif('error', `Failed · ${job.title ?? 'Job'} · ${comp}`, e.message || 'Analysis failed', false, null);
    }
  }

  function scheduleRunPoll(runId) {
    setTimeout(() => pollRun(runId), 2000);
  }

  async function pollRun(runId) {
    const ctx = activeRuns.get(runId);
    if (!ctx) return;
    const { job, mode, startedAt, notifId } = ctx;
    try {
      const res = await fetch(`/api/match-runs/${encodeURIComponent(runId)}`);
      const run = await res.json();
      if (!res.ok) throw new Error(run.error || 'Failed');

      // Orphaned run: server restarted and lost in-memory state — treat as completed
      if (run.status === 'running' && run.is_active === false) run.status = 'completed';

      if (run.status === 'completed' || run.status === 'failed') {
        activeRuns.delete(runId);
        activeAnalysisJobs.delete(activeJobRunKey(job, mode));
        dismissNotif(notifId);

        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        const durStr  = elapsed >= 60 ? `${Math.floor(elapsed / 60)}m ${elapsed % 60}s` : `${elapsed}s`;
        const comp    = companyName(job);

        if (run.status === 'failed') {
          restoreMainBtn(job, mode);
          pushNotif('error', `Failed · ${job.title ?? 'Job'} · ${comp}`, `${modeLabel(mode)} · ${durStr}`, false, null);
          return;
        }

        // Fetch the updated job and patch the card
        const params = new URLSearchParams({ provider: job.provider, source_key: job.source_key, job_id: job.job_id });
        const jobRes = await fetch(`/api/job?${params}`);
        if (!jobRes.ok) { restoreMainBtn(job, mode); return; }

        const updatedJob = await jobRes.json();
        const idx = allJobs.findIndex(j => jobKey(j) === jobKey(job));
        if (idx !== -1) allJobs[idx] = updatedJob;

        const card = document.querySelector(`.job-card[data-key="${CSS.escape(jobKey(job))}"]`);
        if (card) {
          const score   = Number(updatedJob.analysis?.score_5 || 0);
          const hasAnal = updatedJob.analysis && score > 0;
          const footer  = card.querySelector('.job-footer');
          if (footer) {
            footer.innerHTML = footerHtml(updatedJob);
            bindFooterEvents(footer, updatedJob);
            // Re-apply spinners for any pipelines still running on this job
            reapplySpinners();
          }

          // If panel is open for this job, refresh it with the new pipeline data
          if (panelJobData && jobKey(panelJobData.job) === jobKey(updatedJob)) {
            const openTag = panelJobData.activeTag;
            panelJobData.job = updatedJob;
            openPanel(updatedJob, openTag || mode);
          }

          // Update content blocks too
          const anal    = updatedJob.analysis;
          const updScore   = Number(anal?.score_5 || 0);
          const updHasAnal = anal && updScore > 0;
          const jobMain = card.querySelector('.job-main');
          const existingContent = card.querySelector('.job-content');
          if (updHasAnal && jobMain) {
            const newContent = document.createElement('div');
            newContent.className = 'job-content';
            newContent.innerHTML = `
              <div class="jc-block">
                <div class="jc-label">Summary</div>
                <p class="jc-text">${esc(anal.role_summary?.tldr || anal.standout_differentiator || '—')}</p>
              </div>
              <div class="jc-block">
                <div class="jc-label">Verdict</div>
                <p class="jc-text">${esc(recLabel(anal.application_recommendation))}</p>
              </div>
              <div class="jc-block">
                <div class="jc-label">Gaps</div>
                <p class="jc-text">${Array.isArray(anal.gaps) && anal.gaps.length ? esc(anal.gaps.map(g => g.gap || g).join(', ')) : '—'}</p>
              </div>`;
            if (existingContent) existingContent.replaceWith(newContent);
            else jobMain.querySelector('.job-footer')?.before(newContent);
          }
        }

        pushNotif(
          'success',
          `Done · ${updatedJob.title ?? 'Job'} · ${comp}`,
          `${modeLabel(mode)} · ${durStr}${updatedJob.analysis?.score_5 ? ` · Score ${Number(updatedJob.analysis.score_5).toFixed(1)}/5` : ''}`,
          false,
          null,
          // actions: show an Open button to open the side panel on demand
          (updatedJob.pipelines && Object.keys(updatedJob.pipelines).length > 0) || updatedJob.analysis ? [
            {
              label: 'Open panel',
              className: 'btn btn-primary btn-sm',
              onClick: () => openPanel(updatedJob, mode)
            }
          ] : []
        );
        return;
      }

      scheduleRunPoll(runId);
    } catch {
      activeRuns.delete(runId);
      activeAnalysisJobs.delete(activeJobRunKey(job, mode));
      dismissNotif(notifId);
      restoreMainBtn(job, mode);
      pushNotif('error', `Failed · ${job.title ?? 'Job'} · ${companyName(job)}`, `${modeLabel(mode)} · network error`, false, null);
    }
  }

  /* ── Providers dropdown ──────────────────────────────────────── */
  const providerBtn  = document.getElementById('provider-btn');
  const providerMenu = document.getElementById('provider-menu');

  providerBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    providerMenu.classList.toggle('open');
  });
  document.addEventListener('click', () => providerMenu.classList.remove('open'));
  providerMenu.addEventListener('click', e => e.stopPropagation());
  providerMenu.addEventListener('change', () => { syncProviderLabel(); onFilterChange(); });

  function getSelectedProviders() {
    return [...providerMenu.querySelectorAll('input[type="checkbox"]:checked')].map(i => i.value);
  }
  function syncProviderLabel() {
    const sel = getSelectedProviders();
    providerBtn.childNodes[0].textContent = sel.length === 0 ? 'All providers' : sel.length <= 2 ? sel.join(', ') : `${sel.length} providers`;
  }
  function setSelectedProviders(values) {
    const wanted = new Set(values || []);
    providerMenu.querySelectorAll('input[type="checkbox"]').forEach(i => { i.checked = wanted.has(i.value); });
    syncProviderLabel();
  }

  /* ── Favorites ───────────────────────────────────────────────── */
  function renderFavChips() {
    const entries = [...favoriteCompanies.entries()].map(([k, l]) => ({ key: k, label: l })).sort((a, b) => a.label.localeCompare(b.label));
    const wrap    = document.getElementById('fav-chips-wrap');
    const chips   = document.getElementById('fav-chips');
    chips.innerHTML = '';
    wrap.style.display = entries.length > 0 ? 'block' : 'none';
    for (const { key, label } of entries) {
      const chip = document.createElement('span');
      chip.className = 'fav-chip';
      chip.innerHTML = `<span>${esc(label)}</span><button class="fav-chip-remove" aria-label="Remove ${esc(label)}">×</button>`;
      chip.querySelector('.fav-chip-remove').addEventListener('click', () => {
        removeFav(key);
        renderFavChips();
        renderCurrentView();
      });
      chips.appendChild(chip);
    }
  }

  document.getElementById('open-fav-modal').addEventListener('click', () => {
    renderFavChips();
    document.getElementById('fav-modal').style.display = 'flex';
  });
  document.getElementById('close-fav-modal').addEventListener('click', () => {
    document.getElementById('fav-modal').style.display = 'none';
  });
  document.getElementById('fav-modal').addEventListener('click', e => {
    if (e.target === e.currentTarget) e.currentTarget.style.display = 'none';
  });
  document.getElementById('fav-add-btn').addEventListener('click', () => {
    const input = document.getElementById('fav-input');
    if (addFav(input.value)) { input.value = ''; renderFavChips(); renderCurrentView(); }
  });
  document.getElementById('fav-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('fav-add-btn').click();
  });

  /* ── Saved searches ──────────────────────────────────────────── */
  let savedSearches = [];
  const activeSearchIds = new Set();

  /* ── URL state persistence ───────────────────────────────────── */
  function pushUrlState(page) {
    const p = new URLSearchParams();
    const title   = document.getElementById('filter-title').value.trim();
    const loc     = document.getElementById('filter-location').value.trim();
    const company = document.getElementById('filter-company').value.trim();
    const days    = document.getElementById('filter-days').value.trim();
    const sources = getSelectedProviders();
    if (title)                    p.set('title', title);
    if (loc)                      p.set('loc', loc);
    if (company)                  p.set('company', company);
    if (days)                     p.set('days', days);
    if (sources.length)           p.set('sources', sources.join(','));
    if (activeSearchIds.size > 0) p.set('searches', [...activeSearchIds].join(','));
    if (page && page > 1)         p.set('page', String(page));
    const qs = p.toString();
    history.replaceState(null, '', qs ? `?${qs}` : location.pathname);
  }

  function restoreFromUrl() {
    const p = new URLSearchParams(location.search);
    if (p.has('title'))    document.getElementById('filter-title').value    = p.get('title');
    if (p.has('loc'))      document.getElementById('filter-location').value = p.get('loc');
    if (p.has('company'))  document.getElementById('filter-company').value  = p.get('company');
    if (p.has('days'))     document.getElementById('filter-days').value     = p.get('days');
    // sources: deferred to loadSources() since checkboxes don't exist yet at boot
    activeSearchIds.clear();
    if (p.has('searches')) p.get('searches').split(',').filter(Boolean).forEach(id => activeSearchIds.add(Number(id)));
    return p.has('page') ? parseInt(p.get('page'), 10) || 1 : 1;
  }

  function applySearchLock(locked) {
    ['filter-title','filter-location','filter-company','filter-days'].forEach(id => {
      document.getElementById(id).disabled = locked;
    });
    document.querySelector('.provider-btn')?.toggleAttribute('disabled', locked);
  }

  async function loadSavedSearches() {
    const strip = document.getElementById('saved-searches-strip');
    try {
      const res = await fetch('/saved-searches.json');
      if (res.ok) savedSearches = await res.json();
    } catch {}
    for (const s of savedSearches) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'saved-btn';
      btn.dataset.searchId = s.id;
      btn.textContent = s.label;
      btn.addEventListener('click', () => {
        if (activeSearchIds.has(s.id)) {
          activeSearchIds.delete(s.id);
          btn.classList.remove('active');
        } else {
          activeSearchIds.add(s.id);
          btn.classList.add('active');
        }
        const multi = activeSearchIds.size > 1;
        applySearchLock(multi);
        if (activeSearchIds.size === 0) {
          fetchJobs(1);
          return;
        }
        if (!multi) {
          // Single search — fill inputs as before
          const single = savedSearches.find(x => activeSearchIds.has(x.id));
          if (single) {
            document.getElementById('filter-title').value    = single.title    ?? '';
            document.getElementById('filter-location').value = single.location ?? '';
            document.getElementById('filter-company').value  = single.company  ?? '';
            document.getElementById('filter-days').value     = single.days     ?? '';
            setSelectedProviders(single.sources || []);
          }
        }
        fetchJobs(1);
      });
      if (activeSearchIds.has(s.id)) btn.classList.add('active');
      strip.appendChild(btn);
    }
    // Apply lock state from restored URL
    const multi = activeSearchIds.size > 1;
    applySearchLock(multi);
  }
  loadSavedSearches();

  /* ── Filters ─────────────────────────────────────────────────── */
  function onFilterChange() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (fetchJobsController) fetchJobsController.abort();
      fetchJobsController = new AbortController();
      fetchJobs(1, fetchJobsController.signal);
    }, 250);
  }
  ['filter-title','filter-location','filter-company','filter-days'].forEach(id => {
    document.getElementById(id).addEventListener('input', onFilterChange);
  });
  document.getElementById('fav-only-toggle').addEventListener('change', renderCurrentView);
  document.getElementById('evaluated-only-toggle').addEventListener('change', renderCurrentView);

  /* ── Render current view ─────────────────────────────────────── */
  function getRenderableJobs() {
    const favOnly       = document.getElementById('fav-only-toggle').checked;
    const evaluatedOnly = document.getElementById('evaluated-only-toggle').checked;
    return allJobs.filter(job => {
      if (favOnly && !isFav(companyName(job))) return false;
      if (evaluatedOnly && !(job.analysis && Number(job.analysis.score_5) > 0)) return false;
      if (hiddenJobs.has(jobKey(job))) return false;
      return true;
    });
  }

  function renderCurrentView() {
    const loading = document.getElementById('loading-state');
    const empty   = document.getElementById('empty-state');
    const list    = document.getElementById('jobs-list');
    if (loading.style.display !== 'none' && allJobs.length === 0) return;

    const jobs          = getRenderableJobs();
    const favOnly       = document.getElementById('fav-only-toggle').checked;
    const evaluatedOnly = document.getElementById('evaluated-only-toggle').checked;
    const countEl       = document.getElementById('result-count');
    countEl.textContent = evaluatedOnly
      ? `${jobs.length.toLocaleString()} evaluated job${jobs.length !== 1 ? 's' : ''}`
      : favOnly
        ? `${jobs.length.toLocaleString()} favorite job${jobs.length !== 1 ? 's' : ''}`
        : `${jobs.length.toLocaleString()} job${jobs.length !== 1 ? 's' : ''}`;

    if (jobs.length === 0) {
      list.style.display = 'none';
      empty.style.display = 'block';
      const msg = favOnly && favoriteCompanies.size === 0
        ? 'No favorite companies saved yet — add some to filter by favorites.'
        : 'No jobs match your filters.';
      document.getElementById('empty-msg').textContent = msg;
      return;
    }

    empty.style.display = 'none';
    renderJobs(jobs);
    list.style.display = 'flex';
  }

  /* ── Fetch jobs ──────────────────────────────────────────────── */
  function buildSearchParams(overrides = {}) {
    const p = new URLSearchParams();
    const title   = overrides.title   ?? document.getElementById('filter-title').value.trim();
    const loc     = overrides.loc     ?? document.getElementById('filter-location').value.trim();
    const company = overrides.company ?? document.getElementById('filter-company').value.trim();
    const days    = overrides.days    ?? document.getElementById('filter-days').value.trim();
    const sources = overrides.sources ?? getSelectedProviders();
    if (title)          p.set('title', title);
    if (loc)            p.set('location', loc);
    if (company)        p.set('company', company);
    if (days)           p.set('days', days);
    if (sources.length) p.set('sources', sources.join(','));
    return p;
  }

  async function fetchJobs(page = 1, signal = null) {
    document.getElementById('loading-state').style.display = 'block';
    document.getElementById('jobs-list').style.display     = 'none';
    document.getElementById('empty-state').style.display   = 'none';
    document.getElementById('pagination').style.display    = 'none';

    try {
      if (activeSearchIds.size > 0) {
        // Multi-search: fetch each selected search in parallel, dedupe by jobKey
        const active = savedSearches.filter(s => activeSearchIds.has(s.id));
        const responses = await Promise.all(active.map(s => {
          const p = buildSearchParams({
            title: s.title ?? '', loc: s.location ?? '',
            company: s.company ?? '', days: s.days ?? '',
            sources: s.sources || [],
          });
          p.set('page', '1');
          p.set('limit', '200');
          return fetch(`/api/jobs?${p}`, signal ? { signal } : {}).then(r => r.json());
        }));
        const seen = new Set();
        const merged = [];
        for (const data of responses) {
          for (const job of (data.jobs || [])) {
            const k = jobKey(job);
            if (!seen.has(k)) { seen.add(k); merged.push(job); }
          }
        }
        // Sort merged by posted_at desc
        merged.sort((a, b) => {
          const da = a.posted_at || a.first_seen_at || '';
          const db_ = b.posted_at || b.first_seen_at || '';
          return da < db_ ? 1 : da > db_ ? -1 : 0;
        });
        totalJobs   = merged.length;
        pageSize    = merged.length;
        currentPage = 1;
        allJobs     = merged;
      } else {
        const params = buildSearchParams();
        params.set('page', String(page));
        const res  = await fetch(`/api/jobs?${params}`, signal ? { signal } : {});
        const data = await res.json();
        totalJobs   = data.total;
        pageSize    = data.pageSize;
        currentPage = data.page;
        allJobs     = data.jobs;
        const totalPages = Math.ceil(totalJobs / pageSize);
        if (totalPages > 1) {
          document.getElementById('page-info').textContent = `Page ${currentPage} / ${totalPages}`;
          document.getElementById('btn-prev').disabled = currentPage <= 1;
          document.getElementById('btn-next').disabled = currentPage >= totalPages;
          document.getElementById('pagination').style.display = 'flex';
        }
      }
      document.getElementById('loading-state').style.display = 'none';
      pushUrlState(currentPage);
      renderCurrentView();
    } catch (err) {
      if (err?.name === 'AbortError') return;
      document.getElementById('loading-state').innerHTML = '<div style="color:var(--danger)">Error loading jobs.</div>';
    }
  }

  /* ── Fetch stats ─────────────────────────────────────────────── */
  async function fetchStats() {
    try {
      const res  = await fetch('/api/stats');
      const data = await res.json();
      const crawlDate = data.lastCrawl
        ? new Date(data.lastCrawl).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
        : 'unknown';
      document.getElementById('header-sub').textContent =
        `${data.total.toLocaleString()} roles across ${data.byProvider.length} ATS sources · last sync ${crawlDate}`;
      document.getElementById('header-meta').innerHTML =
        `<span><strong>${data.total.toLocaleString()}</strong> open</span>` +
        `<span><strong>${data.byProvider.length}</strong> sources</span>`;
    } catch {}
  }

  /* ── Fetch config ────────────────────────────────────────────── */
  async function fetchConfig() {
    try {
      const res  = await fetch('/api/config');
      const data = await res.json();
      logoDevPublishableKey = typeof data.logoDevPublishableKey === 'string' && data.logoDevPublishableKey.trim() ? data.logoDevPublishableKey.trim() : null;
      hasLogoDevBrandSearch = Boolean(data.hasLogoDevBrandSearch);
      matcherEnabled        = Boolean(data.matcherEnabled);
      renderCurrentView();
    } catch {}
  }

  /* ── Load sources ────────────────────────────────────────────── */
  async function loadSources() {
    try {
      const res  = await fetch('/api/sources');
      const data = await res.json();
      providerMenu.innerHTML = '';
      for (const src of data.sources) {
        const label = document.createElement('label');
        label.className = 'provider-item';
        label.innerHTML = `<input type="checkbox" value="${esc(src)}" /><span>${esc(src)}</span>`;
        providerMenu.appendChild(label);
      }
      // Re-apply sources that were restored from URL (checkboxes didn't exist yet)
      const urlSources = new URLSearchParams(location.search).get('sources');
      if (urlSources) setSelectedProviders(urlSources.split(',').filter(Boolean));
      syncProviderLabel();
    } catch {}
  }

  /* ── Pagination ──────────────────────────────────────────────── */
  document.getElementById('btn-prev').addEventListener('click', () => fetchJobs(currentPage - 1));
  document.getElementById('btn-next').addEventListener('click', () => fetchJobs(currentPage + 1));

  /* ── Panel wiring ────────────────────────────────────────────── */
  document.getElementById('panel-overlay').addEventListener('click', closePanel);
  document.getElementById('panel-close').addEventListener('click', closePanel);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

  /* ── Window focus refresh ────────────────────────────────────── */
  window.addEventListener('focus', () => {
    visitedJobs       = loadSet(VISITED_KEY);
    favoriteCompanies = loadFaveMap();
    renderFavChips();
    renderCurrentView();
  });

  /* ── JD data modal ───────────────────────────────────────────── */
  const jdModal     = document.getElementById('jd-modal');
  const jdModalBody = document.getElementById('jd-modal-body');
  const jdModalTitle = document.getElementById('jd-modal-title');

  function closeJdModal() { jdModal.style.display = 'none'; }
  document.getElementById('jd-modal-close').addEventListener('click', closeJdModal);
  jdModal.addEventListener('click', e => { if (e.target === jdModal) closeJdModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeJdModal(); });

  // Extract salary numbers from compensation string (display only numbers with currency, no long text)
  function isRealCompensation(compensation) {
    const text = String(compensation || '').trim();
    if (!text) return false;
    if (/^(req|r|jr|job)[-_]?\d+[a-z0-9-]*$/i.test(text)) return false;
    if (/^\/?job\//i.test(text)) return false;
    if (!/(salary|compensation|base pay|pay range|ote|equity|bonus|hour|annual|year|yr|[$€£]|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b)/i.test(text)) return false;
    return /[$€£]\s?\d|\b\d{2,3}\s?k\b|\b\d{2,3}[,\s]\d{3}\b|\b\d+\s?-\s?\d+\b/i.test(text);
  }

  function extractSalaryRange(compensation) {
    if (!isRealCompensation(compensation)) return null;
    
    // Detect currency symbol
    const currencyMatch = compensation.match(/[$€£]/);
    const currency = currencyMatch ? currencyMatch[0] : '';
    
    // Extract all numbers (handle formats like $100,000 €90 000 £80k etc.)
    const numbers = [];
    const matches = compensation.match(/[$€£]?\s*(\d{1,3}(?:[,\s]\d{3})*|\d+)(?:[kK])?/g) || [];
    
    for (const match of matches) {
      // Remove currency symbols, spaces, and commas; convert k/K suffix
      let num = match.replace(/[$€£\s,]/g, '');
      if (num.endsWith('k') || num.endsWith('K')) {
        num = String(parseInt(num) * 1000);
      }
      const parsed = parseInt(num, 10);
      if (!isNaN(parsed) && parsed >= 10000) { // Only keep reasonable salary values
        numbers.push(parsed);
      }
    }
    
    // Return unique sorted numbers as range display with currency
    if (numbers.length === 0) return null;
    const unique = [...new Set(numbers)].sort((a, b) => a - b);
    const prefix = currency ? currency + ' ' : '';
    if (unique.length === 1) return prefix + String(unique[0]);
    return prefix + unique.slice(0, 2).join(' - '); // Show min and max
  }

  function renderJdData(data) {
    const field = (label, value) => {
      if (value == null || value === '') return '';
      return `<div class="jd-field"><div class="jd-field-label">${esc(label)}</div><div class="jd-field-value">${esc(String(value))}</div></div>`;
    };
    const list = (label, items) => {
      if (!Array.isArray(items) || items.length === 0) return '';
      return `<div class="jd-field"><div class="jd-field-label">${esc(label)}</div><ul class="jd-field-list">${items.map(i => `<li>${esc(String(i))}</li>`).join('')}</ul></div>`;
    };
    const chips = (label, items) => {
      if (!Array.isArray(items) || items.length === 0) return '';
      return `<div class="jd-field"><div class="jd-field-label">${esc(label)}</div><div class="jd-chips">${items.map(i => `<span class="jd-chip">${esc(String(i))}</span>`).join('')}</div></div>`;
    };
    
    // Extract clean salary range for compensation field
    const cleanCompensation = isRealCompensation(data.compensation) ? data.compensation : null;
    const salaryRange = extractSalaryRange(cleanCompensation);
    
    return [
      field('Title', data.title),
      field('Provider', data.provider),
      field('Location', data.location),
      field('Workplace type', data.workplace_type),
      field('Employment type', data.employment_type),
      salaryRange ? field('Compensation', salaryRange) : field('Compensation', cleanCompensation),
      field('Posted', data.posted_datetime),
      chips('JD concepts', data.jd_concepts),
      list('Responsibilities', data.responsibilities),
      list('Requirements', data.requirements_summary),
    ].filter(Boolean).join('') || '<div class="jd-error">No structured data returned.</div>';
  }

  async function openJdModal(job) {
    jdModal.style.display = 'flex';
    jdModalTitle.textContent = `JD data — ${job.title || 'Job'}`;
    jdModalBody.innerHTML = '<div class="jd-loading">Fetching extracted data…</div>';
    const params = new URLSearchParams({ provider: job.provider, source_key: job.source_key, job_id: job.job_id });
    try {
      const res  = await fetch(`/api/job-parsed?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Request failed');
      jdModalBody.innerHTML = renderJdData(data);
    } catch (err) {
      jdModalBody.innerHTML = `<div class="jd-error">Error: ${esc(err.message || String(err))}</div>`;
    }
  }

  /* ── Boot ────────────────────────────────────────────────────── */
  const bootPage = restoreFromUrl();
  loadSources();
  renderFavChips();
  syncHiddenJobs();
  fetchConfig();
  fetchStats();
  fetchJobs(bootPage);
  pollAutoAnalyzer();
  pollCrawlStatus();

  window.addEventListener('popstate', () => {
    const page = restoreFromUrl();
    const urlSources = new URLSearchParams(location.search).get('sources');
    setSelectedProviders(urlSources ? urlSources.split(',').filter(Boolean) : []);
    document.querySelectorAll('.saved-btn').forEach(btn => {
      const id = Number(btn.dataset.searchId);
      btn.classList.toggle('active', activeSearchIds.has(id));
    });
    applySearchLock(activeSearchIds.size > 1);
    fetchJobs(page);
  });
})();
