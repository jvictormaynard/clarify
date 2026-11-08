import { systemPath } from '../activation-link';

export function redirectSystemPath({ path }: { path: string; initial: boolean }) {
  return systemPath(path, String(Date.now()));
}
