/** The prompts a person copies into the assistant (ORB-182): one per step, honest about
 *  what the MCP can and cannot do. */
import { describe, expect, it } from 'vitest'
import { INTRO_PROMPT, STEP_PROMPTS } from './prompts'

describe('the ready prompts', () => {
  it('cover every step and leave the values to fill in marked', () => {
    for (const id of ['fiscali', 'cliente', 'lavoro', 'documento'] as const) {
      expect(STEP_PROMPTS[id]).toContain('«')
      expect(STEP_PROMPTS[id].length).toBeGreaterThan(80)
    }
  })

  it('never promise the assistant will set the emitter, which the MCP cannot do', () => {
    // The emitter's identity is a deliberate exclusion of the agent surface: the prompt
    // asks for the fiscal profile and names Impostazioni → Emittente as the person's job.
    expect(STEP_PROMPTS.fiscali).toContain('profilo fiscale')
    expect(STEP_PROMPTS.fiscali).toContain('Impostazioni → Emittente')
    expect(STEP_PROMPTS.fiscali).toMatch(/non la puoi fare tu/)
  })

  it('ask for a preview and a confirmation before anything is written or generated', () => {
    expect(INTRO_PROMPT).toMatch(/aspetta il mio ok/)
    expect(STEP_PROMPTS.fiscali).toMatch(/chiedimi conferma/)
    expect(STEP_PROMPTS.documento).toMatch(/anteprima/)
    expect(STEP_PROMPTS.cliente).toMatch(/non inventare/)
  })
})
