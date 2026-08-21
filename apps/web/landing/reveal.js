/* The whole of the landing page's JavaScript.
 *
 * The initial state is VISIBLE. This adds [data-hidden] then removes it; CSS
 * that hides and JS that reveals would blank the page whenever the script does
 * not run. So: no IntersectionObserver, reduced motion, or nothing to observe
 * all mean "do not hide" -- never "hide and hope".
 */
;(function () {
  function reveal(doc) {
    var reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || typeof IntersectionObserver !== 'function') return

    var targets = doc.querySelectorAll('.rise')
    if (targets.length === 0) return

    var observer = new IntersectionObserver(
      function (entries) {
        for (var i = 0; i < entries.length; i += 1) {
          if (!entries[i].isIntersecting) continue
          entries[i].target.removeAttribute('data-hidden')
          // Stop watching once shown -- else it keeps firing on every scroll.
          observer.unobserve(entries[i].target)
        }
      },
      { rootMargin: '0px 0px -10% 0px', threshold: 0.01 },
    )

    for (var index = 0; index < targets.length; index += 1) {
      // Stagger lives in CSS (transition-delay reads --rise-index); this just
      // supplies the ordinal, reset every 6 so a long page never queues seconds
      // of delay.
      targets[index].style.setProperty('--rise-index', String(index % 6))
      targets[index].setAttribute('data-hidden', '')
      observer.observe(targets[index])
    }
  }

  window.__pigroReveal = reveal
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      reveal(document)
    })
  } else {
    reveal(document)
  }
})()
