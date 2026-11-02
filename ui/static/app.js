// Click-to-load YouTube preview, copy button, and showing error messages from the server.
document.addEventListener('click', function (e) {
  var play = e.target.closest('[data-play]');
  if (play) {
    var box = play.closest('[data-preview]');
    var frame = document.createElement('iframe');
    frame.src = 'https://www.youtube-nocookie.com/embed/' + encodeURIComponent(box.getAttribute('data-preview'));
    frame.title = 'Video preview';
    frame.allow = 'encrypted-media; picture-in-picture';
    frame.setAttribute('allowfullscreen', '');
    box.insertBefore(frame, box.firstChild);
    play.remove();
  }
  var copy = e.target.closest('[data-copy]');
  if (copy) {
    var target = document.getElementById(copy.getAttribute('data-copy'));
    if (target && navigator.clipboard) {
      navigator.clipboard.writeText(target.value).then(function () { copy.textContent = 'Copied'; });
    }
  }
});
document.body.addEventListener('htmx:beforeSwap', function (e) {
  var status = e.detail.xhr.status;
  if (status === 400 || status === 404 || status === 409) { e.detail.shouldSwap = true; e.detail.isError = false; }
});
