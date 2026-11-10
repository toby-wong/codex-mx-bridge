import test from "node:test";
import assert from "node:assert/strict";
import { PALETTES, DEFAULT_THEME, schemeFor, colorsFor, contrast, themeTokens, applyTheme } from "../mxbridge/settings_web/theme.mjs";

test("system appearance selects the right palette without changing saved choices", () => {
  const theme = structuredClone(DEFAULT_THEME);
  theme.mode = "system";
  theme.palette = "custom";
  theme.colors.dark.accent = "#f0aacc";
  assert.equal(schemeFor(theme, false), "light");
  assert.equal(schemeFor(theme, true), "dark");
  assert.equal(colorsFor(theme, "dark").accent, "#f0aacc");
  assert.equal(theme.mode, "system");
  assert.equal(schemeFor({ mode: "light" }, true), "light");
  assert.equal(schemeFor({ mode: "dark" }, false), "dark");
});

test("preset and custom backgrounds keep text, links, controls and notices readable", () => {
  const backgrounds = ["#000000", "#ffffff", "#777777", "#787878", "#ff0000", "#00ff00", "#0000ff", "#ffeedd"];
  const accents = ["#ffffff", "#000000", "#777777", "#ff0000", "#00ff00", "#0000ff"];
  const variants = Object.values(PALETTES).flatMap(palette => [palette.light, palette.dark]);
  variants.push(...backgrounds.flatMap(background => accents.map(accent => ({ background, accent }))));
  for (const colors of variants) {
    const tokens = themeTokens(colors);
    for (const foreground of ["text", "muted", "accent-text"]) {
      for (const background of ["page", "surface", "rail", "hover", "selected"]) {
        assert(contrast(tokens[foreground], tokens[background]) >= 4.5, `${JSON.stringify(colors)}: ${foreground} on ${background}`);
      }
    }
    assert(contrast(tokens["on-accent"], tokens.accent) >= 4.5);
    assert(contrast(tokens["on-accent"], tokens["accent-hover"]) >= 4.5);
    assert(contrast(tokens["input-line"], tokens.surface) >= 3);
    for (const name of ["success", "warning", "danger"]) {
      assert(contrast(tokens[name], tokens[`${name}-bg`]) >= 4.5);
    }
  }
});

test("theme application sets only colour tokens and the chosen scheme", () => {
  const properties = new Map();
  const root = { style: { setProperty: (key, value) => properties.set(key, value) }, dataset: {} };
  applyTheme({ ...DEFAULT_THEME, mode: "system", palette: "slate" }, true, root);
  assert.equal(root.dataset.scheme, "dark");
  assert.equal(root.style.colorScheme, "dark");
  assert.equal(properties.get("--page"), PALETTES.slate.dark.background);
  assert([...properties.values()].every(value => /^#[0-9a-f]{6}$/i.test(value)));
  const invalid = themeTokens({ accent: "url(https://example.com)", background: "#000000;display:none" });
  assert.equal(invalid.page, PALETTES.sage.light.background);
  assert.equal(invalid.accent, PALETTES.sage.light.accent);
});
