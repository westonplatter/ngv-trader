// Capture a screenshot of a running frontend route, for demo-data PR images.
//
// Usage:
//   node scripts/screenshot.mjs <path> <out.png> [width] [height]
//
// Examples (Vite dev server running on :5173, see `task frontend`):
//   node scripts/screenshot.mjs "/positions?demo=1" ../docs/screenshots/positions-demo.png
//   node scripts/screenshot.mjs "/strategies?demo=1&trade_group_id=103" out.png 1600 900
//
// Always pass `?demo=1` so the page renders the static demo fixtures
// (frontend/src/lib/demoData.ts) with no backend required.
//
// Environment notes (Claude Code on the web):
//   - Playwright's browser CDN is blocked by the egress policy, so DO NOT run
//     `playwright install`. A compatible Chromium is preinstalled.
//   - This script auto-detects it via $PW_CHROMIUM, then $PLAYWRIGHT_BROWSERS_PATH,
//     then the default /opt/pw-browsers location.
//   - playwright-core is resolved from the local node_modules; if missing, it is
//     also resolved from the Bun global cache.

import { existsSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(import.meta.url);

const [, , routePath, outPath, widthArg, heightArg] = process.argv;
if (!routePath || !outPath) {
  console.error(
    "usage: node scripts/screenshot.mjs <path> <out.png> [width] [height]",
  );
  process.exit(1);
}

const baseUrl = process.env.SCREENSHOT_BASE_URL ?? "http://localhost:5173";
const width = Number(widthArg ?? 2240);
const height = Number(heightArg ?? 900);

function resolveChromium() {
  if (process.env.PW_CHROMIUM && existsSync(process.env.PW_CHROMIUM)) {
    return process.env.PW_CHROMIUM;
  }
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH ?? "/opt/pw-browsers";
  if (!existsSync(root)) return null;
  for (const dir of readdirSync(root)) {
    if (!dir.startsWith("chromium-")) continue;
    const candidate = join(root, dir, "chrome-linux", "chrome");
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

function resolvePlaywright() {
  try {
    return require("playwright-core");
  } catch {
    // Fall back to the Bun global install cache.
    const cacheRoot = join(process.env.HOME ?? "/root", ".bun/install/cache");
    if (existsSync(cacheRoot)) {
      const entry = readdirSync(cacheRoot).find((d) =>
        d.startsWith("playwright-core@"),
      );
      if (entry) return require(join(cacheRoot, entry, "index.js"));
    }
    throw new Error(
      "playwright-core not found. Install it or set it up in the Bun cache.",
    );
  }
}

const executablePath = resolveChromium();
if (!executablePath) {
  console.error(
    "No preinstalled Chromium found. Set $PW_CHROMIUM to the chrome binary.",
  );
  process.exit(1);
}

const { chromium } = resolvePlaywright();

const browser = await chromium.launch({
  executablePath,
  args: ["--no-sandbox"],
});
try {
  const page = await browser.newPage({
    viewport: { width, height },
    deviceScaleFactor: 2,
  });
  const url = `${baseUrl}${routePath}`;
  await page.goto(url, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.screenshot({ path: outPath, fullPage: true });
  console.log(`saved ${outPath} (${url})`);
} finally {
  await browser.close();
}
