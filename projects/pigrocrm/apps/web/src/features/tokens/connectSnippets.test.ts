import { describe, expect, it } from 'vitest'
import {
  TOKEN_PLACEHOLDER,
  claudeCodeCommand,
  mcpEndpoint,
  mcpServersJson,
  serverName,
} from './connectSnippets'

describe('the endpoint', () => {
  it('is the origin plus the space prefix plus /mcp', () => {
    expect(mcpEndpoint('https://pigro.example', '')).toBe('https://pigro.example/mcp')
    expect(mcpEndpoint('https://pigro.example', '/studio')).toBe('https://pigro.example/studio/mcp')
  })
})

describe('the server name', () => {
  it('is pigrocrm for the root and pigrocrm-<slug> for a space, so two spaces never collide', () => {
    expect(serverName('')).toBe('pigrocrm')
    expect(serverName('/studio')).toBe('pigrocrm-studio')
  })
})

describe('the snippets', () => {
  const url = 'https://pigro.example/studio/mcp'

  it('build the claude mcp add command with the bearer header', () => {
    expect(claudeCodeCommand('pigrocrm-studio', url, 'pgc_abc')).toBe(
      'claude mcp add --transport http pigrocrm-studio https://pigro.example/studio/mcp --header "Authorization: Bearer pgc_abc"',
    )
  })

  it('build a valid mcpServers JSON document', () => {
    const parsed = JSON.parse(mcpServersJson('pigrocrm-studio', url, 'pgc_abc'))
    expect(parsed).toEqual({
      mcpServers: {
        'pigrocrm-studio': {
          type: 'http',
          url,
          headers: { Authorization: 'Bearer pgc_abc' },
        },
      },
    })
  })

  it('carry the placeholder until a token exists', () => {
    expect(claudeCodeCommand('pigrocrm', url, TOKEN_PLACEHOLDER)).toContain('Bearer <token>')
    expect(mcpServersJson('pigrocrm', url, TOKEN_PLACEHOLDER)).toContain('Bearer <token>')
  })
})
