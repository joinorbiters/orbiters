/* The title's first word, typed and retyped: the word the page ships, then each role
 * in `data-roles` in turn. An IIFE publishing `window.__typewriter`, like field.js, so
 * both page scripts can call it and the tests can load it with `new Function`. Timers
 * only, so fake timers can drive it. The page is complete without it: the word in the
 * markup stays, and so does the line a screen reader hears, which is the sr-only span
 * next to it. This only moves the visible word, which is aria-hidden; the cursor is
 * CSS, switched on by `is-typing`. With prefers-reduced-motion nothing happens at all.
 */
;(function () {
  function mount(el, options) {
    var idle = { stop: function () {} }
    var roles = (el.getAttribute('data-roles') || '').split('|').filter(Boolean)
    var reduced =
      typeof window.matchMedia === 'function' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (roles.length < 2 || reduced) return idle
    options = options || {}
    var type = options.type || 60
    var erase = options.erase || 35
    var hold = options.hold || 1800
    var pause = options.pause || 300
    var shown = el.textContent
    var index = roles.indexOf(shown)
    var word = shown
    var timer
    el.setAttribute('aria-hidden', 'true')
    el.classList.add('is-typing')

    function next(step, ms) {
      timer = setTimeout(step, ms)
    }
    function erasing() {
      shown = shown.slice(0, -1)
      el.textContent = shown
      if (shown) return next(erasing, erase)
      index = (index + 1) % roles.length
      word = roles[index]
      next(typing, pause)
    }
    function typing() {
      shown = word.slice(0, shown.length + 1)
      el.textContent = shown
      if (shown.length < word.length) return next(typing, type)
      next(erasing, hold)
    }
    next(erasing, hold)
    return {
      stop: function () {
        clearTimeout(timer)
      },
    }
  }

  window.__typewriter = { mount: mount }
})()
