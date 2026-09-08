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
     the one the note talks about and the one that gets the focus. The same names the
     API's 422 uses in `detail[].loc`, which is how a refusal from the server points at
     a field too. */
  var FIELDS = ['nome', 'cognome', 'email', 'linkedin_url']
  var WRONG = {
    nome: 'Scrivi il tuo nome e riprova.',
    cognome: 'Scrivi il tuo cognome e riprova.',
    email: "Controlla l'indirizzo e riprova.",
    linkedin_url: 'Controlla il profilo LinkedIn e riprova.',
  }

  /* A profile, not any URL: parsed, never searched. Looking for the host as a substring
     accepted `evil.com/linkedin.com/ada` and `example.com/?u=linkedin.com/x` -- the host
     is in the path there, not in the host -- and the API then refused them with a 422
     the visitor could do nothing about. Only `https`, and the same host rule the schema
     applies, so client and server agree in both directions. */
  function isProfile(value) {
    var url
    try {
      url = new URL(value)
    } catch (error) {
      return false
    }
    var host = url.hostname.toLowerCase()
    return url.protocol === 'https:' && (host === 'linkedin.com' || /\.linkedin\.com$/.test(host))
  }

  /* Which field a 422 is about. `detail[].loc` is `["body", "<campo>"]`; anything the
     form does not own (a `utm_` key, an empty body) falls back to the address, which is
     the one field a visitor can always usefully re-read. */
  function blame(body) {
    var errors = (body && body.detail) || []
    for (var i = 0; i < errors.length; i += 1) {
      var loc = errors[i].loc || []
      var name = loc[loc.length - 1]
      if (FIELDS.indexOf(name) >= 0) return name
    }
    return 'email'
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
      if (value.nome === '') return refuse(inputs.nome, WRONG.nome)
      if (value.cognome === '') return refuse(inputs.cognome, WRONG.cognome)
      if (!inputs.email.checkValidity() || value.email.indexOf('@') < 1) {
        return refuse(inputs.email, WRONG.email)
      }
      if (value.linkedin_url !== '' && !isProfile(value.linkedin_url)) {
        return refuse(inputs.linkedin_url, WRONG.linkedin_url)
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
            /* The API refused a field. Blaming the address on every 422 -- which is what
               this did -- marked a perfectly good address as wrong and left the real
               culprit unmarked, with no way to submit. */
            return response
              .json()
              .catch(function () {
                return null
              })
              .then(function (body) {
                var name = blame(body)
                refuse(inputs[name], WRONG[name])
              })
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
