/* The landing's own script: it mounts the field behind the hero, and that is all.
 *
 * Still, not drifting: a page that scrolls has enough movement of its own, and the
 * only motion this system spends is on Orbiters, where the field is the whole page.
 * No entrance animation either -- the initial state is the final state, so the page
 * reads the same with the script, without it, and with reduced motion.
 */
;(function () {
  function start() {
    var field = window.__pigroField
    var canvas = document.getElementById('hero-field')
    if (!field || !canvas || typeof canvas.getContext !== 'function') return
    var cell = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--landing-cell'))
    field.mount(canvas, {
      cell: cell || 16,
      seed: 7,
      /* A streak from the upper left down to the lower right, denser to the right
         of the box so the tiles frame the text rather than sit behind it. */
      band: function (u, v) {
        return 1 - Math.abs((u * 1.1 - v * 0.9 - 0.25) * 1.5) - (u < 0.45 ? (0.45 - u) * 1.2 : 0)
      },
    })
  }
  window.__pigroLanding = { start: start }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start)
  } else {
    start()
  }
})()
