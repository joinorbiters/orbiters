/** The prompts a person copies into the assistant (ORB-182): one per step, honest about
 *  what the MCP can do, which since ORB-188 includes the fiscal identity. */
import { describe, expect, it } from 'vitest'
import { INTRO_PROMPT, STEP_PROMPTS } from './prompts'

describe('the ready prompts', () => {
  it('cover every step and leave the values to fill in marked', () => {
    for (const id of ['fiscali', 'cliente', 'lavoro', 'documento'] as const) {
      expect(STEP_PROMPTS[id]).toContain('«')
      expect(STEP_PROMPTS[id].length).toBeGreaterThan(80)
    }
  })

  it('ask the assistant to set both the emitter and the fiscal profile, in one imperative voice', () => {
    // `update_emitter_profile` and `update_fiscal_profile` are on the default MCP surface
    // (ORB-188): the prompt says «imposta» and names both halves, nothing is left to type.
    expect(STEP_PROMPTS.fiscali).toMatch(/^Imposta su PigroCRM/)
    expect(STEP_PROMPTS.fiscali).toContain('Emittente:')
    expect(STEP_PROMPTS.fiscali).toContain('Profilo fiscale:')
    expect(STEP_PROMPTS.fiscali).toContain('partita IVA')
    expect(STEP_PROMPTS.fiscali).toContain('IBAN')
    expect(STEP_PROMPTS.fiscali).not.toMatch(/a mano|non la puoi fare tu|Impostazioni/)
  })

  it('ask for a preview and a confirmation before anything is written or generated', () => {
    expect(INTRO_PROMPT).toMatch(/aspetta il mio ok/)
    expect(STEP_PROMPTS.fiscali).toMatch(/chiedimi conferma/)
    expect(STEP_PROMPTS.fiscali).toMatch(/non inventare/)
    expect(STEP_PROMPTS.documento).toMatch(/anteprima/)
    expect(STEP_PROMPTS.cliente).toMatch(/non inventare/)
  })
})
