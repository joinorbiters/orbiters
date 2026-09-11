/* The landing's own script: it mounts the field behind the page and the typewriter on
 * the title, and that is all.
 *
 * The same field as the community page on `/`, with the same options -- Ivan's ruling
 * of 2026-09-09: the two pages share one background. The canvas is fixed and the
 * page scrolls over it; `animate` drifts it slowly and field.js itself stands still
 * when the reader asked for reduced motion. The title's first word is typed by the shared
 * typewriter.js, and a screen reader hears the same line either way (see the sr-only
 * span in the h1).
 *
 * Since ORB-145 (Ivan, 2026-09-11) the blocks below the hero rise in as they scroll
 * into view, the pitch deck's own gesture: each `[data-reveal]` gets `in` when it
 * enters the viewport, once. The initial state is still the final state for anyone the
 * script does not reach: landing.css hides a block only under `html.js`, which the
 * inline gate in the page's head sets, and shows everything again after three seconds
 * whatever happened here. Under reduced motion every block is marked at once.
 *
 * Since ORB-166 the script also carries the campaign: a visitor from an ad lands here
 * with the six UTM keys in the URL, and the doors into the hub are plain paths, so the
 * first click used to lose them. `carryUtm` appends the keys the page was opened with
 * to every link into `/hub/` (never overriding one a link already carries, `perk` and
 * the like untouched) and writes them in `sessionStorage` under `orbiters.utm`, the key
 * the hub's `resolveUtm` reads when its own URL has none. Session storage on purpose:
 * it dies with the tab, and the only thing it holds is the campaign, never the person.
 * Without JavaScript the links are what the markup says and the attribution is lost,
 * which is what happened before and is the honest fallback.
 */
;(function () {
  var UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'utm_id']
  var UTM_STORAGE_KEY = 'orbiters.utm'

  /** The UTM keys in `search`, trimmed and capped at 200 characters like the hub does. */
  function readUtm(search) {
    var params = new URLSearchParams(search)
    var utm = new URLSearchParams()
    UTM_KEYS.forEach(function (key) {
      var value = (params.get(key) || '').trim().slice(0, 200)
      if (value) utm.set(key, value)
    })
    return utm
  }

  /** Appends the page's UTM keys to every link into the hub and remembers them for the
   *  tab. Returns how many links were rewritten, for the test. */
  function carryUtm(root, search) {
    var utm = readUtm(search === undefined ? window.location.search : search)
    var keys = Array.from(utm.keys())
    if (!keys.length) return 0
    try {
      window.sessionStorage.setItem(UTM_STORAGE_KEY, utm.toString())
    } catch {
      /* storage refused: the links still carry the keys */
    }
    var rewritten = 0
    ;(root || document).querySelectorAll('a[href^="/hub/"]').forEach(function (link) {
      var url = new URL(link.getAttribute('href'), window.location.origin)
      keys.forEach(function (key) {
        if (!url.searchParams.has(key)) url.searchParams.set(key, utm.get(key))
      })
      link.setAttribute('href', url.pathname + url.search + url.hash)
      rewritten += 1
    })
    return rewritten
  }

  window.__landing = { carryUtm: carryUtm, readUtm: readUtm, UTM_KEYS: UTM_KEYS, UTM_STORAGE_KEY: UTM_STORAGE_KEY }

  function reveal() {
    var blocks = document.querySelectorAll('[data-reveal]')
    if (!blocks.length) return
    var reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced || typeof window.IntersectionObserver !== 'function') {
      blocks.forEach(function (el) { el.classList.add('in') })
      return
    }
    var seen = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return
          entry.target.classList.add('in')
          seen.unobserve(entry.target)
        })
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
    )
    blocks.forEach(function (el) { seen.observe(el) })
  }

  function start() {
    carryUtm()
    reveal()
    var role = document.querySelector('h1 .role')
    if (role && window.__typewriter) window.__typewriter.mount(role)
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
