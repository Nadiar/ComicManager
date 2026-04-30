function getCsrfToken() {
  var name = 'csrftoken';
  var cookies = document.cookie.split(';');
  for (var i = 0; i < cookies.length; i++) {
    var parts = cookies[i].trim().split('=');
    if (parts[0] === name) return parts[1] || '';
  }
  return '';
}

window.showConfirm = function(message, onConfirm, label, danger) {
  var modal = document.getElementById('confirm-modal');
  document.getElementById('confirm-modal-message').textContent = message;
  var okBtn = document.getElementById('confirm-modal-ok');
  okBtn.textContent = label || 'Confirm';
  okBtn.className = 'cm-btn sm ' + (danger ? '' : 'ok');
  if (danger) { okBtn.style.color = 'var(--cm-err)'; okBtn.style.borderColor = 'var(--cm-err)'; }
  else { okBtn.style.color = ''; okBtn.style.borderColor = ''; }
  okBtn.onclick = function() {
    modal.close();
    if (onConfirm) onConfirm();
  };
  modal.showModal();
};

var _msgToastTimer = null;
window.showMsgToast = function(message, type) {
  var toast = document.getElementById('msg-toast');
  var inner = document.getElementById('msg-toast-inner');
  document.getElementById('msg-toast-text').textContent = message;
  inner.className = 'alert shadow-lg max-w-sm' +
    (type === 'error' ? ' alert-error' : type === 'success' ? ' alert-success' : ' alert-info');
  toast.classList.remove('hidden');
  if (_msgToastTimer) clearTimeout(_msgToastTimer);
  _msgToastTimer = setTimeout(function() {
    toast.classList.add('hidden');
    _msgToastTimer = null;
  }, 4000);
};
