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
