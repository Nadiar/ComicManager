(function() {
  let currentGallery = [];
  let currentGalleryIndex = 0;
  let touchStartX = 0;
  let touchEndX = 0;

  window.openLightbox = function(items, startIndex) {
    currentGallery = items || [];
    currentGalleryIndex = startIndex || 0;
    updateGalleryUI();
    document.getElementById('image-modal').showModal();
  };

  window.galleryPrev = function(e) {
    if (e) e.stopPropagation();
    if (currentGallery.length <= 1) return;
    currentGalleryIndex = (currentGalleryIndex - 1 + currentGallery.length) % currentGallery.length;
    updateGalleryUI();
  };

  window.galleryNext = function(e) {
    if (e) e.stopPropagation();
    if (currentGallery.length <= 1) return;
    currentGalleryIndex = (currentGalleryIndex + 1) % currentGallery.length;
    updateGalleryUI();
  };

  function updateGalleryUI() {
    var item = currentGallery[currentGalleryIndex];
    if (!item) return;

    var img = document.getElementById('modal-full-img');
    var cap = document.getElementById('modal-img-caption');
    var counter = document.getElementById('gallery-counter');
    var prevBtn = document.getElementById('gallery-prev');
    var nextBtn = document.getElementById('gallery-next');

    img.src = item.url;
    cap.textContent = item.caption || '';

    if (currentGallery.length > 1) {
      counter.textContent = (currentGalleryIndex + 1) + ' / ' + currentGallery.length;
      counter.style.display = '';
      prevBtn.style.display = 'flex';
      nextBtn.style.display = 'flex';
    } else {
      counter.style.display = 'none';
      prevBtn.style.display = 'none';
      nextBtn.style.display = 'none';
    }
  }

  function handleSwipe() {
    var threshold = 50;
    if (touchEndX < touchStartX - threshold) galleryNext();
    if (touchEndX > touchStartX + threshold) galleryPrev();
  }

  document.addEventListener('DOMContentLoaded', function() {
    var modal = document.getElementById('image-modal');
    if (!modal) return;

    modal.addEventListener('touchstart', function(e) { touchStartX = e.changedTouches[0].screenX; }, false);
    modal.addEventListener('touchend', function(e) { touchEndX = e.changedTouches[0].screenX; handleSwipe(); }, false);

    document.addEventListener('keydown', function(e) {
      if (!modal.open) return;
      if (e.key === 'ArrowLeft') galleryPrev();
      if (e.key === 'ArrowRight') galleryNext();
    });
  });
})();
