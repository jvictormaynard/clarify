# Settings unit tests

Run these commands from `desktop/` after `npm ci`, with Node 22.21.1:

| Command | Contract |
| --- | --- |
| `npm run typecheck` | Type-check the production Settings source and the unit TypeScript files/configuration. |
| `npm run test:unit` | Run the Node unit suite. No browser installation, Python, or development server is needed. |
| `npm run test:browser` | Run the existing isolated Playwright and Python bridge suite through `scripts/test-settings.mjs`. |
| `npm run test:boot` | Run the existing production-output boot suite through the same wrapper with `--built`. Run `build` first. |
| `npm run build` | Type-check and build the production web output. |
| `npm test` | Run unit tests, then browser/bridge tests. This keeps the previous regular-suite coverage. Boot tests remain separate. |
| `npm run check` | Build, run both regular suites, then run production-output boot tests. |

Pass filters to the selected suite, for example:

```sh
node scripts/test-unit.mjs settings-hook -t "clean close"
node scripts/test-settings.mjs --grep "microphone"
```

`scripts/test-unit.mjs` creates a temporary profile and removes inherited provider
credentials before starting Vitest. It removes the profile on success or failure
and stops its owned process tree on interruption. No unit test starts Python,
opens an audio device, or calls a real provider. Tauri transport mocks reject
requests until a test installs an in-memory fixture.

Vitest resolves the actual TypeScript modules, including extensionless shared
imports. The hook suite renders the real `useSettings` hook with React DOM and
runs its real effects with fake timers. It substitutes the Tauri transport and
native-window adapter. The page suite renders the real Account and History
pages with small child-control fixtures. These fixtures expose the operation
props and events under test; real control focus and layout stay in browser and
native acceptance. The state suite imports the real bridge queue and merge code.
No test removes imports, rewrites source, or implements React hooks.

Browser scenarios use explicit typed fixture options. Test names do not select
account state, locale or provider outcomes. One fixture owns the controller,
requests and awaited process cleanup for each case. Keep rendered focus, layout,
navigation and Save-responsiveness checks in the browser. State-only regressions
belong in the existing headless cases when that boundary detects the same failure.

The npm lock records exact dependency resolution. Verify Node compatibility when
changing the test environment. See the primary
[Vitest configuration](https://vitest.dev/config/),
[module mocking](https://vitest.dev/guide/mocking/modules),
[React act](https://react.dev/reference/react/act), and
[jsdom](https://github.com/jsdom/jsdom/tree/27.4.0) documentation.
