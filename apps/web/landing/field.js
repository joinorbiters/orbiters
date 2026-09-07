/* The field of tiles, shared by the landing and by Orbiters.
 *
 * A classic script, not a module: the page scripts that use it (`landing.js`,
 * `orbiters.js`) stay self-contained IIFEs their tests can load with `new Function`,
 * and this one only has to run first, which document order guarantees. Colours are
 * read from the CSS custom properties the palette plugin injects, so there is no
 * second copy of the palette in JavaScript. Nothing here is required for the page:
 * without it the grid is still there and the boxes still read.
 */
;(function () {
  var reduced =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  function token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  }

  /* --- Value noise on an integer lattice. Cheap, deterministic, and enough: the
     tiles only need to clump, not to look like terrain. */
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

  /* The default band: a diagonal streak from the lower left to the upper right,
     thinning out towards the corners so the page still reads as a page. `u`, `v`
     are the cell's position in [0, 1]. */
  function diagonal(u, v) {
    return 1 - Math.abs((u + v - 1) * 1.6)
  }

  /**
   * Paints `canvas` with tiles. `options.cell` is the tile size in CSS pixels,
   * `options.band(u, v)` says how dense the field is at a point (0 = empty),
   * `options.animate` drifts the field slowly unless the reader asked for less
   * motion, `options.seed` picks a different arrangement.
   */
  function mount(canvas, options) {
    var ctx = canvas.getContext('2d')
    if (!ctx) return
    options = options || {}
    var colours = [
      token('--color-prussian-blue'),
      token('--color-royal-gold'),
      token('--color-charcoal-blue'),
      token('--color-watermelon'),
    ]
    var cell = options.cell || 16
    var band = options.band || diagonal
    var seed = options.seed || 0
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
          var density = band(x / cols, y / rows)
          if (density <= 0) continue
          var coarse = noise(x * 0.07 + t + seed, y * 0.07)
          var fine = noise(x * 0.45 - t * 2 - seed, y * 0.45 + t)
          var v = (coarse * 0.6 + fine * 0.4) * density * 1.4
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

    if (!options.animate || reduced) return
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

  window.__pigroField = { noise: noise, mount: mount, diagonal: diagonal }
})()
