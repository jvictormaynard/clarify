export function activationSource(url: string): 'keyboard' | 'activity' | null {
  if (activationToken(url)) return 'keyboard';
  if (url === 'clarify://keyboard' || url === 'clarify://keyboard/') return 'keyboard';
  if (url === 'clarify://activate' || url === 'clarify://activate/') return 'activity';
  return null;
}
export function activationToken(url: string): string | null {
  const match = /^clarify:\/\/keyboard\/?\?token=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i.exec(url);
  return match?.[1] ?? null;
}

// System URLs are untrusted. Do not forward arbitrary paths to Router's decoder.
export function systemPath(path: string, request: string): string {
  if (path.length > 512) return '/';
  const source = activationSource(path);
  if (source) {
    const token = activationToken(path);
    return `/?activate=${source}&request=${encodeURIComponent(request)}${token ? `&token=${token}` : ''}`;
  }
  if (path === '/dictionary' || path === '/settings') return path;
  const route = /^clarify:\/\/(dictionary|settings)\/?$/.exec(path);
  return route ? `/${route[1]}` : '/';
}
