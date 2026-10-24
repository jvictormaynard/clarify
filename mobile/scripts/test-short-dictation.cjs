// Explicit live acceptance, separate from isolated unit tests. The temporary
// secret supplies a Groq key and synthetic M4A clips; no key enters an artifact.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

if (process.platform !== 'darwin') throw new Error('Live mobile acceptance requires macOS.');
let payload;
try { payload = JSON.parse(process.env.CLARIFY_SHORT_DICTATION_ACCEPTANCE || '{}'); }
catch { throw new Error('Malformed live-acceptance configuration.'); }
delete process.env.CLARIFY_SHORT_DICTATION_ACCEPTANCE;
if (!payload.key || !Array.isArray(payload.clips) || payload.clips.length !== 3) {
  throw new Error('Supply temporary acceptance credentials and three synthetic clips.');
}
const root = process.cwd();
const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'clarify-short-speech-'));
try {
  const clips = payload.clips.map((clip, index) => {
    if (![500, 800, 1283].includes(clip.durationMs) || typeof clip.audio !== 'string') {
      throw new Error('Unexpected synthetic fixture metadata.');
    }
    const filename = `${index}.m4a`;
    fs.writeFileSync(path.join(fixture, filename), Buffer.from(clip.audio, 'base64'), { mode: 0o600 });
    return { filename, durationMs: clip.durationMs };
  });
  fs.writeFileSync(path.join(fixture, 'clips.json'), JSON.stringify(clips), { mode: 0o600 });
  const sources = ['GroqClient.swift', 'LocalLibrary.swift', 'Snippets.swift', 'RewritePrompt.swift', 'KeyStore.swift', 'Localization.swift',
    'SharedState.swift', 'KeyboardVocabulary.swift']
    .map((name) => path.join(root, 'modules/clarify-core/ios', name));
  const executable = path.join(fixture, 'acceptance');
  const compile = spawnSync('swiftc', ['-parse-as-library', ...sources,
    path.join(root, 'scripts/ShortDictationAcceptance.swift'), '-lsqlite3', '-o', executable], { stdio: 'inherit' });
  if (compile.status !== 0) throw new Error('Could not compile the actual mobile client.');
  const result = spawnSync(executable, [fixture], {
    encoding: 'utf8', env: { ...process.env, CLARIFY_ACCEPTANCE_GROQ_KEY: payload.key },
    timeout: 360_000,
  });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.status !== 0) throw new Error('Live short-speech acceptance failed.');
  const report = JSON.parse(result.stdout);
  const output = path.join(root, 'test-results');
  fs.mkdirSync(output, { recursive: true });
  fs.writeFileSync(path.join(output, 'short-dictation-acceptance.json'), JSON.stringify(report, null, 2));
} finally {
  fs.rmSync(fixture, { recursive: true, force: true });
}
