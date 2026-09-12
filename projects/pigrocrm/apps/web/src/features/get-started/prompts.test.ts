/** The prompts a person copies into the assistant (ORB-182): one per step, honest about
 *  what the MCP can and cannot do in this space. */
import { describe, expect, it } from 'vitest'
import { FISCAL_PROMPT_FULL_ACCESS, INTRO_PROMPT, promptFor, STEP_PROMPTS } from './prompts'

describe('the ready prompts', () => {
  it('cover every step and leave the values to fill in marked', () => {
    for (const id of ['fiscali', 'cliente', 'lavoro', 'documento'] as const) {
      expect(STEP_PROMPTS[id]).toContain('«')
      expect(STEP_PROMPTS[id].length).toBeGreaterThan(80)
    }
    expect(FISCAL_PROMPT_FULL_ACCESS).toContain('«')
  })

  it('never promise the assistant will set the emitter, which the MCP cannot do', () => {
    // The emitter's identity is a deliberate exclusion of the agent surface: both fiscal
    // prompts name Impostazioni → Emittente as the person's job.
    for (const prompt of [STEP_PROMPTS.fiscali, FISCAL_PROMPT_FULL_ACCESS]) {
      expect(prompt).toContain('profilo fiscale')
      expect(prompt).toContain('Impostazioni → Emittente')
      expect(prompt).toMatch(/non la puoi fare tu/)
    }
  })

  it('ask the assistant to write the fiscal profile only where the space grants it full access', () => {
    // `update_fiscal_profile` exists only with `mcp_full_access`, off by default: the
    // default prompt reads and explains, the full-access one writes the whole profile.
    expect(promptFor('fiscali', { fullAccess: false })).toMatch(/^Leggi il mio profilo fiscale/)
    expect(promptFor('fiscali', { fullAccess: false })).not.toMatch(/Imposta il mio profilo/)
    expect(promptFor('fiscali', { fullAccess: false })).toContain('Impostazioni → Fiscale')
    expect(promptFor('fiscali', { fullAccess: true })).toBe(FISCAL_PROMPT_FULL_ACCESS)
    expect(FISCAL_PROMPT_FULL_ACCESS).toMatch(/riepilogo dell’intero profilo/)
    expect(promptFor('cliente', { fullAccess: true })).toBe(STEP_PROMPTS.cliente)
  })

  it('ask for a preview and a confirmation before anything is written or generated', () => {
    expect(INTRO_PROMPT).toMatch(/aspetta il mio ok/)
    expect(FISCAL_PROMPT_FULL_ACCESS).toMatch(/chiedimi conferma/)
    expect(STEP_PROMPTS.documento).toMatch(/anteprima/)
    expect(STEP_PROMPTS.cliente).toMatch(/non inventare/)
  })
})
