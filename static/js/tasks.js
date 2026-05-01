(function() {
  var POLL_INTERVAL = 2000;
  var activeTaskId = null;
  var taskLabel = '';
  var cancelRequested = false;

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

  var actionQueue = [];

  function updateQueueIndicator() {
    if (!queueStatus) return;
    if (actionQueue.length === 0) {
      queueStatus.classList.add('hidden');
      queueStatus.textContent = '';
    } else {
      queueStatus.textContent = actionQueue.length === 1 ? '1 more task queued' : actionQueue.length + ' more tasks queued';
      queueStatus.classList.remove('hidden');
    }
  }

  async function processNextAction() {
    if (actionQueue.length === 0) {
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
        processNextAction();
      }
    } catch (err) {
      processNextAction();
    }
  }

  window.isTaskActive = function() { return !!activeTaskId; };

  window.enqueueAction = function(actionFn, label, btn) {
    actionQueue.push({ action: actionFn, label: label, btn: btn || null });
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

  function showErrors(errors) {
    if (!errors || errors.length === 0) {
      errorList.classList.add('hidden');
      errorList.innerHTML = '';
      return;
    }
    errorList.innerHTML = errors.map(function(e) {
      var safe = e.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      return '<div class="text-xs text-error/80 font-mono leading-tight" title="' + safe + '">' + safe + '</div>';
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

  function startPolling(taskId, toastLabel) {
    activeTaskId = taskId;
    taskLabel = toastLabel || 'Processing';
    cancelRequested = false;
    cancelBtn.textContent = 'Cancel';
    cancelBtn.disabled = false;
    showToast();
    showCancel();
    hideDismiss();
    hideLogLink();
    showErrors(null);
    labelEl.textContent = taskLabel + '...';
    status.textContent = 'Starting...';
    count.textContent = '0%';
    bar.value = 0;
    bar.classList.remove('progress-success', 'progress-error');
    bar.classList.add('progress-primary');
    pollProgress();
  }

  function pollProgress() {
    if (!activeTaskId) return;

    fetch('/comics/task-progress/' + activeTaskId + '/')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.state === 'PROGRESS') {
          var pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
          bar.value = pct;
          count.textContent = pct + '%';
          status.textContent = (data.current && data.total ? data.current + ' / ' + data.total + ' — ' : '') + progressText(data);
          setTimeout(pollProgress, POLL_INTERVAL);

        } else if (data.state === 'SUCCESS') {
          bar.value = 100;
          var r = data.result || {};
          markTaskDone(activeTaskId);
          hideCancel();
          if (r.cancelled) {
            labelEl.textContent = taskLabel + ' cancelled';
            bar.classList.remove('progress-primary');
            bar.classList.add('progress-error');
          } else if (r.stopped_early) {
            labelEl.textContent = taskLabel + ' stopped early';
            bar.classList.remove('progress-primary');
            bar.classList.add('progress-error');
          } else {
            labelEl.textContent = taskLabel + ' complete!';
            bar.classList.remove('progress-primary');
            bar.classList.add('progress-success');
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
            showDismiss();
          }

        } else if (data.state === 'FAILURE') {
          markTaskDone(activeTaskId);
          hideCancel();
          labelEl.textContent = taskLabel + ' failed';
          status.textContent = data.error || 'Unknown error';
          bar.classList.remove('progress-primary');
          bar.classList.add('progress-error');
          activeTaskId = null;
          if (actionQueue.length > 0) {
            setTimeout(processNextAction, 800);
          } else {
            showDismiss();
          }

        } else {
          status.textContent = data.state === 'STARTED' ? 'Starting...' : 'Queued...';
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

  window.startTaskPolling = startPolling;

  window.dismissTaskToast = function() {
    actionQueue = [];
    updateQueueIndicator();
    hideToast();
    location.reload();
  };

  window.showQuickToast = function(message, type) {
    labelEl.textContent = message;
    bar.value = 100;
    bar.classList.remove('progress-primary', 'progress-error', 'progress-success');
    bar.classList.add(type === 'error' ? 'progress-error' : 'progress-success');
    count.textContent = '';
    hideDismiss();
    showErrors(null);
    status.textContent = '';
    hideCancel();
    showToast();
    setTimeout(function() { hideToast(); location.reload(); }, 2000);
  };

  // WebSocket real-time task events
  (function() {
    function connect() {
      var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      var ws = new WebSocket(proto + '//' + location.host + '/ws/tasks/');

      ws.onmessage = function(e) {
        var msg;
        try { msg = JSON.parse(e.data); } catch(_) { return; }

        if (msg.type === 'task.snapshot') {
          if (!activeTaskId && msg.tasks && msg.tasks.length > 0) {
            var running = msg.tasks.find(function(t) { return t.state === 'PROGRESS' && !isTaskDone(t.task_id); });
            if (running) {
              startPolling(running.task_id, running.label || 'Processing');
              bar.value = running.pct || 0;
              count.textContent = (running.pct || 0) + '%';
              if (running.sublabel) status.textContent = running.sublabel;
            }
          }
          return;
        }

        if (!activeTaskId || msg.task_id !== activeTaskId) return;

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
            bar.classList.remove('progress-primary'); bar.classList.add('progress-error');
          } else if (r.stopped_early) {
            labelEl.textContent = taskLabel + ' stopped early';
            bar.classList.remove('progress-primary'); bar.classList.add('progress-error');
          } else {
            labelEl.textContent = taskLabel + ' complete!';
            bar.classList.remove('progress-primary'); bar.classList.add('progress-success');
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
            showDismiss();
          }
        } else if (msg.state === 'FAILURE') {
          markTaskDone(activeTaskId);
          hideCancel();
          labelEl.textContent = taskLabel + ' failed';
          status.textContent = msg.error || 'Unknown error';
          bar.classList.remove('progress-primary'); bar.classList.add('progress-error');
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
