/* The landing's own script: it mounts the field behind the page, and that is all.
 *
 * The same field as the community page on `/`, with the same options -- Ivan's ruling
 * of 2026-09-09: the two pages share one background. The canvas is fixed and the
 * page scrolls over it; `animate` drifts it slowly and field.js itself stands still
 * when the reader asked for reduced motion. No entrance animation: the initial state
 * is the final state, so the page reads the same with the script and without it.
 */
;(function () {
  function start() {
    var field = window.__pigroField
    var canvas = document.getElementById('field')
    if (!field || !canvas || typeof canvas.getContext !== 'function') return
    var cell = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--landing-cell'))
    field.mount(canvas, { cell: cell || 16, animate: true })
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start)
  } else {
    start()
  }
})()
