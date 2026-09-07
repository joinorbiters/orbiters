/* Orbiters: the field of tiles, and the one form.
 *
 * The page is complete without this file: the grid is CSS, the box is HTML. What is
 * added here is the drifting field on the canvas -- painted by the shared field.js,
 * loaded before this script -- and the fetch behind the button.
 */
;(function () {
  var doc = document

  function field(canvas) {
    var shared = window.__pigroField
    if (!shared) return
    var cell = parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue('--orb-cell'),
    )
    shared.mount(canvas, { cell: cell || 16, animate: true })
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

  window.__orbiters = { start: start }
  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', start)
  } else {
    start()
  }
})()
