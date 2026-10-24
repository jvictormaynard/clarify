// Explicit live acceptance with a dedicated temporary account and synthetic audio.
// The parent workflow supplies a short-lived secret; no fixture enters an artifact.
const { Buffer } = require('node:buffer');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
if (process.platform !== 'darwin') throw new Error('Native snippets acceptance requires macOS.');
let payload;
try { payload = JSON.parse(process.env.CLARIFY_SNIPPETS_ACCEPTANCE || '{}'); }
catch { throw new Error('Malformed snippets acceptance configuration.'); }
delete process.env.CLARIFY_SNIPPETS_ACCEPTANCE;
if (typeof payload.endpoint !== 'string' || typeof payload.userID !== 'string' || typeof payload.token !== 'string'
  || typeof payload.trigger !== 'string' || typeof payload.replacement !== 'string'
  || !Array.isArray(payload.clips) || payload.clips.length < 1 || payload.clips.length > 3) {
  throw new Error('Supply dedicated snippets acceptance credentials and synthetic clips.');
}
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-snippets-'));
try {
  const clips = payload.clips.map((clip, index) => {
    if (!['standalone', 'inline'].includes(clip.kind) || typeof clip.audio !== 'string') throw new Error('Invalid synthetic clip metadata.');
    const bytes = Buffer.from(clip.audio, 'base64');
    if (!bytes.length || bytes.length > 24 * 1024 * 1024) throw new Error('Invalid synthetic clip size.');
    const filename = `${index}.m4a`;
    fs.writeFileSync(path.join(fixture, filename), bytes, { mode: 0o600 });
    return { filename, kind: clip.kind };
  });
  const metadata = { ...payload, clips };
  const file = path.join(fixture, 'fixture.json'), report = path.join(fixture, 'report.json');
  fs.writeFileSync(file, JSON.stringify(metadata), { mode: 0o600 });
  const result = spawnSync('swift', ['test', '--package-path', 'modules/clarify-core', '--filter', 'SnippetAcceptanceTests.testLiveSnippetService'], {
    encoding: 'utf8', timeout: 720_000,
    env: { ...process.env, CLARIFY_SNIPPETS_ACCEPTANCE_FILE: file, CLARIFY_SNIPPETS_ACCEPTANCE_REPORT: report },
  });
  if (!fs.existsSync(report)) throw new Error('Native snippets acceptance did not produce a report.');
  const evidence = JSON.parse(fs.readFileSync(report, 'utf8'));
  // The Swift harness writes only a fixed safe schema. Never forward compiler,
  // XCTest, HTTP, credential or fixture output from the child process.
  const allowed = ['passed', 'guest_preserved', 'account_persisted', 'peer_isolated', 'single_pass', 'hosted_cases', 'standalone_cases', 'inline_cases', 'history_persisted', 'failure'];
  if (Object.keys(evidence).some(key => !allowed.includes(key))
    || Object.values(evidence).some(value => !['boolean', 'number'].includes(typeof value) && value !== 'live_native_acceptance_failed')) {
    throw new Error('Invalid snippets acceptance report.');
  }
  process.stdout.write(JSON.stringify(evidence) + '\n');
  const output = path.join(process.cwd(), 'test-results');
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'snippets-acceptance.json'), JSON.stringify(evidence, null, 2));
  if (result.status !== 0 || evidence.passed !== true) throw new Error('Native snippets acceptance failed.');
} finally { fs.rmSync(fixture, { recursive: true, force: true }); }
