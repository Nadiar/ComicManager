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
