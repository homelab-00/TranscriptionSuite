/**
 * Extract the admin auth token from a Docker log line.
 * Strips ANSI escape sequences and looks for "Admin Token: <value>".
 */
export function extractAdminTokenFromDockerLogLine(line: string): string | null {
  if (!line) return null;
  const cleanLine = line.replace(/\u001b\[[0-9;]*m/g, '');
  const match = /Admin Token:\s*([^\s]+)/i.exec(cleanLine);
  if (!match) return null;
  const token = match[1].trim();
  return token.length > 0 ? token : null;
}
