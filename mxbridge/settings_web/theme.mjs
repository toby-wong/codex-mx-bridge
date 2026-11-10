export const PALETTES = {
  sage: { name: "Sage", light: { background: "#f4f3ef", accent: "#315f49" },
    dark: { background: "#171e1b", accent: "#a1ceb2" } },
  slate: { name: "Slate", light: { background: "#eef2f6", accent: "#315e96" },
    dark: { background: "#181e28", accent: "#9abff4" } },
  sand: { name: "Sand", light: { background: "#f6f0e7", accent: "#8c4c29" },
    dark: { background: "#241d18", accent: "#e9b88b" } },
};
export const DEFAULT_THEME = {
  schema_version: 1, mode: "light", palette: "sage",
  colors: { light: { ...PALETTES.sage.light }, dark: { ...PALETTES.sage.dark } },
};
export const validColor = value => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value);
export const schemeFor = (config, prefersDark) =>
  config.mode === "system" ? (prefersDark ? "dark" : "light") : config.mode;
export function colorsFor(config, scheme) {
  return (PALETTES[config.palette]?.[scheme] || config.colors?.[scheme] || DEFAULT_THEME.colors[scheme]);
}
function rgb(hex) { return hex.slice(1).match(/../g).map(value => parseInt(value, 16)); }
function mix(first, second, amount) {
  return "#" + rgb(first).map((value, index) =>
    Math.round(value + (rgb(second)[index] - value) * amount).toString(16).padStart(2, "0")).join("");
}
export function luminance(hex) {
  const linear = rgb(hex).map(value => {
    const channel = value / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  });
  return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
}
export function contrast(first, second) {
  const a = luminance(first), b = luminance(second);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}
const ink = background => contrast("#ffffff", background) > contrast("#000000", background) ? "#ffffff" : "#000000";
function readable(color, backgrounds, target = 4.5) {
  const anchor = ink(backgrounds[0]);
  for (let step = 0; step <= 100; step++) {
    const candidate = mix(color, anchor, step / 100);
    if (backgrounds.every(background => contrast(candidate, background) >= target)) return candidate;
  }
  return anchor;
}

export function themeTokens(colors) {
  const background = validColor(colors.background) ? colors.background : PALETTES.sage.light.background;
  const accent = validColor(colors.accent) ? colors.accent : PALETTES.sage.light.accent;
  const anchor = ink(background), dark = anchor === "#ffffff";
  // Derived surfaces share a readable text colour even for unusual custom backgrounds.
  const safeSurface = candidate => {
    for (let step = 0; step <= 100; step++) {
      const result = mix(candidate, background, step / 100);
      if (contrast(anchor, result) >= 4.5) return result;
    }
    return background;
  };
  const surface = safeSurface(mix(background, "#ffffff", dark ? .055 : .8));
  const rail = safeSurface(mix(background, dark ? "#000000" : surface, dark ? .2 : .15));
  const hover = safeSurface(mix(surface, anchor, .05));
  const selected = safeSurface(mix(surface, accent, dark ? .18 : .12));
  const backgrounds = [background, surface, rail, hover, selected];
  const text = readable(mix(anchor, background, .12), backgrounds);
  const muted = readable(mix(anchor, background, .42), backgrounds);
  const accentText = readable(accent, backgrounds);
  const tokens = {
    page: background, surface, rail, text, muted, accent, "on-accent": ink(accent),
    "accent-text": accentText, "accent-hover": mix(accent, ink(accent) === "#ffffff" ? "#000000" : "#ffffff", .12),
    hover, selected, line: mix(surface, text, .18), "line-soft": mix(surface, text, .09),
    "input-line": readable(mix(surface, text, .3), [surface], 3),
    "switch-off": readable(mix(surface, text, .3), [surface], 3),
    "switch-knob": ink(readable(mix(surface, text, .3), [surface], 3)),
    focus: accentText,
  };
  for (const [name, color] of Object.entries({ success: "#468b57", warning: "#b88126", danger: "#bd503b" })) {
    const panel = safeSurface(mix(surface, color, dark ? .18 : .1));
    tokens[name] = readable(color, [background, surface, panel]);
    tokens[`${name}-bg`] = panel;
    tokens[`${name}-line`] = mix(panel, tokens[name], .3);
  }
  return tokens;
}

export function applyTheme(config = DEFAULT_THEME, prefersDark = false, root = document.documentElement) {
  const scheme = schemeFor(config, prefersDark);
  const colors = colorsFor(config, scheme);
  const tokens = themeTokens(colors);
  for (const [name, value] of Object.entries(tokens)) root.style.setProperty(`--${name}`, value);
  root.dataset.scheme = scheme;
  root.style.colorScheme = ink(tokens.page) === "#ffffff" ? "dark" : "light";
  return scheme;
}
