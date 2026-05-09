// Topnav dropdown hover with grace-period
document.querySelectorAll('.cm-nav-dd').forEach(function(dd) {
  var menu = dd.querySelector('.cm-nav-dd-menu');
  if (!menu) return;
  var timer;
  dd.addEventListener('mouseenter', function() { clearTimeout(timer); menu.style.display = 'block'; });
  dd.addEventListener('mouseleave', function() { timer = setTimeout(function() { menu.style.display = ''; }, 150); });
  menu.addEventListener('mouseenter', function() { clearTimeout(timer); });
  menu.addEventListener('mouseleave', function() { timer = setTimeout(function() { menu.style.display = ''; }, 150); });
});

// Sidebar collapse toggle (persisted in localStorage)
(function() {
  var sb = document.getElementById('cm-sidebar');
  var btn = document.getElementById('cm-sb-toggle');
  if (!sb || !btn) return;
  if (localStorage.getItem('cm.sb.collapsed') === '1') sb.classList.add('collapsed');
  btn.addEventListener('click', function() {
    sb.classList.toggle('collapsed');
    localStorage.setItem('cm.sb.collapsed', sb.classList.contains('collapsed') ? '1' : '0');
  });
})();

function batchAction(url, confirmMsg, taskLabel, btn) {
  showConfirm(confirmMsg, () => {
    btn.disabled = true;
    btn.innerHTML = '<span class="loading loading-spinner loading-sm"></span> Working...';
    fetch(url, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } })
      .then(r => r.json())
      .then(data => {
        if (data.task_id) {
          btn.innerHTML = 'Running...';
          if (window.startTaskPolling) window.startTaskPolling(data.task_id, taskLabel);
        } else if (data.success) {
          btn.innerHTML = 'Done';
          setTimeout(() => window.location.reload(), 1500);
        } else {
          btn.innerHTML = data.error || 'Error';
          btn.disabled = false;
        }
      })
      .catch(err => {
        btn.innerHTML = 'Error';
        btn.title = err.toString();
        btn.disabled = false;
      });
  });
}

function comicActionFadeRow(pk, urlPath, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="loading loading-spinner loading-xs"></span>';
  fetch(`/comics/${pk}/${urlPath}/`, { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken() } })
    .then(r => r.json())
    .then(data => {
      if (data.success) {
        const row = btn.closest('tr');
        row.style.transition = 'opacity 0.3s';
        row.style.opacity = '0';
        setTimeout(() => row.remove(), 300);
      } else {
        btn.innerHTML = 'Error';
        btn.title = data.error || 'Failed';
        btn.disabled = false;
      }
    })
    .catch(err => {
      btn.innerHTML = 'Error';
      btn.title = err.toString();
      btn.disabled = false;
    });
}

function getActionBadgeClass(action) {
  switch (action) {
    case 'SetValue': return 'ok';
    case 'Add': return 'info';
    case 'Remove': return 'warn';
    case 'Replace': return 'violet';
    default: return '';
  }
}

function showTagResultModal(comicTitle, data) {
  const modal = document.getElementById('tag-result-modal');
  document.getElementById('tag-modal-comic-title').textContent = comicTitle;

  const matchedCount = data.matched_rulesets?.length || 0;
  const changesCount = data.changes?.length || 0;
  document.getElementById('tag-matched-count').textContent = matchedCount;
  document.getElementById('tag-changes-count').textContent = changesCount;

  const rulesetsSection = document.getElementById('tag-rulesets-section');
  const changesSection = document.getElementById('tag-changes-section');
  const noMatchesDiv = document.getElementById('tag-no-matches');

  if (matchedCount === 0) {
    rulesetsSection.style.display = 'none';
    changesSection.style.display = 'none';
    noMatchesDiv.style.display = '';
  } else {
    rulesetsSection.style.display = '';
    changesSection.style.display = '';
    noMatchesDiv.style.display = 'none';

    document.getElementById('tag-rulesets-list').innerHTML = data.matched_rulesets.map(name =>
      `<span class="cm-chip accent" style="font-size:11px;">${escapeHtml(name)}</span>`
    ).join('');

    const changesTable = document.getElementById('tag-changes-table');
    if (changesCount > 0) {
      changesTable.innerHTML = data.changes.map(change => `
        <tr class="cm-divider">
          <td style="padding:5px 8px; font-weight:600; color:var(--cm-fg-1);">${escapeHtml(change.field)}</td>
          <td style="padding:5px 8px;"><span class="cm-chip ${getActionBadgeClass(change.modifier)}" style="font-size:10px;">${escapeHtml(change.modifier)}</span></td>
          <td style="padding:5px 8px; max-width:200px; overflow:hidden; text-overflow:ellipsis; color:var(--cm-fg-1);" title="${escapeHtml(change.new_value || '')}">${escapeHtml(change.new_value || '')}</td>
          <td style="padding:5px 8px; font-size:11px; color:var(--cm-fg-3);">${escapeHtml(change.ruleset_name || '')}</td>
        </tr>
      `).join('');
    } else {
      changesTable.innerHTML = `<tr><td colspan="4" style="padding:10px 8px; text-align:center; color:var(--cm-fg-3);">No field changes (rules matched but no modifications needed)</td></tr>`;
    }
  }

  modal.showModal();
}

function showFormatResultModal(comicTitle, data) {
  const modal = document.getElementById('format-result-modal');
  document.getElementById('format-modal-comic-title').textContent = comicTitle;
  document.getElementById('format-series').textContent = data.series || '(none)';
  document.getElementById('format-title').textContent = data.title || '(none)';
  document.getElementById('format-count').textContent = data.count != null ? data.count : '—';
  document.getElementById('format-page-count').textContent = data.page_count != null ? data.page_count + ' pages' : '—';

  const resultBox = document.getElementById('format-result-box');
  const resultText = document.getElementById('format-result-text');

  if (data.detected_format) {
    resultBox.style.background = 'var(--cm-ok-dim)';
    resultBox.style.borderColor = 'var(--cm-ok)';
    resultBox.style.color = 'var(--cm-ok)';
    if (data.format_changed) {
      resultText.innerHTML = `Format detected: <strong>${escapeHtml(data.detected_format)}</strong>`;
    } else {
      resultText.innerHTML = `Format already set to: <strong>${escapeHtml(data.new_format)}</strong>`;
    }
  } else {
    resultBox.style.background = 'var(--cm-info-dim)';
    resultBox.style.borderColor = 'var(--cm-info)';
    resultBox.style.color = 'var(--cm-info)';
    resultText.textContent = 'No format pattern matched. State advanced to "formatted".';
  }

  const patternsList = document.getElementById('format-patterns-list');
  if (data.patterns_checked) {
    patternsList.innerHTML = data.patterns_checked.map(p => `
      <div style="display:flex; align-items:center; gap:6px; font-size:12px; color:${p.matched ? 'var(--cm-ok)' : 'var(--cm-fg-3)'}; font-weight:${p.matched ? '600' : '400'};">
        <span style="flex-shrink:0;">${p.matched ? '✓' : '○'}</span>
        <span>${escapeHtml(p.pattern)}</span>
      </div>
    `).join('');
  }

  modal.showModal();
}

function showOrganizeResultModal(comicTitle, data) {
  const modal = document.getElementById('organize-result-modal');
  document.getElementById('organize-modal-comic-title').textContent = comicTitle;
  document.getElementById('organize-profile').textContent = data.profile || '(fallback)';
  document.getElementById('organize-old-path').textContent = data.old_path || '(none)';
  document.getElementById('organize-new-path').textContent = data.new_path || '(none)';

  const resultBox = document.getElementById('organize-result-box');
  const resultText = document.getElementById('organize-result-text');

  if (data.moved) {
    resultBox.style.background = 'var(--cm-ok-dim)';
    resultBox.style.borderColor = 'var(--cm-ok)';
    resultBox.style.color = 'var(--cm-ok)';
    resultText.textContent = 'File moved to library location.';
  } else {
    resultBox.style.background = 'var(--cm-info-dim)';
    resultBox.style.borderColor = 'var(--cm-info)';
    resultBox.style.color = 'var(--cm-info)';
    resultText.textContent = data.message || 'File already in correct location.';
  }

  modal.showModal();
}
