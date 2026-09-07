/* Orbiters: the field of tiles, and the one form.
 *
 * The page is complete without this file: the grid is CSS, the box is HTML. What is
 * added here is the coloured field on the canvas and the fetch behind the button.
 * Colours come from the CSS custom properties the palette plugin injects, so there is
 * no second copy of the palette in JavaScript.
 */
;(function () {
  var doc = document
  var reduced =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  function token(name) {
    return getComputedStyle(doc.documentElement).getPropertyValue(name).trim()
  }

  /* --- Value noise on an integer lattice. Cheap, deterministic, and enough:
     the tiles only need to clump, not to look like terrain. */
  function hash(x, y) {
    var n = (x * 374761393 + y * 668265263) | 0
    n = ((n ^ (n >>> 13)) * 1274126177) | 0
    return ((n ^ (n >>> 16)) >>> 0) / 4294967296
  }
  function lerp(a, b, t) {
    return a + (b - a) * t
  }
  function noise(x, y) {
    var x0 = Math.floor(x)
    var y0 = Math.floor(y)
    var fx = x - x0
    var fy = y - y0
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    return lerp(
      lerp(hash(x0, y0), hash(x0 + 1, y0), fx),
      lerp(hash(x0, y0 + 1), hash(x0 + 1, y0 + 1), fx),
      fy,
    )
  }

  function field(canvas) {
    var ctx = canvas.getContext('2d')
    if (!ctx) return
    var colours = [
      token('--color-prussian-blue'),
      token('--color-royal-gold'),
      token('--color-charcoal-blue'),
      token('--color-watermelon'),
    ]
    var cell = parseFloat(token('--orb-cell')) || 16
    var cols, rows, dpr
    var last = 0

    function size() {
      dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(canvas.clientWidth * dpr)
      canvas.height = Math.round(canvas.clientHeight * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      cols = Math.ceil(canvas.clientWidth / cell)
      rows = Math.ceil(canvas.clientHeight / cell)
    }

    function paint(t) {
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)
      for (var y = 0; y < rows; y += 1) {
        for (var x = 0; x < cols; x += 1) {
          /* A diagonal band across the middle, like a streak of weather: the corners
             stay empty so the page still reads as a page. */
          var band = 1 - Math.abs((x / cols + y / rows - 1) * 1.6)
          if (band <= 0) continue
          var coarse = noise(x * 0.07 + t, y * 0.07)
          var fine = noise(x * 0.45 - t * 2, y * 0.45 + t)
          var v = (coarse * 0.6 + fine * 0.4) * band * 1.4
          if (v < 0.36) continue
          /* Holes and specks: the fine layer punches through the blue and lets gold
             through, so the field is texture rather than continents. */
          if (fine > 0.8 && v < 0.55) continue
          var pick = v < 0.52 ? 0 : v < 0.6 ? 2 : v < 0.76 ? (fine > 0.55 ? 1 : 0) : 1
          if (v > 0.5 && hash(x, y) > 0.985) pick = 3
          ctx.fillStyle = colours[pick]
          ctx.fillRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2)
        }
      }
    }

    size()
    paint(0)
    window.addEventListener('resize', function () {
      size()
      paint(last)
    })

    if (reduced) return
    var previous = 0
    function frame(now) {
      /* Eight frames a second: the drift reads as slow weather, and a phone does
         not spend its battery on wallpaper. */
      if (now - previous > 125) {
        previous = now
        last += 0.012
        paint(last)
      }
      window.requestAnimationFrame(frame)
    }
    window.requestAnimationFrame(frame)
  }

  function signup(form, note) {
    var input = form.querySelector('input[name="email"]')
    var button = form.querySelector('button')

    function say(text, tone) {
      note.textContent = text
      note.setAttribute('data-tone', tone)
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault()
      var email = input.value.trim()
      if (!input.checkValidity() || email.indexOf('@') < 1) {
        input.setAttribute('aria-invalid', 'true')
        say("Controlla l'indirizzo e riprova.", 'error')
        input.focus()
        return
      }
      input.removeAttribute('aria-invalid')
      button.disabled = true
      fetch('/api/orbiters/signups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email }),
      })
        .then(function (response) {
          if (response.status === 422) {
            input.setAttribute('aria-invalid', 'true')
            say("Controlla l'indirizzo e riprova.", 'error')
            return
          }
          if (!response.ok) throw new Error(String(response.status))
          form.hidden = true
          say('Sei in orbita. Ti scriviamo noi.', 'done')
        })
        .catch(function () {
          say('Non siamo riusciti a salvarla. Riprova tra poco.', 'error')
        })
        .then(function () {
          button.disabled = false
        })
    })
  }

  function start() {
    var canvas = doc.getElementById('field')
    if (canvas && typeof canvas.getContext === 'function') field(canvas)
    var form = doc.getElementById('signup')
    var note = doc.getElementById('note')
    if (form && note) signup(form, note)
  }

  window.__orbiters = { start: start, noise: noise }
  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', start)
  } else {
    start()
  }
})()
