// ABOUTME: Loads KaTeX from CDN and auto-renders \( ... \) and $$ ... $$ math on the page.
// ABOUTME: Use by adding <script src="../shared/katex.js" defer></script> (or "shared/katex.js" from root).
(function() {
    var css = document.createElement('link');
    css.rel = 'stylesheet';
    css.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css';
    document.head.appendChild(css);

    var core = document.createElement('script');
    core.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js';
    core.onload = function() {
        var auto = document.createElement('script');
        auto.src = 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js';
        auto.onload = function() {
            renderMathInElement(document.body, {
                delimiters: [
                    { left: '$$', right: '$$', display: true },
                    { left: '\\(', right: '\\)', display: false }
                ]
            });
        };
        document.head.appendChild(auto);
    };
    document.head.appendChild(core);
})();
