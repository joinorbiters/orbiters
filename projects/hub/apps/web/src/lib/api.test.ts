import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, admin, applyAsFreelancer, requestPeople } from './api'

function answer(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => vi.restoreAllMocks())

describe('the api client', () => {
  it('turns a 422 into an ApiError that names the fields', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      answer(422, {
        detail: [
          { loc: ['body', 'tariffa_giornaliera'], msg: 'Serve una cifra.' },
          { loc: ['body', 'cv'], msg: 'Il CV deve essere un PDF.' },
        ],
      }),
    )
    const failure = await requestPeople(
      {
        nome_azienda: 'ACME',
        referente: 'Wile',
        email: 'w@acme.it',
        progetto: 'x',
        periodo_da: '2026-10-01',
        durata: '3 mesi',
        budget_giornaliero: '500',
      },
      {},
    ).catch((error: unknown) => error)
    expect(failure).toBeInstanceOf(ApiError)
    const apiError = failure as ApiError
    expect(apiError.status).toBe(422)
    expect(apiError.fields).toEqual(['tariffa_giornaliera', 'cv'])
    expect(apiError.message).toBe('Serve una cifra. · Il CV deve essere un PDF.')
  })

  it('has a sentence for a 429 and for an unexplained failure', async () => {
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(new Response('', { status: 429 }))
    await expect(admin.signups()).rejects.toMatchObject({ status: 429, message: /Riprova/ })
    spy.mockResolvedValueOnce(new Response('boom', { status: 500 }))
    await expect(admin.signups()).rejects.toMatchObject({ status: 500, message: /500/ })
  })

  it('sends the freelancer as multipart with the UTM and without empty optionals', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(answer(201, { ok: true }))
    const cv = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], 'cv.pdf', {
      type: 'application/pdf',
    })
    await applyAsFreelancer(
      {
        nome: 'Ada',
        cognome: 'Lovelace',
        email: 'ada@studio.it',
        linkedin_url: '',
        tariffa_giornaliera: '450',
        posizione: 'Backend developer',
        remoto: 'remoto',
        links: ['https://github.com/ada', '  '],
        cv,
      },
      { utm_source: 'linkedin' },
    )
    const [url, init] = spy.mock.calls[0]!
    expect(url).toBe('/api/hub/freelancers')
    const body = init?.body as FormData
    expect(body.get('nome')).toBe('Ada')
    expect(body.get('utm_source')).toBe('linkedin')
    expect(body.has('linkedin_url')).toBe(false)
    expect(body.getAll('links')).toEqual(['https://github.com/ada'])
    expect((body.get('cv') as File).name).toBe('cv.pdf')
  })

  it('lists the admins and creates one as JSON, with the password in the body only', async () => {
    // ORB-123: the list and the form behind «Amministratori».
    const spy = vi.spyOn(globalThis, 'fetch')
    spy.mockResolvedValueOnce(answer(200, [{ id: '1', email: 'ivan@orbiters.it', nome: 'Ivan', attivo: true, created_at: '2026-09-10T10:00:00Z' }]))
    const listed = await admin.admins()
    expect(spy.mock.calls[0]![0]).toBe('/api/hub/admins')
    expect(listed[0]!.email).toBe('ivan@orbiters.it')
    spy.mockResolvedValueOnce(answer(201, { id: '2', email: 'lorenzo@orbiters.it', nome: 'Lorenzo', attivo: true, created_at: '2026-09-10T10:01:00Z' }))
    const created = await admin.createAdmin({ email: 'lorenzo@orbiters.it', nome: 'Lorenzo', password: 'una-password-lunga' })
    const [url, init] = spy.mock.calls[1]!
    expect(url).toBe('/api/hub/admins')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(init?.body as string)).toEqual({ email: 'lorenzo@orbiters.it', nome: 'Lorenzo', password: 'una-password-lunga' })
    expect(created.nome).toBe('Lorenzo')
  })

  it('points the admin at the CV route by id', () => {
    expect(admin.cvUrl('abc')).toBe('/api/hub/freelancers/abc/cv')
  })
})
