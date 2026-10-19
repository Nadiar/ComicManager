let _scrapePk = null;
let _scrapeOnSuccess = null;
let _scrapeOnSkip = null;
let _scrapeOnCancel = null;
let _scrapeBatch = false;
window._scrapeHandled = false;

let _scrapeApiAllMatches = [];
let _scrapeApiShownCount = 0;
const _SCRAPE_API_BATCH = 3;

const _INDUCKS_COUNTRY_LOCK = window._INDUCKS_COUNTRY_LOCK || '';

function openScrapeModal(pk, opts) {
  opts = opts || {};
  _scrapePk = pk;
  _scrapeOnSuccess = opts.onSuccess || function() { location.reload(); };
  _scrapeOnSkip    = opts.onSkip    || null;
  _scrapeOnCancel  = opts.onCancel  || null;
  _scrapeBatch     = !!(opts.batch);
  window._scrapeHandled = false;

  const skipBtn = document.getElementById('scrape-skip-btn');
  skipBtn.style.display = opts.skipEnabled ? '' : 'none';

  _scrapeReset();
  document.getElementById('scrape-modal').showModal();
  document.getElementById('scrape-local-cover').src = `/comics/${pk}/cover/`;

  fetch(`/comics/${pk}/scrape/preview/?force=1`)
    .then(r => r.json())
    .then(data => {
      document.getElementById('scrape-loading').style.display = 'none';

      if (!data.success) {
        const e = document.getElementById('scrape-error');
        e.style.display = '';
        document.getElementById('scrape-error-text').textContent = data.error || 'Error loading matches';
        // A failed local lookup still sends the comic: keep the search
        // sections so it can be matched by hand
        if (data.comic) _scrapeShowSearch(data.comic);
        return;
      }

      _scrapeShowSearch(data.comic);

      if (data.matches.length === 0) {
        document.getElementById('scrape-local-matches').innerHTML =
          '<div style="grid-column:1/-1; text-align:center; padding:16px; font-size:13px; color:var(--cm-warn);">No local matches found</div>';
        document.getElementById('scrape-api-no-local').style.display = '';
        return;
      }

      _scrapeRenderLocalMatches(data.matches);
    })
    .catch(err => {
      document.getElementById('scrape-loading').style.display = 'none';
      document.getElementById('scrape-error').style.display = '';
      document.getElementById('scrape-error-text').textContent = 'Error: ' + err.message;
    });
}

function _scrapeShowSearch(comic) {
  const label = `${comic.series || ''} #${comic.number || ''}`.trim();
  document.getElementById('scrape-modal-title').textContent = label;
  document.getElementById('scrape-local-info').textContent = label;

  const searchStr = `${comic.series || ''} ${comic.number || ''}`.trim();
  document.getElementById('scrape-api-input').value = searchStr;
  const inducksInput = document.getElementById('scrape-inducks-input');
  if (inducksInput) inducksInput.value = searchStr;

  const apiSection = document.getElementById('scrape-api-section');
  apiSection.style.display = 'flex';
  const inducksSection = document.getElementById('scrape-inducks-section');
  if (inducksSection) inducksSection.style.display = 'flex';
}

function _scrapeReset() {
  document.getElementById('scrape-loading').style.display = 'flex';
  document.getElementById('scrape-error').style.display = 'none';
  document.getElementById('scrape-local-matches').innerHTML = '';
  document.getElementById('scrape-local-cover').style.display = '';
  document.getElementById('scrape-modal-title').textContent = 'Loading...';
  document.getElementById('scrape-local-info').textContent = '';

  document.getElementById('scrape-api-section').style.display = 'none';
  document.getElementById('scrape-api-no-local').style.display = 'none';
  document.getElementById('scrape-api-matches').innerHTML = '';
  document.getElementById('scrape-api-loading').style.display = 'none';
  document.getElementById('scrape-api-error').style.display = 'none';
  _scrapeApiAllMatches = [];
  _scrapeApiShownCount = 0;

  const inducksSection = document.getElementById('scrape-inducks-section');
  if (inducksSection) {
    inducksSection.style.display = 'none';
    document.getElementById('scrape-inducks-matches').innerHTML = '';
    document.getElementById('scrape-inducks-loading').style.display = 'none';
    document.getElementById('scrape-inducks-error').style.display = 'none';
  }
}

function _scrapeCard(match, type) {
  const covers = match.cover_urls || (match.cover_url ? [match.cover_url] : []);
  const isRec  = !!match.recommended;
  const borderColor = isRec ? 'var(--cm-ok)' : 'var(--cm-border)';
  const hoverColor  = type === 'inducks' ? 'var(--cm-info)' : type === 'api' ? 'var(--cm-accent)' : 'var(--cm-ok)';
  const chipClass   = type === 'inducks' ? 'info' : type === 'api' ? 'accent' : (isRec ? 'ok' : '');
  const coverIdx    = `scrape-cover-${type}-${Date.now()}-${Math.random().toString(36).slice(2,6)}`;

  const coverHtml = covers.length > 0
    ? `<img src="${_scrapeEsc(covers[0])}" alt="Cover"
            style="max-height:148px; max-width:100%; object-fit:contain; display:block;"
            class="_scrape-cover-img" data-covers='${JSON.stringify(covers)}' data-cover-idx="0" />`
    : `<div style="height:100px; display:flex; align-items:center; justify-content:center; font-size:11px; color:var(--cm-fg-3);">No cover</div>`;

  const multiNav = covers.length > 1 ? `
    <div style="position:absolute; bottom:4px; left:0; right:0; display:flex; justify-content:center; align-items:center; gap:4px;">
      <button type="button" class="cm-icon-btn _scrape-cover-nav" data-dir="prev" data-target="${coverIdx}"
              style="width:20px; height:20px; font-size:14px; background:var(--cm-bg-2); border-radius:50%;">‹</button>
      <span class="_scrape-cover-counter" style="font-size:10px; color:var(--cm-fg-2); background:var(--cm-bg-2); padding:1px 5px; border-radius:8px;">1/${covers.length}</span>
      <button type="button" class="cm-icon-btn _scrape-cover-nav" data-dir="next" data-target="${coverIdx}"
              style="width:20px; height:20px; font-size:14px; background:var(--cm-bg-2); border-radius:50%;">›</button>
    </div>` : '';

  const chips = `<span class="cm-chip${chipClass ? ' ' + chipClass : ''}" style="font-size:10px;">${_scrapeEsc(match.match_type || type)}</span>${isRec ? '<span class="cm-chip ok" style="font-size:10px;">Best Match</span>' : ''}`;

  const card = document.createElement('div');
  card.style.cssText = `background:var(--cm-bg-2); border:2px solid ${borderColor}; border-radius:8px; cursor:pointer; overflow:hidden; transition:border-color .1s; display:flex; flex-direction:column;`;
  card.addEventListener('mouseenter', () => { card.style.borderColor = hoverColor; });
  card.addEventListener('mouseleave', () => { card.style.borderColor = isRec ? 'var(--cm-ok)' : 'var(--cm-border)'; });

  card.innerHTML = `
    <div id="${coverIdx}" style="height:160px; background:var(--cm-bg-3); display:flex; align-items:center; justify-content:center; position:relative; padding:4px;">
      ${coverHtml}
      ${multiNav}
    </div>
    <div style="padding:8px 10px; display:flex; flex-direction:column; gap:3px; flex:1;">
      <div style="font-size:12px; font-weight:600; color:var(--cm-fg-1); line-height:1.3;">${_scrapeEsc(match.series || '')} #${_scrapeEsc(String(match.number || ''))}</div>
      <div class="_scrape-vol-info" data-vol="${match.volume_id || ''}" style="font-size:11px; color:var(--cm-fg-3);">${_scrapeEsc(match.publisher || '')}${match.year ? ' (' + match.year + ')' : ''}</div>
      <div style="display:flex; flex-wrap:wrap; gap:3px; margin-top:4px;">${chips}</div>
    </div>`;

  card.querySelectorAll('._scrape-cover-nav').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const container = document.getElementById(btn.dataset.target);
      const img = container.querySelector('._scrape-cover-img');
      if (!img) return;
      const cvrs = JSON.parse(img.dataset.covers);
      let ci = parseInt(img.dataset.coverIdx);
      ci = btn.dataset.dir === 'next' ? (ci + 1) % cvrs.length : (ci - 1 + cvrs.length) % cvrs.length;
      img.src = cvrs[ci];
      img.dataset.coverIdx = ci;
      const ctr = btn.parentElement.querySelector('._scrape-cover-counter');
      if (ctr) ctr.textContent = `${ci + 1}/${cvrs.length}`;
    });
  });

  return card;
}

function _scrapeEsc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function _scrapeRenderLocalMatches(matches) {
  const grid = document.getElementById('scrape-local-matches');
  matches.forEach(match => {
    const card = _scrapeCard(match, 'local');
    card.addEventListener('click', e => {
      if (!e.target.closest('._scrape-cover-nav')) {
        scrapeSelectMatch(match.issue_id);
      }
    });
    grid.appendChild(card);
  });
}

function scrapeSearchApi() {
  const query = document.getElementById('scrape-api-input').value.trim();
  if (!query) return;

  _scrapeApiAllMatches = [];
  _scrapeApiShownCount = 0;
  document.getElementById('scrape-api-matches').innerHTML = '';
  document.getElementById('scrape-api-loading').style.display = 'flex';
  document.getElementById('scrape-api-error').style.display = 'none';

  fetch(`/comics/${_scrapePk}/scrape/api-search/?q=${encodeURIComponent(query)}`)
    .then(r => r.json().then(data => ({ status: r.status, data })))
    .then(({ status, data }) => {
      document.getElementById('scrape-api-loading').style.display = 'none';
      if (!data.success) {
        const errEl = document.getElementById('scrape-api-error');
        errEl.style.display = '';
        if (data.rate_limited) {
          errEl.style.background = 'color-mix(in srgb, var(--cm-warn) 15%, transparent)';
          errEl.style.borderColor = 'var(--cm-warn)';
          errEl.style.color = 'var(--cm-warn)';
          document.getElementById('scrape-api-error-text').textContent = '\u23F3 ' + data.error;
        } else {
          document.getElementById('scrape-api-error-text').textContent = data.error;
        }
        return;
      }
      if (data.matches.length === 0) {
        document.getElementById('scrape-api-matches').innerHTML =
          '<div style="grid-column:1/-1; text-align:center; padding:16px; font-size:13px; color:var(--cm-fg-3);">No API results found</div>';
        return;
      }
      _scrapeApiAllMatches = data.matches;
      _scrapeApiShownCount = 0;
      _scrapeShowApiResultBatch();
    })
    .catch(err => {
      document.getElementById('scrape-api-loading').style.display = 'none';
      document.getElementById('scrape-api-error').style.display = '';
      document.getElementById('scrape-api-error-text').textContent = err.toString();
    });
}

function _scrapeShowApiResultBatch() {
  const grid = document.getElementById('scrape-api-matches');
  const batch = _scrapeApiAllMatches.slice(_scrapeApiShownCount, _scrapeApiShownCount + _SCRAPE_API_BATCH);
  if (!batch.length) return;

  const existingMore = grid.querySelector('._scrape-show-more');
  if (existingMore) existingMore.remove();

  batch.forEach(match => {
    const card = _scrapeCard(match, 'api');
    card.addEventListener('click', e => {
      if (!e.target.closest('._scrape-cover-nav')) {
        scrapeSelectMatch(match.issue_id);
      }
    });
    grid.appendChild(card);
  });

  _scrapeApiShownCount += batch.length;

  const vids = [...new Set(batch.map(m => m.volume_id).filter(Boolean))];
  if (vids.length) {
    fetch(`/comics/scrape/volume-batch/?vids=${vids.join(',')}`)
      .then(r => r.json())
      .then(data => {
        if (!data.success) return;
        Object.entries(data.volumes).forEach(([vid, info]) => {
          grid.querySelectorAll(`._scrape-vol-info[data-vol="${vid}"]`).forEach(el => {
            const parts = [];
            if (info.publisher) parts.push(info.publisher);
            if (info.year) parts.push(`(${info.year})`);
            el.textContent = parts.join(' ') || '—';
          });
        });
      })
      .catch(() => {});
  }

  if (_scrapeApiShownCount < _scrapeApiAllMatches.length) {
    const remaining = _scrapeApiAllMatches.length - _scrapeApiShownCount;
    const moreDiv = document.createElement('div');
    moreDiv.className = '_scrape-show-more';
    moreDiv.style.cssText = 'grid-column:1/-1; display:flex; justify-content:center; margin-top:4px;';
    moreDiv.innerHTML = `<button type="button" class="cm-btn sm ghost" onclick="_scrapeShowApiResultBatch()">Show ${Math.min(_SCRAPE_API_BATCH, remaining)} more (${remaining} remaining)</button>`;
    grid.appendChild(moreDiv);
  }
}

function scrapeSearchInducks(mode) {
  if (!document.getElementById('scrape-inducks-input')) return;
  const query     = document.getElementById('scrape-inducks-input').value.trim();
  const storycode = document.getElementById('scrape-inducks-storycode').value.trim();
  if (mode === 'storycode' && !storycode) return;
  if (mode !== 'storycode' && !query) return;

  let country = _INDUCKS_COUNTRY_LOCK;
  if (!country) {
    const sel = document.getElementById('scrape-inducks-country');
    if (sel) country = sel.value;
  }

  document.getElementById('scrape-inducks-matches').innerHTML = '';
  document.getElementById('scrape-inducks-loading').style.display = 'flex';
  document.getElementById('scrape-inducks-error').style.display = 'none';

  let url = `/comics/${_scrapePk}/scrape/inducks-search/?`;
  url += mode === 'storycode' ? `storycode=${encodeURIComponent(storycode)}` : `q=${encodeURIComponent(query)}`;
  if (country) url += `&country=${encodeURIComponent(country)}`;

  fetch(url)
    .then(r => r.json())
    .then(data => {
      document.getElementById('scrape-inducks-loading').style.display = 'none';
      if (!data.success) {
        document.getElementById('scrape-inducks-error').style.display = '';
        document.getElementById('scrape-inducks-error-text').textContent = data.error;
        return;
      }
      if (data.matches.length === 0) {
        document.getElementById('scrape-inducks-matches').innerHTML =
          '<div style="grid-column:1/-1; text-align:center; padding:16px; font-size:13px; color:var(--cm-fg-3);">No Inducks results found</div>';
        return;
      }
      const grid = document.getElementById('scrape-inducks-matches');
      data.matches.forEach(match => {
        const card = _scrapeCard({ ...match, match_type: 'inducks', recommended: false }, 'inducks');

        const bodyEl = card.querySelector('div:last-child');
        const stories = match.stories || [];
        const issueUrl = `https://inducks.org/issue.php?c=${encodeURIComponent(match.issuecode)}`;

        const storyBadges = stories.map(s =>
          `<span style="display:inline-flex; align-items:center; gap:2px;">
            <a href="https://inducks.org/story.php?c=${encodeURIComponent(s.code)}" target="_blank"
              class="cm-chip" style="font-size:10px; text-decoration:none;" onclick="event.stopPropagation()"
              title="${_scrapeEsc(s.title || s.code)}">${_scrapeEsc(s.code)}</a>
            <button style="background:none; border:none; cursor:pointer; color:var(--cm-ok); font-size:13px; padding:0 2px;"
              onclick="event.stopPropagation(); scrapeSelectMatch(null, 'inducks', '${_scrapeEsc(match.issuecode)}', '${_scrapeEsc(s.code)}')"
              title="Match this story only">&#x2713;</button>
          </span>`
        ).join('');

        const leadTitle = stories.length > 0 && stories[0].title
          ? `<div style="font-size:11px; color:var(--cm-fg-2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${_scrapeEsc(stories[0].title)}</div>` : '';

        bodyEl.innerHTML = `
          <div style="font-size:12px; font-weight:600; color:var(--cm-fg-1); line-height:1.3;">${_scrapeEsc(match.series || '')} #${_scrapeEsc(String(match.number || ''))}</div>
          <div style="font-size:11px; color:var(--cm-fg-3);">${_scrapeEsc(match.publisher || 'Unknown')} (${match.year || '?'})</div>
          ${leadTitle}
          ${match.pages ? `<div style="font-size:10px; color:var(--cm-fg-3);">${match.pages} pages</div>` : ''}
          <div style="display:flex; flex-wrap:wrap; gap:3px; margin-top:4px;">
            <span class="cm-chip info" style="font-size:10px;">inducks</span>
            ${match.country ? `<span class="cm-chip" style="font-size:10px;">${_scrapeEsc(match.country)}</span>` : ''}
          </div>
          ${storyBadges ? `<div style="display:flex; flex-wrap:wrap; gap:3px; margin-top:4px;">${storyBadges}</div>` : ''}
          <a href="${issueUrl}" target="_blank" style="font-size:10px; color:var(--cm-info); text-decoration:none; margin-top:4px;" onclick="event.stopPropagation()">Issue on Inducks ↗</a>`;

        card.addEventListener('click', e => {
          if (!e.target.closest('._scrape-cover-nav') && !e.target.closest('button') && !e.target.closest('a')) {
            scrapeSelectMatch(null, 'inducks', match.issuecode);
          }
        });
        grid.appendChild(card);
      });
    })
    .catch(err => {
      document.getElementById('scrape-inducks-loading').style.display = 'none';
      document.getElementById('scrape-inducks-error').style.display = '';
      document.getElementById('scrape-inducks-error-text').textContent = err.toString();
    });
}

function scrapeMatchStoryDirect() {
  if (!document.getElementById('scrape-inducks-storycode')) return;
  const storycode = document.getElementById('scrape-inducks-storycode').value.trim();
  if (!storycode) return;
  scrapeSelectMatch(null, 'inducks', null, storycode);
}

function scrapeSelectMatch(issueId, source, issuecode, storycode) {
  window._scrapeHandled = true;
  document.getElementById('scrape-modal').close();

  const base = source === 'inducks'
    ? { source: 'inducks', ...(issuecode ? { issuecode } : {}), ...(storycode ? { storycode } : {}) }
    : { issue_id: issueId };
  const payload = _scrapeBatch ? { ...base, batch: true } : base;

  fetch(`/comics/${_scrapePk}/scrape/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  .then(r => r.json())
  .then(data => {
    if (data.success) {
      if (_scrapeOnSuccess) _scrapeOnSuccess(data);
    } else {
      if (typeof showMsgToast === 'function') showMsgToast('Scrape failed: ' + (data.error || 'Unknown error'), 'error');
    }
  })
  .catch(err => {
    if (typeof showMsgToast === 'function') showMsgToast('Network error: ' + err.message, 'error');
  });
}

function scrapeSkip() {
  window._scrapeHandled = true;
  document.getElementById('scrape-modal').close();
  if (_scrapeOnSkip) _scrapeOnSkip();
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('scrape-api-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); scrapeSearchApi(); }
  });
  document.getElementById('scrape-inducks-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); scrapeSearchInducks(); }
  });
  document.getElementById('scrape-inducks-storycode')?.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); scrapeSearchInducks('storycode'); }
  });

  document.getElementById('scrape-modal')?.addEventListener('close', () => {
    if (window._scrapeHandled) { window._scrapeHandled = false; return; }
    if (_scrapeOnCancel) _scrapeOnCancel();
  });
});
