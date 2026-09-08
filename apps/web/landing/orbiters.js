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

  /* The attribution the URL carries -- `?utm_source=linkedin&utm_medium=paid-social&
     utm_id=...` -- read once, when the page loads, so it survives however long the
     person takes to type. Only the six utm_ keys, each cut to what the API stores. An
     ad platform's macro left unexpanded (`{{AD_SET_ID}}`) is sent as the literal it
     arrived as: that is what happened, and hiding it would hide a broken campaign. */
  var UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'utm_id']
  function utmFrom(search) {
    var params = new URLSearchParams(search || '')
    var utm = null
    for (var i = 0; i < UTM_KEYS.length; i += 1) {
      var value = params.get(UTM_KEYS[i])
      if (value === null) continue
      value = value.trim().slice(0, 200)
      if (value === '') continue
      utm = utm || {}
      utm[UTM_KEYS[i]] = value
    }
    return utm
  }

  /* The four fields, in the order the form reads them: the first one that is wrong is
     the one the note talks about and the one that gets the focus. */
  var FIELDS = ['nome', 'cognome', 'email', 'linkedin_url']

  /* A profile, not any URL: the scheme is fixed and the host has to be LinkedIn's.
     A bare `linkedin.com/in/ada` and someone else's site are both refused here, so
     nobody discovers it from a 422 they cannot read. */
  function isProfile(value) {
    return value.slice(0, 8) === 'https://' && value.toLowerCase().indexOf('linkedin.com/') > 0
  }

  function signup(form, note, utm) {
    var inputs = {}
    for (var i = 0; i < FIELDS.length; i += 1) {
      inputs[FIELDS[i]] = form.querySelector('input[name="' + FIELDS[i] + '"]')
    }
    var button = form.querySelector('button')

    function say(text, tone) {
      note.textContent = text
      note.setAttribute('data-tone', tone)
    }

    function refuse(input, message) {
      input.setAttribute('aria-invalid', 'true')
      say(message, 'error')
      input.focus()
    }

    form.addEventListener('submit', function (event) {
      event.preventDefault()
      var value = {}
      for (var j = 0; j < FIELDS.length; j += 1) {
        value[FIELDS[j]] = inputs[FIELDS[j]].value.trim()
        inputs[FIELDS[j]].removeAttribute('aria-invalid')
      }
      if (value.nome === '') return refuse(inputs.nome, 'Scrivi il tuo nome e riprova.')
      if (value.cognome === '') return refuse(inputs.cognome, 'Scrivi il tuo cognome e riprova.')
      if (!inputs.email.checkValidity() || value.email.indexOf('@') < 1) {
        return refuse(inputs.email, "Controlla l'indirizzo e riprova.")
      }
      if (value.linkedin_url !== '' && !isProfile(value.linkedin_url)) {
        return refuse(inputs.linkedin_url, 'Controlla il profilo LinkedIn e riprova.')
      }
      var payload = { email: value.email, nome: value.nome, cognome: value.cognome }
      if (value.linkedin_url !== '') payload.linkedin_url = value.linkedin_url
      if (utm) payload.utm = utm
      button.disabled = true
      fetch('/api/orbiters/signups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
        .then(function (response) {
          if (response.status === 422) {
            /* Everything else on this form was checked above, so the field the API can
               still refuse is the address: `a@b` passes the checks here. */
            refuse(inputs.email, "Controlla l'indirizzo e riprova.")
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
    if (form && note) signup(form, note, utmFrom(window.location.search))
  }

  window.__orbiters = { utmFrom: utmFrom }

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', start)
  } else {
    start()
  }
})()
