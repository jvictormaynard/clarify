import { test, expect } from "./settings-fixture";
import { openSettings } from "./settings-navigation";

test("computer: explicit consent, private QR, replacement, expiry, devices and stop", async ({ page }, testInfo) => {
  const rpc = (method: string, args: unknown[] = []) => page.evaluate(async request => {
    const response = await fetch("/__test_rpc", { method: "POST", body: JSON.stringify(request) });
    const reply = await response.json();
    if (reply.error) throw reply.error;
    return reply.result;
  }, { method, args });
  await openSettings(page, "Dispositivos");
  expect((await rpc("snapshot")).computerState.enabled).toBe(false);
  await page.getByRole("button", { name: "Conectar celular", exact: true }).click();
  const pairing = page.getByRole("dialog", { name: "Conectar celular", exact: true });
  expect((await rpc("snapshot")).computerState.enabled).toBe(false);
  await page.getByRole("button", { name: "Ativar acesso e gerar QR", exact: true }).click();
  const qr = page.getByRole("img", { name: "QR para parear o iPhone", exact: true });
  await expect(qr).toBeVisible();
  await qr.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("computer-pairing-fixture.png"), fullPage: true });
  const first = await qr.getAttribute("src");
  const snapshot = JSON.stringify(await rpc("snapshot"));
  expect(snapshot).not.toContain("data:image");
  expect(snapshot).not.toContain("FAKE-QR");
  await page.getByRole("button", { name: "Gerar outro QR", exact: true }).click();
  await expect(qr).toBeVisible();
  await expect(qr).not.toHaveAttribute("src", first!);
  await pairing.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(qr).toHaveCount(0);
  await expect.poll(() => rpc("getComputerPairing")).toEqual({});
  await expect(page.getByText("Para usar fora do Wi-Fi, abra Conta → Meu computador no iPhone e ative o acesso pela internet.", { exact: true })).toBeVisible();
  await expect(page.getByRole("switch", { name: "Manter acesso ao iniciar o Clarify", exact: true })).toBeHidden();
  const options = page.getByRole("button", { name: "Dispositivos e opções", exact: true });
  await options.focus();
  await expect(options).toBeFocused();
  await options.press("Enter");
  for (const width of [640, 820, 1040]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await options.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`computer-options-${width}.png`) });
  }
  await page.getByRole("switch", { name: "Manter acesso ao iniciar o Clarify", exact: true }).click();
  await expect(page.getByRole("switch", { name: "Manter acesso ao iniciar o Clarify", exact: true })).toBeChecked();
  await page.getByRole("button", { name: "Conectar celular", exact: true }).click();
  await expect(qr).toBeVisible();
  await rpc("testComputer", ["expire"]);
  await expect(qr).toHaveCount(0);
  await expect(page.getByText("Gere um novo QR para conectar o celular.", { exact: true })).toBeVisible();
  await rpc("testComputer", ["paired"]);
  await pairing.getByRole("button", { name: "Fechar", exact: true }).click();
  await expect(page.getByText("Fixture iPhone", { exact: true })).toBeVisible();
  await expect(page.getByText("1 celular pareado", { exact: true })).toBeVisible();
  await rpc("testComputer", ["internet"]);
  await expect(page.getByText("Acesso pela internet ativo.", { exact: true })).toBeVisible();
  await expect(page.getByText("Para usar fora do Wi-Fi, abra Conta → Meu computador no iPhone e ative o acesso pela internet.", { exact: true })).toBeHidden();
  await options.focus();
  await options.press("Enter");
  await expect(page.getByRole("button", { name: "Revogar acesso de Fixture iPhone", exact: true })).toBeHidden();
  const connection = page.locator("section.settings-section").filter({ has: page.getByRole("heading", { name: "Acesso pelo celular", exact: true }) });
  for (const width of [640, 820, 1040]) {
    await page.setViewportSize({ width, height: 760 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    await connection.screenshot({ path: testInfo.outputPath(`computer-connected-${width}.png`) });
  }
  await options.press("Enter");
  await page.getByRole("button", { name: "Revogar acesso de Fixture iPhone", exact: true }).click();
  await expect(page.getByText("Nenhum celular pareado.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Conectar celular", exact: true }).click();
  await rpc("testComputer", ["offline"]);
  await expect(page.getByText("O computador está offline. Pare o acesso e tente novamente.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Gerar outro QR", exact: true })).toBeDisabled();
  await pairing.getByRole("button", { name: "Fechar", exact: true }).click();
  await page.getByRole("button", { name: "Parar acesso", exact: true }).click();
  await expect(page.getByRole("button", { name: "Parar acesso", exact: true })).toHaveCount(0);
  expect((await rpc("snapshot")).computerState.durable).toBe(false);
});
