import { test, expect } from '@playwright/test';

test('pill recovery uses the current processing animation and distinct error presentation', async ({ page }, testInfo) => {
  const targetIcon = 'data:image/svg+xml;base64,' + Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"><rect width="24" height="24" rx="5" fill="#4285f4"/><path d="M6 7h12M6 12h12M6 17h8" stroke="white" stroke-width="2"/></svg>').toString('base64');
  await page.addInitScript(({ targetIcon }) => {
    const host = window as unknown as {
      clarifyDesktop: unknown; pillState: Record<string, unknown>; pillCalls: string[];
      publishPill: (patch: Record<string, unknown>) => void;
    };
    let listener: (message: unknown) => void;
    host.pillState = { surface: 'error', status: 'Falha de conexão', feedbackVisible: true,
      feedbackTitle: 'Falha de conexão', canRetryTranscription: true, feedbackOperationId: 12,
      targetIcon, uiLanguage: 'pt', language: 'pt', busy: false, recording: false };
    host.pillCalls = [];
    host.publishPill = patch => { host.pillState = { ...host.pillState, ...patch }; listener?.({ event: 'workflow', state: host.pillState }); };
    host.clarifyDesktop = {
      subscribe(callback: typeof listener) { listener = callback; return () => {}; },
      ready: async () => { host.publishPill({}); }, window: async () => {}, onWindow: () => () => {},
      call: async (_channel: string, method: string) => {
        host.pillCalls.push(method);
        if (method === 'retryTranscription') host.publishPill({ feedbackVisible: false, transitionPending: true });
      },
    };
  }, { targetIcon });
  const publish = (patch: Record<string, unknown>) => page.evaluate(patch => {
    (window as unknown as { publishPill: (patch: Record<string, unknown>) => void }).publishPill(patch);
  }, patch);
  await page.goto('/?surface=pill');
  const pill = page.locator('.workflow-pill');
  await expect(pill).toHaveAttribute('data-feedback-problem', 'true');
  await expect(pill.locator('.pill-problem-icon')).toBeVisible();
  await expect(pill.locator('.pill-target-icon')).toHaveCount(0);
  await expect(pill.locator('.pill-feedback-label')).toHaveCSS('color', 'rgb(248, 113, 113)');
  await expect(pill.getByRole('button', { name: 'Tentar novamente', exact: true })).toBeVisible();
  await pill.screenshot({ path: testInfo.outputPath('01-problem.png'), omitBackground: true, animations: 'disabled' });
  await pill.getByRole('button', { name: 'Tentar novamente', exact: true }).click();
  await expect(pill.locator('.pill-typing')).toBeVisible();
  await expect(pill).toHaveAttribute('data-starting', 'false');
  await expect(pill.locator('.pill-problem-icon')).toHaveCount(0);
  await publish({ surface: 'processing', busy: true, transitionPending: false, canRetryTranscription: false });
  await expect(pill.locator('.pill-typing i')).toHaveCount(3);
  await expect(pill.locator('.pill-typing i').first()).toHaveCSS('animation-name', 'pill-type');
  await expect(pill.locator('.pill-target-icon')).toBeVisible();
  await pill.screenshot({ path: testInfo.outputPath('02-current-processing.png'), omitBackground: true });
  await publish({ surface: 'success', busy: false, feedbackVisible: true, canShowResult: true, recoveryResultVisible: true,
    feedbackTitle: 'Texto recuperado', result: 'Texto recuperado de teste.' });
  await expect(pill.getByRole('button', { name: 'Copiar', exact: true })).toBeVisible();
  await expect(pill.getByRole('button', { name: 'Ver resultado', exact: true })).toHaveCount(0);
  await page.clock.install();
  await page.clock.runFor(3500);
  await expect(pill).toHaveAttribute('data-feedback-problem', 'false');
  const calls = () => page.evaluate(() => (window as unknown as { pillCalls: string[] }).pillCalls);
  expect(await calls()).not.toContain('dismissFeedback');
  await pill.getByRole('button', { name: 'Copiar', exact: true }).click();
  expect(await calls()).toContain('copyResult');
  await pill.screenshot({ path: testInfo.outputPath('03-recovered.png'), omitBackground: true, animations: 'disabled' });
  await publish({ surface: 'cancelled', recoveryResultVisible: false, canShowResult: false, cancellationVisible: true, canUndoCancellation: true, feedbackTitle: 'Transcrição cancelada' });
  await expect(pill.locator('.pill-problem-icon')).toHaveCount(0);
  await expect(pill.getByRole('button', { name: 'Desfazer', exact: true })).toBeVisible();
  const beforePartial = await calls();
  await page.setViewportSize({ width: 660, height: 272 });
  await publish({ surface: 'recording', feedbackVisible: false, recording: true, recordingReady: true, cancellationVisible: false, canUndoCancellation: false, status: 'Gravando', feedbackTitle: '', liveTranscript: 'Estas palavras ainda podem mudar.', showRecordingStop: true });
  const partial = page.getByRole('status', { name: 'Transcrição ao vivo' });
  await expect(partial).toContainText('Estas palavras ainda podem mudar.');
  await page.clock.runFor(400);
  await page.clock.resume();
  await page.evaluate(() => document.fonts.ready);
  expect(await calls()).toEqual(beforePartial);
  await expect(partial).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('04-live-transcription.png'), omitBackground: true });
  await publish({ surface: 'processing', recording: false });
  await expect(partial).toHaveCount(0);
});
