// Optional browser acceptance test. Requires Playwright and the Python pets extra.
import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, writeFile, rename, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const run = promisify(execFile);
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const python = process.env.MX_TEST_PYTHON || "python3.15";
const module = process.env.MX_PLAYWRIGHT_MODULE;
const { chromium } = await import(module ? pathToFileURL(module).href : "playwright");
const screenshots = join(root, "test-results/settings-browser");

test("settings app browser acceptance", { timeout: 120000 }, async t => {
  const state = await mkdtemp(join(tmpdir(), "mx-settings-browser-"));
  const command = [join(root, "bridge.py"), "--state-dir", state, "settings"];
  let browser;
  const saved = async () => JSON.parse(await readFile(join(state, "display.json"), "utf8"));
  const savedTheme = async () => JSON.parse(await readFile(join(state, "theme.json"), "utf8"));
  async function externalChange(changes) {
    const path = join(state, "display.json");
    await writeFile(path + ".test-tmp", JSON.stringify({ ...await saved(), ...changes }));
    await rename(path + ".test-tmp", path);
  }
  try {
    const fixture = JSON.parse((await run(python, [join(root, "tests/settings_fixture.py"), state])).stdout);
    const { stdout } = await run(python, [...command, "--no-open"]);
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1320, height: 1100 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors = [], csp = [];
    page.on("pageerror", e => errors.push(e.message));
    page.on("console", message => { if (message.text().includes("Content Security Policy")) csp.push(message.text()); });
    await page.goto(stdout.trim(), { waitUntil: "domcontentloaded" });
    await page.locator("#app").waitFor({ state: "visible" });
    await mkdir(screenshots, { recursive: true });
    const tab = name => page.locator(`[data-tab="${name}"]`).click();
    const save = async () => {
      await page.locator("#save").click();
      await page.waitForFunction(() => document.querySelector("#save-state").textContent === "Up to date");
    };
    await t.test("loads installed sprites, strips token from URL, and pages beyond nine chats", async () => {
      await page.waitForFunction(() => [...document.querySelectorAll("#preview-grid img")].some(img => img.naturalWidth > 0));
      assert.equal(new URL(page.url()).hash, "");
      assert.equal(await page.locator("#preview-grid .key").count(), 9);
      assert.equal(await page.locator("#page-number").textContent(), "1 / 2");
      await page.locator("#next-page").click();
      assert.equal(await page.locator("#page-number").textContent(), "2 / 2");
      await page.locator("#chat-view").selectOption("recent");
      assert.equal(await page.locator("#page-number").textContent(), "1 / 1");
      await save();
      assert.equal((await saved()).chat_view, "recent");
    });
    await t.test("caption and fps controls save while preserving rules and unknown settings", async () => {
      await page.locator("#show_status").uncheck();
      await page.locator("#fps").fill("8");
      await save();
      const value = await saved();
      assert.equal(value.fps, 8);
      assert.equal(value.show_status, false);
      assert.equal(value.pet_rules[0].pet, fixture.remote);
      assert.deepEqual(value.future_setting, { preserve: true });
      assert.equal(await page.locator("#preview-grid .status").count(), 0);
    });
    await t.test("previews and saves dark appearance without changing display settings", async () => {
      const before = await readFile(join(state, "display.json"), "utf8");
      await tab("theme");
      await page.screenshot({ path: join(screenshots, "theme-light.png"), fullPage: true });
      await page.locator("#theme-mode").selectOption("dark");
      await page.locator('[data-palette="slate"]').click();
      assert.equal(await page.locator("html").getAttribute("data-scheme"), "dark");
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--page").trim()), "#181e28");
      await save();
      assert.equal((await savedTheme()).mode, "dark");
      assert.equal((await savedTheme()).palette, "slate");
      assert.equal(await readFile(join(state, "display.json"), "utf8"), before);
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.locator("#app").waitFor({ state: "visible" });
      assert.equal(await page.locator("html").getAttribute("data-scheme"), "dark");
      await tab("theme");
      await page.screenshot({ path: join(screenshots, "theme-dark.png"), fullPage: true });
    });
    await t.test("custom colours preview immediately, validate hex input, and persist", async () => {
      await page.locator("#theme-mode").selectOption("light");
      await page.locator("#customize-theme").click();
      await page.locator("#theme-accent-hex").fill("#5c37a6");
      await page.locator("#theme-background-hex").fill("#f4effa");
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()), "#5c37a6");
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor), "rgb(244, 239, 250)");
      assert.deepEqual(await page.locator('[data-palette="custom"]').evaluate(choice =>
        ["accent", "background"].map(name => choice.style.getPropertyValue(`--swatch-${name}`))),
      ["#5c37a6", "#f4effa"]);
      await page.locator("#theme-accent-hex").fill("#bad");
      assert.equal(await page.locator("#save").isDisabled(), true);
      assert.equal(await page.locator("#theme-color-error").isVisible(), true);
      await page.locator("#theme-accent-hex").fill("#5c37a6");
      await save();
      const stored = await savedTheme();
      assert.equal(stored.palette, "custom");
      assert.deepEqual(stored.colors.light, { background: "#f4effa", accent: "#5c37a6" });
      assert.equal(stored.colors.dark.background, "#181e28");
      await page.screenshot({ path: join(screenshots, "theme-custom.png"), fullPage: true });
    });
    await t.test("system appearance follows live operating-system changes", async () => {
      await page.locator("#theme-mode").selectOption("system");
      await save();
      await page.emulateMedia({ colorScheme: "dark" });
      await page.waitForFunction(() => document.documentElement.dataset.scheme === "dark");
      assert.equal(await page.locator("#custom-theme-title").textContent(), "Custom dark colours");
      await page.emulateMedia({ colorScheme: "light" });
      await page.waitForFunction(() => document.documentElement.dataset.scheme === "light");
      assert.equal((await savedTheme()).mode, "system");
      assert.equal(await page.locator("#save").isDisabled(), true);
    });
    await t.test("theme file edits hot reload across windows and preserve a dirty preview", async () => {
      const before = await readFile(join(state, "display.json"), "utf8");
      const other = await page.context().newPage();
      const writeTheme = async change => {
        const file = join(state, "theme.json");
        await writeFile(file + ".test-tmp", JSON.stringify({ ...await savedTheme(), ...change }));
        await rename(file + ".test-tmp", file);
      };
      try {
        await other.goto(stdout.trim(), { waitUntil: "domcontentloaded" });
        await other.locator("#app").waitFor({ state: "visible" });
        await writeTheme({ mode: "dark", palette: "sand" });
        await page.bringToFront();
        await page.waitForFunction(() => document.documentElement.dataset.scheme === "dark");
        await other.bringToFront();
        await other.waitForFunction(() => document.documentElement.dataset.scheme === "dark");
        await page.bringToFront();
        await page.locator("#customize-theme").click();
        await page.locator("#theme-accent-hex").fill("#c0ffff");
        await writeTheme({ mode: "light", palette: "sage" });
        await page.locator("#conflict").waitFor({ state: "visible" });
        await other.bringToFront();
        await other.waitForFunction(() => document.documentElement.dataset.scheme === "light");
        await page.bringToFront();
        assert.equal(await page.locator("#theme-accent-hex").inputValue(), "#c0ffff");
        assert.equal(await page.locator("html").getAttribute("data-scheme"), "dark");
        assert.equal(await page.locator("#save").isDisabled(), true);
        await page.locator("#reload-file").click();
        await page.locator("#conflict").waitFor({ state: "hidden" });
        assert.equal(await page.locator("html").getAttribute("data-scheme"), "light");
        assert.equal(await readFile(join(state, "display.json"), "utf8"), before);
      } finally { await other.close(); }
    });
    await t.test("recovers an invalid theme file and previews defaults before saving", async () => {
      await writeFile(join(state, "theme.json"), '{"schema_version":1,"mode":"broken"}');
      await page.locator("#theme-warning").waitFor({ state: "visible" });
      assert.equal(await page.locator("#theme-mode").isDisabled(), true);
      await page.locator("#reset-theme").click();
      assert.equal(await page.locator("#theme-mode").inputValue(), "light");
      assert.equal((await savedTheme()).mode, "broken");
      await save();
      assert.equal((await savedTheme()).mode, "light");
      await page.locator("#theme-mode").selectOption("dark");
      await page.locator("#discard").click();
      assert.equal(await page.locator("html").getAttribute("data-scheme"), "light");
    });
    await t.test("adds and reorders a local Pi pet rule", async () => {
      await tab("rules");
      await page.locator("#add-rule").click();
      const last = page.locator(".rule").last();
      await last.getByLabel("Agent client").selectOption("pi");
      await last.getByLabel("Location", { exact: true }).selectOption("local");
      await last.getByLabel("Pet", { exact: true }).selectOption(fixture.remote);
      await last.getByRole("button", { name: "Move assignment up 2" }).click();
      await save();
      const value = await saved();
      assert.equal(value.pet_rules[0].client, "pi");
      assert.equal(value.pet_rules[0].location, "local");
      assert.equal(value.pet_rules[1].location, "remote");
    });
    await t.test("renames a chat and assigns its pet using its stable identity", async () => {
      await tab("chats");
      await page.getByLabel("Display name for Local Pi", { exact: true }).fill("My Pi work");
      await page.getByLabel("Pet for Remote Pi child", { exact: true }).selectOption(fixture.local);
      await save();
      const value = await saved();
      assert.equal(value.name_overrides["chat-0"], "My Pi work");
      assert.deepEqual(value.pet_rules.at(-1), { key: "remote/desk/@client/pi/remote-child", pet: fixture.local });
    });
    await t.test("preserves a dirty draft when the file changes elsewhere", async () => {
      await tab("display");
      await page.locator("#show_name").uncheck();
      await externalChange({ fps: 6 });
      await page.locator("#conflict").waitFor({ state: "visible" });
      assert.equal(await page.locator("#show_name").isChecked(), false);
      assert.equal(await page.locator("#save").isDisabled(), true);
      await page.locator("#reload-file").click();
      await page.locator("#conflict").waitFor({ state: "hidden" });
      assert.equal(await page.locator("#show_name").isChecked(), true);
      assert.equal(await page.locator("#fps").inputValue(), "6");
    });
    await t.test("imports a pet ZIP and selects it without changing settings until saved", async () => {
      const before = await readFile(join(state, "display.json"), "utf8");
      await tab("pets");
      await page.locator("#pet-source").selectOption("file");
      await page.locator("#pet-file").setInputFiles(join(state, "new-pet.codex-pet.zip"));
      await page.locator("#import-pet").click();
      await page.waitForFunction(() => document.querySelector("#import-status").textContent.startsWith("Imported new-pet"));
      const card = page.locator(".pet-card").filter({ has: page.getByRole("heading", { name: "new-pet", exact: true }) });
      await card.getByRole("button", { name: "Use as default", exact: true }).click();
      assert.equal(await readFile(join(state, "display.json"), "utf8"), before);
      await save();
      assert.match((await saved()).pet, /^new-pet\//);
    });
    await t.test("imports from the URL form, suggests a name and keeps the current selection", async () => {
      const before = await readFile(join(state, "display.json"), "utf8");
      const archive = (await readFile(join(state, "new-pet.codex-pet.zip"))).toString("base64");
      // Stub only the remote transfer; the local importer and browser flow remain real.
      const route = async request => {
        const payload = request.request().postDataJSON();
        assert.equal(payload.url, "https://codex-pets.net/#/pets/url-pet");
        assert.equal(payload.name, "url-pet");
        const imported = await page.request.post(new URL("/api/pets/import", page.url()).href, {
          headers: request.request().headers(),
          data: { name: payload.name, filename: "fixture.zip", data: archive, layout: payload.layout },
        });
        await request.fulfill({ response: imported });
      };
      await page.route("**/api/pets/import-url", route);
      try {
        assert.equal(await page.locator("#pet-source").inputValue(), "url");
        await page.locator("#pet-url").fill("https://codex-pets.net/#/pets/url-pet");
        assert.equal(await page.locator("#pet-name").inputValue(), "url-pet");
        await page.locator("#pet-name").fill("custom-name");
        await page.locator("#pet-url").fill("https://codex-pets.net/#/pets/other");
        assert.equal(await page.locator("#pet-name").inputValue(), "custom-name");
        await page.locator("#pet-name").fill("");
        await page.locator("#pet-url").fill("https://codex-pets.net/#/pets/url-pet");
        await page.locator("#import-pet").click();
        await page.waitForFunction(() => document.querySelector("#import-status").textContent.startsWith("Imported url-pet"));
        assert.equal(await page.locator(".pet-card h3").filter({ hasText: "url-pet" }).count(), 1);
        assert.equal(await readFile(join(state, "display.json"), "utf8"), before);
      } finally { await page.unroute("**/api/pets/import-url", route); }
    });
    await t.test("shows URL download errors without clearing the link or changing settings", async () => {
      const before = await readFile(join(state, "display.json"), "utf8");
      await page.locator("#pet-url").fill("https://127.0.0.1/pet.png");
      await page.locator("#import-pet").click();
      await page.waitForFunction(() => document.querySelector("#import-status").textContent.includes("public hosts"));
      assert.equal(await page.locator("#pet-url").inputValue(), "https://127.0.0.1/pet.png");
      assert.equal(await page.locator("#import-pet").isEnabled(), true);
      assert.equal(await readFile(join(state, "display.json"), "utf8"), before);
      await page.locator("#pet-url").fill("https://codex-pets.net/#/pets/banana-cat");
    });
    await t.test("rejects a malformed config import without discarding unsaved edits", async () => {
      await tab("display");
      await page.locator("#show_client").uncheck();
      await tab("bridge");
      await page.locator("#import-config").setInputFiles({
        name: "invalid.json", mimeType: "application/json",
        buffer: Buffer.from(JSON.stringify({ schema_version: 1, pet_rules: [null] })),
      });
      await page.waitForFunction(() => document.querySelector("#notice").classList.contains("error"));
      await tab("display");
      assert.equal(await page.locator("#show_client").isChecked(), false);
      assert.equal(await page.locator("#save").isEnabled(), true);
      await page.locator("#discard").click();
    });
    await t.test("saves explicit local and remote Herdr bindings", async () => {
      await tab("bridge");
      await page.locator("#add-local-binding").click();
      const local = page.locator("#local-bindings .binding");
      await local.getByLabel("Local Herdr socket").fill("/tmp/fixture-herdr.sock");
      await local.getByLabel("Outer iTerm session UUID").fill("w2t3p1:12345678-1234-1234-1234-123456789abc");
      await page.locator("#add-remote-binding").click();
      const remote = page.locator("#remote-bindings .binding");
      await remote.getByLabel("Collector source").fill("desk");
      await remote.getByLabel("SSH alias / target").fill("desk-ssh");
      await remote.getByLabel("Outer Mac iTerm session UUID").fill("abcdef12-1234-1234-1234-123456789abc");
      await save();
      const value = JSON.parse(await readFile(join(state, "herdr-focus.json"), "utf8"));
      assert.equal(value.bindings[0].iterm_id, "12345678-1234-1234-1234-123456789abc");
      assert.equal(value.remote_bindings[0].source, "desk");
    });
    await t.test("exports settings and validates a valid import before saving", async () => {
      const downloadPromise = page.waitForEvent("download");
      await page.locator("#export-config").click();
      const download = await downloadPromise;
      assert.equal(download.suggestedFilename(), "display.json");
      const value = { ...await saved(), fps: 3 };
      await page.locator("#import-config").setInputFiles({
        name: "display.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(value)),
      });
      await page.locator("#view-display").waitFor({ state: "visible" });
      assert.equal(await page.locator("#fps").inputValue(), "3");
      assert.notEqual((await saved()).fps, 3);
      await save();
      assert.equal((await saved()).fps, 3);
    });
    await t.test("has a usable narrow layout and produces screenshots without script or CSP errors", async () => {
      await mkdir(screenshots, { recursive: true });
      await page.locator("#preview-source").selectOption("sample");
      await page.screenshot({ path: join(screenshots, "display.png"), fullPage: true });
      await tab("pets");
      await page.screenshot({ path: join(screenshots, "pets.png"), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 });
      for (const section of ["display", "theme", "pets", "rules", "chats", "bridge"]) {
        await tab(section);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${section} overflows the viewport`);
      }
      await tab("theme");
      await page.locator("#theme-mode").selectOption("dark");
      await page.locator("#customize-theme").click();
      await page.screenshot({ path: join(screenshots, "theme-mobile.png"), fullPage: true });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "custom theme overflows the viewport");
      await page.locator("#discard").click();
      await tab("display");
      await page.keyboard.press("Tab");
      assert.notEqual(await page.evaluate(() => document.activeElement.tagName), "BODY");
      await page.screenshot({ path: join(screenshots, "mobile.png"), fullPage: true });
      assert.deepEqual(errors, []);
      assert.deepEqual(csp, []);
    });
  } finally {
    await browser?.close();
    await run(python, [...command, "--stop"]).catch(() => {});
    await rm(state, { recursive: true, force: true });
  }
});
