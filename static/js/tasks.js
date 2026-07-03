(function() {
  var POLL_INTERVAL = 2000;
  var activeTaskId = null;
  var taskLabel = '';
  var cancelRequested = false;
  var _taskOnComplete = null;
  var _taskUsedCallback = false;

  var toast = document.getElementById('task-progress-toast');
  var labelEl = document.getElementById('task-progress-label');
  var count = document.getElementById('task-progress-count');
  var bar = document.getElementById('task-progress-bar');
  var status = document.getElementById('task-progress-status');
  var queueStatus = document.getElementById('task-queue-status');
  var cancelBtn = document.getElementById('task-cancel-btn');
  var dismissBtn = document.getElementById('task-dismiss-btn');
  var errorList = document.getElementById('task-error-list');
  var logLink = document.getElementById('task-log-link');
  var spinner = document.getElementById('task-spinner');
  var queueListEl = document.getElementById('task-queue-list');
  var pendingCount = 0;   // server-side queued items behind the running one
  var lastWsAt = 0;       // last time the WebSocket delivered an update for the active task

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  var actionQueue = [];
  var batchTotal = 0;   // total tasks in the current sequential batch
  var batchDone = 0;    // tasks finished so far in the current batch

  function updateQueueIndicator() {
    if (!queueStatus) return;
    if (batchTotal > 1) {
      var current = Math.min(batchDone + 1, batchTotal);
      queueStatus.textContent = 'Task ' + current + ' of ' + batchTotal;
      queueStatus.classList.remove('hidden');
    } else {
      queueStatus.classList.add('hidden');
      queueStatus.textContent = '';
    }
  }

  function resetBatch() {
    batchTotal = 0;
    batchDone = 0;
    updateQueueIndicator();
  }

  async function processNextAction() {
    if (actionQueue.length === 0) {
      resetBatch();
      showDismiss();
      return;
    }
    var next = actionQueue.shift();
    updateQueueIndicator();
    if (next.btn) { next.btn.textContent = 'Starting...'; }
    try {
      var data = await next.action();
      if (data && data.task_id) {
        startPolling(data.task_id, next.label);
      } else {
        // Queued task failed to start — count it as done so the batch counter
        // keeps advancing, then move on.
        batchDone++;
        if (next.btn) { next.btn.textContent = (data && data.error) ? 'Error' : 'Skipped'; }
        processNextAction();
      }
    } catch (err) {
      batchDone++;
      processNextAction();
    }
  }

  window.isTaskActive = function() { return !!activeTaskId; };

  window.enqueueAction = function(actionFn, label, btn) {
    actionQueue.push({ action: actionFn, label: label, btn: btn || null });
    batchTotal++;
    updateQueueIndicator();
    if (btn) {
      btn.textContent = 'Queued';
      btn.disabled = true;
    }
  };

  function showToast() { toast.classList.remove('hidden'); }
  function hideToast() { toast.classList.add('hidden'); }
  function showCancel() { cancelBtn.classList.remove('hidden'); }
  function hideCancel() { cancelBtn.classList.add('hidden'); }
  function showDismiss() { dismissBtn.classList.remove('hidden'); }
  function hideDismiss() { dismissBtn.classList.add('hidden'); }
  function showLogLink() { logLink.classList.remove('hidden'); }
  function hideLogLink() { logLink.classList.add('hidden'); }
  function showSpinner() { if (spinner) spinner.classList.remove('hidden'); }
  function hideSpinner() { if (spinner) spinner.classList.add('hidden'); }

  function markTaskDone(taskId) {
    try {
      var done = JSON.parse(sessionStorage.getItem('cm.done_tasks') || '[]');
      if (done.indexOf(taskId) === -1) { done.push(taskId); }
      sessionStorage.setItem('cm.done_tasks', JSON.stringify(done.slice(-20)));
    } catch(e) {}
  }
  function isTaskDone(taskId) {
    try {
      return JSON.parse(sessionStorage.getItem('cm.done_tasks') || '[]').indexOf(taskId) !== -1;
    } catch(e) { return false; }
  }
  window._isTaskDone = isTaskDone;

  function _doRefreshOrReload() {
    var container = document.getElementById('comic-results-container');
    if (container && window.htmx) {
      htmx.ajax('GET', window.location.href, {target: '#comic-results-container', swap: 'innerHTML'});
    } else {
      location.reload();
    }
  }

  function _finishTask(r) {
    var hasErrors = r.errors && r.errors.length > 0;
    showDismiss();
    if (!hasErrors && actionQueue.length === 0 && pendingCount === 0) {
      setTimeout(function() {
        if (_taskUsedCallback) return;
        _doRefreshOrReload();
        hideToast();
      }, 2500);
    }
  }

  function showErrors(errors) {
    if (!errors || errors.length === 0) {
      errorList.classList.add('hidden');
      errorList.innerHTML = '';
      return;
    }
    errorList.innerHTML = errors.map(function(e) {
      var safe = e.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return '<div class="text-xs font-mono leading-tight" style="color:var(--cm-err); opacity:.85;" title="' + safe + '">' + safe + '</div>';
    }).join('');
    errorList.classList.remove('hidden');
  }

  function progressText(data) {
    if (data.step) {
      var text = data.step;
      if (data.comic) text += ' — ' + data.comic;
      if (data.errors && data.errors.length > 0) text += ' (' + data.errors.length + ' error' + (data.errors.length !== 1 ? 's' : '') + ')';
      return text;
    }
    if (data.flagged !== undefined && data.cleared !== undefined) {
      var parts = [];
      if (data.flagged > 0) parts.push(data.flagged + ' flagged');
      if (data.cleared > 0) parts.push(data.cleared + ' cleared');
      return parts.length ? parts.join(', ') : (data.current || 0) + ' checked';
    }
    if (data.mismatched !== undefined && data.matched !== undefined) {
      var parts = [];
      if (data.mismatched > 0) parts.push(data.mismatched + ' mismatched');
      if (data.matched > 0) parts.push(data.matched + ' matched');
      if (data.errors && data.errors.length > 0) parts.push(data.errors.length + ' errors');
      return parts.length ? parts.join(', ') : (data.current || 0) + ' checked';
    }
    if (data.action) {
      var actionLabel = {tag: 'tagged', format: 'formatted', organize: 'organized', write: 'written'}[data.action] || 'processed';
      return (data.success_count || 0) + ' ' + actionLabel +
        (data.errors && data.errors.length > 0 ? ', ' + data.errors.length + ' errors' : '');
    }
    if (data.written !== undefined) {
      return (data.written || 0) + ' written' +
        (data.errors && data.errors.length > 0 ? ', ' + data.errors.length + ' errors' : '');
    }
    if (data.moved !== undefined) {
      return (data.moved || 0) + ' moved' +
        (data.errors && data.errors.length > 0 ? ', ' + data.errors.length + ' errors' : '');
    }
    return (data.processed || 0) + ' processed' +
      (data.errors && data.errors.length > 0 ? ', ' + data.errors.length + ' errors' : '');
  }

  function successText(r) {
    if (r.stopped_early) {
      var done = r.processed || r.written || r.success_count || r.moved || 0;
      var errCount = r.errors && r.errors.length > 0 ? r.errors.length : 1;
      return 'Stopped after ' + done + ' processed — ' + errCount + ' error' + (errCount !== 1 ? 's' : '');
    }
    if (r.cancelled) {
      var done = r.processed || r.written || r.success_count || 0;
      return 'Cancelled after ' + done + ' processed';
    }
    if (r.flagged !== undefined && r.cleared !== undefined) {
      var parts = [];
      if (r.flagged > 0) parts.push(r.flagged + ' flagged');
      if (r.cleared > 0) parts.push(r.cleared + ' cleared');
      return (parts.length ? parts.join(', ') : 'No changes') + ' (of ' + (r.total || 0) + ' checked)';
    }
    if (r.mismatched !== undefined && r.matched !== undefined) {
      var parts = [];
      if (r.mismatched > 0) parts.push(r.mismatched + ' mismatched');
      if (r.matched > 0) parts.push(r.matched + ' matched');
      if (r.errors && r.errors.length > 0) parts.push(r.errors.length + ' errors');
      return (parts.length ? parts.join(', ') : 'No changes') + ' (of ' + (r.total || 0) + ' checked)';
    }
    if (r.action) {
      var actionLabel = {tag: 'tagged', format: 'formatted', organize: 'organized', write: 'written'}[r.action] || 'processed';
      return (r.success_count || 0) + ' of ' + (r.total || 0) + ' ' + actionLabel +
        (r.errors && r.errors.length > 0 ? ', ' + r.errors.length + ' errors' : '');
    }
    if (r.written !== undefined) {
      return (r.written || 0) + ' of ' + (r.total || 0) + ' written' +
        (r.errors && r.errors.length > 0 ? ', ' + r.errors.length + ' errors' : '');
    }
    if (r.moved !== undefined) {
      var parts = [(r.moved || 0) + ' moved'];
      if (r.already_ok > 0) parts.push(r.already_ok + ' already ok');
      if (r.errors && r.errors.length > 0) parts.push(r.errors.length + ' errors');
      return parts.join(', ') + ' (of ' + (r.total || 0) + ')';
    }
    if (r.matched !== undefined && r.failed !== undefined) {
      var parts = [];
      if (r.matched > 0) parts.push(r.matched + ' matched');
      if (r.failed > 0) parts.push(r.failed + ' failed');
      if (r.errors && r.errors.length > 0) parts.push(r.errors.length + ' errors');
      return parts.length ? parts.join(', ') + ' (of ' + (r.total || 0) + ')' : 'Done';
    }
    return (r.processed || 0) + ' of ' + (r.total || 0) + ' processed' +
      (r.errors && r.errors.length > 0 ? ', ' + r.errors.length + ' errors' : '');
  }

  function startPolling(taskId, toastLabel, onComplete) {
    // A task starting while no batch is in progress begins a new batch.
    // Continuation calls from processNextAction keep the existing batch counts.
    if (batchTotal === 0) { batchTotal = 1; batchDone = 0; }
    _taskOnComplete = onComplete || null;
    _taskUsedCallback = false;
    activeTaskId = taskId;
    taskLabel = toastLabel || 'Processing';
    cancelRequested = false;
    cancelBtn.textContent = 'Cancel';
    cancelBtn.disabled = false;
    showToast();
    showSpinner();
    showCancel();
    // Dismiss stays available in every state (including queued/running) so a
    // toast can always be cleared, even one pinned to a stuck/forgotten task.
    showDismiss();
    hideLogLink();
    showErrors(null);
    labelEl.textContent = taskLabel + '...';
    status.textContent = 'Starting...';
    // Seed the bar at the batch baseline so a continuing batch doesn't snap
    // back to 0% between tasks.
    var basePct = batchTotal > 1 ? Math.round((batchDone / batchTotal) * 100) : 0;
    count.textContent = basePct + '%';
    bar.value = basePct;
    bar.classList.remove('ok', 'err');
    updateQueueIndicator();
    pollProgress();
  }

  function pollProgress() {
    if (!activeTaskId) return;

    fetch('/comics/task-progress/' + activeTaskId + '/')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.state === 'PROGRESS') {
          var taskFrac = data.total > 0 ? (data.current / data.total) : 0;
          // For a multi-task batch the bar tracks overall progress across all
          // tasks; for a single task it tracks that task's own progress.
          var pct = batchTotal > 1
            ? Math.round(((batchDone + taskFrac) / batchTotal) * 100)
            : Math.round(taskFrac * 100);
          bar.value = pct;
          count.textContent = pct + '%';
          status.textContent = (data.current && data.total ? data.current + ' / ' + data.total + ' — ' : '') + progressText(data);
          setTimeout(pollProgress, POLL_INTERVAL);

        } else if (data.state === 'SUCCESS') {
          var r = data.result || {};
          markTaskDone(activeTaskId);
          hideCancel();
          batchDone++;
          if (r.cancelled) {
            labelEl.textContent = taskLabel + ' cancelled';
            bar.classList.add('err');
          } else if (r.stopped_early) {
            labelEl.textContent = taskLabel + ' stopped early';
            bar.classList.add('err');
          } else {
            labelEl.textContent = taskLabel + ' complete!';
            bar.classList.add('ok');
          }
          count.textContent = '';
          status.textContent = successText(r);
          showErrors(r.errors);
          showLogLink();
          activeTaskId = null;
          if (actionQueue.length > 0) {
            // More tasks queued: hold the bar at the batch baseline (not 100%)
            // and advance the "Task X of Y" counter before the next one starts.
            bar.classList.remove('ok', 'err');
            bar.value = Math.round((batchDone / batchTotal) * 100);
            updateQueueIndicator();
            status.textContent = 'Starting next task...';
            setTimeout(processNextAction, 800);
          } else {
            bar.value = 100;
            resetBatch();
            if (_taskOnComplete) {
              var cb = _taskOnComplete;
              _taskOnComplete = null;
              _taskUsedCallback = true;
              try { cb(); } catch(e) {}
            } else {
              _finishTask(r);
            }
          }

        } else if (data.state === 'FAILURE') {
          markTaskDone(activeTaskId);
          hideCancel();
          batchDone++;
          labelEl.textContent = taskLabel + ' failed';
          status.textContent = data.error || 'Unknown error';
          bar.classList.add('err');
          activeTaskId = null;
          if (actionQueue.length > 0) {
            updateQueueIndicator();
            setTimeout(processNextAction, 800);
          } else {
            resetBatch();
            showDismiss();
          }

        } else {
          // Don't let a stale poll downgrade the display to "Queued..." while
          // the WebSocket is actively delivering progress for this task.
          if (Date.now() - lastWsAt > 4000) {
            status.textContent = data.state === 'STARTED' ? 'Starting...' : 'Queued...';
          }
          setTimeout(pollProgress, POLL_INTERVAL);
        }
      })
      .catch(function() {
        setTimeout(pollProgress, POLL_INTERVAL * 2);
      });
  }

  window.cancelActiveTask = function() {
    if (!activeTaskId || cancelRequested) return;
    cancelRequested = true;
    cancelBtn.textContent = 'Cancelling...';
    cancelBtn.disabled = true;
    status.textContent = 'Finishing current item, then stopping...';
    var csrfToken = document.cookie.match(/csrftoken=([^;]+)/);
    fetch('/comics/task-cancel/' + activeTaskId + '/', {
      method: 'POST',
      headers: {'X-CSRFToken': csrfToken ? csrfToken[1] : ''},
    });
  };

  // Obsolete: action handlers used to call this with the dispatch response's
  // task_id to start the toast. That id is now the QueuedTask id, not the
  // running Celery task, so polling it shows a false "Queued...". The toast is
  // driven entirely by the WebSocket queue snapshot (which resumes the real
  // running task), so this is a no-op. Kept as a stub so the many callers do
  // not need editing; the end-of-queue refresh is handled by _finishTask.
  window.startTaskPolling = function(taskId, label, onComplete) {};

  window.dismissTaskToast = function() {
    // Stop any in-flight polling and forget the task on the server so the
    // resume block can't re-inject it on the next page load.
    var dismissedId = activeTaskId;
    activeTaskId = null;
    if (dismissedId) {
      var csrfToken = document.cookie.match(/csrftoken=([^;]+)/);
      fetch('/comics/task-dismiss/' + dismissedId + '/', {
        method: 'POST',
        headers: {'X-CSRFToken': csrfToken ? csrfToken[1] : ''},
      }).catch(function() {});
    }
    actionQueue = [];
    resetBatch();
    hideToast();
    if (!_taskUsedCallback) {
      _doRefreshOrReload();
    }
    _taskUsedCallback = false;
  };

  // Show a one-shot result in the standard task toast (no polling): filled bar,
  // optional error list, audit-log link, and a persistent Dismiss button.
  // Used by synchronous actions (e.g. single-comic Move) so they match the
  // look of background Celery tasks instead of a fast-vanishing alert.
  // opts: { label, status, success, errors: [str], showLog }
  window.showResultToast = function(opts) {
    opts = opts || {};
    // Never clobber a toast that is actively tracking a running task.
    if (activeTaskId) {
      if (window.showMsgToast) window.showMsgToast(opts.label || '', opts.success ? 'success' : 'error');
      return;
    }
    hideSpinner();
    labelEl.textContent = opts.label || '';
    bar.value = 100;
    bar.classList.remove('ok', 'err');
    bar.classList.add(opts.success ? 'ok' : 'err');
    count.textContent = '';
    status.textContent = opts.status || '';
    hideCancel();
    showErrors(opts.errors && opts.errors.length ? opts.errors : null);
    if (opts.showLog) showLogLink(); else hideLogLink();
    showDismiss();
    // Dismiss should just close the toast (no surprise page reload).
    _taskUsedCallback = true;
    showToast();
  };

  window.showQuickToast = function(message, type) {
    labelEl.textContent = message;
    bar.value = 100;
    bar.classList.remove('ok', 'err');
    bar.classList.add(type === 'error' ? 'err' : 'ok');
    count.textContent = '';
    hideDismiss();
    showErrors(null);
    status.textContent = '';
    hideCancel();
    showToast();
    setTimeout(function() { hideToast(); location.reload(); }, 2000);
  };

  // ── Server-driven queue (cross-device) ─────────────────────────────────
  function renderQueueList(queued) {
    if (!queueListEl) return;
    if (!queued.length) { queueListEl.classList.add('hidden'); queueListEl.innerHTML = ''; return; }
    queueListEl.innerHTML = queued.map(function(t) {
      return '<div class="flex items-center gap-1.5 text-xs cm-text-muted">' +
        '<span class="flex-1 truncate">' + escapeHtml(t.label) + '</span>' +
        '<button class="cm-btn sm ghost" style="color:var(--cm-err);padding:0 6px;" title="Remove from queue" ' +
        'onclick="window.cancelQueued(\'' + t.id + '\')">&times;</button>' +
        '</div>';
    }).join('');
    queueListEl.classList.remove('hidden');
  }

  // Render the queue from a server snapshot: resume the running task's progress
  // (this is what restores the toast on navigation, reload, or another device)
  // and list the queued items with per-item cancel.
  window._renderQueue = function(tasks) {
    tasks = tasks || [];
    var running = tasks.filter(function(t) { return t.state === 'running'; });
    var queued  = tasks.filter(function(t) { return t.state === 'queued'; });
    pendingCount = queued.length;
    var run = running[0];
    if (run && run.celery_task_id && activeTaskId !== run.celery_task_id && !isTaskDone(run.celery_task_id)) {
      startPolling(run.celery_task_id, run.label || 'Processing');
    }
    renderQueueList(queued);
    if (tasks.length) { showToast(); }
    else if (!activeTaskId) { hideToast(); }
  };

  window.cancelQueued = function(id) {
    var csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
    fetch('/comics/queue/' + id + '/cancel/', { method: 'POST', headers: { 'X-CSRFToken': csrf } }).catch(function(){});
  };

  // WebSocket real-time task events
  (function() {
    function connect() {
      var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      var ws = new WebSocket(proto + '//' + location.host + '/ws/tasks/');

      ws.onmessage = function(e) {
        var msg;
        try { msg = JSON.parse(e.data); } catch(_) { return; }

        if (msg.type === 'queue.snapshot') {
          window._renderQueue(msg.tasks || []);
          return;
        }

        if (!activeTaskId || msg.task_id !== activeTaskId) return;
        lastWsAt = Date.now();

        if (msg.state === 'PROGRESS') {
          if (msg.pct !== undefined) bar.value = msg.pct;
          count.textContent = (msg.pct || 0) + '%';
          status.textContent = (msg.current && msg.total ? msg.current + ' / ' + msg.total + ' — ' : '') + (msg.sublabel || progressText(msg));
        } else if (msg.state === 'SUCCESS') {
          bar.value = 100;
          markTaskDone(activeTaskId);
          hideCancel();
          var r = msg.result || {};
          if (r.cancelled) {
            labelEl.textContent = taskLabel + ' cancelled';
            bar.classList.add('err');
          } else if (r.stopped_early) {
            labelEl.textContent = taskLabel + ' stopped early';
            bar.classList.add('err');
          } else {
            labelEl.textContent = taskLabel + ' complete!';
            bar.classList.add('ok');
          }
          count.textContent = '';
          status.textContent = successText(r);
          showErrors(r.errors);
          showLogLink();
          activeTaskId = null;
          if (actionQueue.length > 0) {
            status.textContent = 'Starting next task...';
            setTimeout(processNextAction, 800);
          } else {
            if (_taskOnComplete) {
              var cb = _taskOnComplete;
              _taskOnComplete = null;
              _taskUsedCallback = true;
              try { cb(); } catch(e) {}
            } else {
              _finishTask(r);
            }
          }
        } else if (msg.state === 'FAILURE') {
          markTaskDone(activeTaskId);
          hideCancel();
          labelEl.textContent = taskLabel + ' failed';
          status.textContent = msg.error || 'Unknown error';
          bar.classList.add('err');
          activeTaskId = null;
          if (actionQueue.length > 0) {
            setTimeout(processNextAction, 800);
          } else {
            showDismiss();
          }
        }
      };

      ws.onclose = function() { setTimeout(connect, 3000); };
      ws.onerror = function() {};
    }

    connect();
  })();
})();
