// ABOUTME: Updates the YouTube search button's query as the user scrolls.
// ABOUTME: Reads data-yt (search query) and data-yt-label (button label) from sections.
(function() {
    var btn = document.querySelector('.yt-link');
    if (!btn) return;
    var defaultHref = btn.href;
    var sections = document.querySelectorAll('[data-yt]');
    if (sections.length === 0) return;
    var observer = new IntersectionObserver(function(entries) {
        for (var i = 0; i < entries.length; i++) {
            if (entries[i].isIntersecting) {
                var q = entries[i].target.getAttribute('data-yt');
                btn.href = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(q);
                var label = entries[i].target.getAttribute('data-yt-label');
                if (label) { var span = btn.querySelector('.yt-label'); if (span) span.textContent = label; }
            }
        }
    }, { threshold: 0.3 });
    for (var i = 0; i < sections.length; i++) {
        observer.observe(sections[i]);
    }
})();
