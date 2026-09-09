/* The cookie notice, and the only thing that can load the measurement pixel.
 *
 * The pixel is not on the page until somebody says yes. That is the whole design: the
 * SDK is *injected* here rather than sitting in the markup, so before a decision the
 * browser makes no request to OpenAI at all -- no script, no cookie, no ping, and
 * nothing to explain. A snippet in the head with `oaiq('consent', false)` after it
 * would still have fetched the script and handed a third party the visitor's address.
 *
 * Consequences worth knowing:
 *   - with JavaScript off, nothing here runs, so there is no notice and no tracker,
 *     which is the correct pair;
 *   - a refusal is remembered and the notice does not come back;
 *   - `orbiters.js` calls `window.oaiq` if it is a function. The stub below is defined
 *     only once consent is granted, so a signup made under a refusal measures nothing.
 *
 * The two pages that carry this are the two an ad can land on. privacy.html and
 * termini.html have no pixel and therefore nothing to ask about.
 */
;(function () {
  var STORAGE_KEY = 'orbiters.consent'
  var GRANTED = 'granted'
  var DENIED = 'denied'
  var PIXEL_ID = '9r6qrnPxBV8WDVGtpuaqxh'
  var SDK_URL = 'https://bzrcdn.openai.com/sdk/oaiq.min.js'

  /* localStorage throws rather than returning null in a browser set to block site data,
     and in Safari's private mode. A visitor whose browser refuses to remember anything
     is a visitor who sees the notice again, which is a nuisance; a page that breaks on
     it is worse. */
  function remembered() {
    try {
      return window.localStorage.getItem(STORAGE_KEY)
    } catch {
      return null
    }
  }

  function remember(decision) {
    try {
      window.localStorage.setItem(STORAGE_KEY, decision)
    } catch {
      /* Niente da fare: la scelta vale per questa visita. */
    }
  }

  /* OpenAI's own loader, minus the part that runs without being asked: the queue stub
     so nothing said between here and the SDK's arrival is lost, then the script, then
     the init. Called only from `accept`. */
  function loadPixel() {
    if (window.oaiq) return
    var queue = function () {
      queue.q.push(arguments)
    }
    queue.q = []
    window.oaiq = queue
    var script = document.createElement('script')
    script.async = true
    script.src = SDK_URL
    var first = document.getElementsByTagName('script')[0]
    if (first && first.parentNode) first.parentNode.insertBefore(script, first)
    else document.head.appendChild(script)
    window.oaiq('init', { pixelId: PIXEL_ID, debug: true })
  }

  function button(label, kind, onClick) {
    var element = document.createElement('button')
    element.type = 'button'
    element.textContent = label
    element.setAttribute('data-kind', kind)
    element.addEventListener('click', onClick)
    return element
  }

  /* Built here rather than written into both pages: with JavaScript off there is no
     tracker to consent to, so a notice in the markup would be a question about nothing.
     Text nodes only -- no innerHTML -- because that is the habit worth keeping even
     when every string is a literal. */
  function notice(onDecision) {
    var box = document.createElement('section')
    box.className = 'consent'
    box.setAttribute('role', 'region')
    box.setAttribute('aria-label', 'Cookie e misurazione')

    var text = document.createElement('p')
    text.appendChild(
      document.createTextNode('Solo un cookie di misurazione, per sapere se un annuncio funziona. '),
    )
    var link = document.createElement('a')
    link.href = '/privacy'
    link.textContent = 'Dettagli'
    text.appendChild(link)
    text.appendChild(document.createTextNode('.'))
    box.appendChild(text)

    var buttons = document.createElement('div')
    buttons.className = 'consent-actions'
    buttons.appendChild(button('No', 'no', function () { onDecision(DENIED, box) }))
    buttons.appendChild(button('Va bene', 'si', function () { onDecision(GRANTED, box) }))
    box.appendChild(buttons)
    return box
  }

  /* The notice is fixed over the bottom of the viewport, and on a phone the whole
     community page fits in one screen, so nothing scrolls out from under it: whatever it
     covers stays covered until the visitor answers (ORB-18). So while it is up the page
     is given the same room under its content. `--consent-room` on the root element is
     the distance from the notice's top edge to the bottom of the viewport, measured
     rather than guessed because the sentence wraps to one, two or three lines depending
     on the width; system.css spends it at the end of the body. Measured again when the
     notice changes size or the viewport does, and taken away with the notice. */
  var ROOM = '--consent-room'

  function room(box) {
    var root = document.documentElement
    var observer = null
    function stop() {
      if (observer) observer.disconnect()
      window.removeEventListener('resize', measure)
      root.style.removeProperty(ROOM)
    }
    function measure() {
      /* Gone some other way than a click: no room for what is not there. */
      if (!box.isConnected) return stop()
      var covered = box.offsetHeight ? window.innerHeight - box.getBoundingClientRect().top : 0
      root.style.setProperty(ROOM, Math.max(0, Math.ceil(covered)) + 'px')
    }
    if (typeof ResizeObserver === 'function') {
      observer = new ResizeObserver(measure)
      observer.observe(box)
    }
    window.addEventListener('resize', measure)
    measure()
    return stop
  }

  function decide(decision, box) {
    remember(decision)
    if (decision === GRANTED) loadPixel()
    if (box && box.parentNode) box.parentNode.removeChild(box)
  }

  function start() {
    var decision = remembered()
    if (decision === GRANTED) return loadPixel()
    /* A refusal is final until the visitor clears their own storage: no pixel, and no
       second ask. */
    if (decision === DENIED) return
    /* The room is released by the same click that removes the notice, here, so that a
       second start() cannot orphan the first notice's observer and `decide` keeps no
       state of its own. */
    var stop = null
    var box = notice(function (decision, clicked) {
      if (stop) stop()
      decide(decision, clicked)
    })
    document.body.appendChild(box)
    stop = room(box)
  }

  window.__consent = { start: start, decide: decide, STORAGE_KEY: STORAGE_KEY }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start)
  } else {
    start()
  }
})()
