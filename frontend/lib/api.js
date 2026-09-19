// Minimal API client for the static UI (mirrors Spec §45 + §57E).
export const API = 'http://localhost:8000';
export async function canonicalBuild(domain = 'research_grant') {
  return (await fetch(`${API}/demo/canonical?domain=${domain}`)).json();
}
