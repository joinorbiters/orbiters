/**
 * What a client needs to connect to this installation's MCP server over HTTP (ORB-170):
 * the endpoint, a name for the server, and the two forms a configuration takes.
 * Pure functions, so the dialog's tests can look at strings.
 */
export const TOKEN_PLACEHOLDER = '<token>'

/** `https://host/mcp` for the root, `https://host/<slug>/mcp` for a space. */
export function mcpEndpoint(origin: string, prefix: string): string {
  return `${origin}${prefix}/mcp`
}

/** The name the client files the server under. A space gets its slug in the name, so a
 *  person with two spaces in one client does not end up with two `pigrocrm` entries. */
export function serverName(prefix: string): string {
  const slug = prefix.replace(/^\//, '')
  return slug ? `pigrocrm-${slug}` : 'pigrocrm'
}

export function claudeCodeCommand(name: string, url: string, token: string): string {
  return `claude mcp add --transport http ${name} ${url} --header "Authorization: Bearer ${token}"`
}

export function mcpServersJson(name: string, url: string, token: string): string {
  return JSON.stringify(
    { mcpServers: { [name]: { type: 'http', url, headers: { Authorization: `Bearer ${token}` } } } },
    null,
    2,
  )
}
