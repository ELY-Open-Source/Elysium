/**
 * Drives the built site (run `pnpm preview` first) at desktop and phone size through every beat.
 * Usage: node scripts/check.mjs --out <dir> [--url http://localhost:4173]
 * Fails on any console error or page error, on a blank scene, on a missing install command, when
 * pointing at a person shows no memory card, and if reduced motion still scrubs instead of settling.
 */
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(name);
  if (i === -1) return fallback;
  if (!args[i + 1]) throw new Error(`${name} needs a value`);
  return args[i + 1];
};
const out = arg('--out');
if (!out) throw new Error('usage: node scripts/check.mjs --out <dir> [--url http://localhost:4173]');
const url = arg('--url', 'http://localhost:4173/');
mkdirSync(out, { recursive: true });

const INSTALL_UNIX = 'curl -fsSL https://raw.githubusercontent.com/ELY-Open-Source/Elysian/main/install.sh | bash';
const INSTALL_WIN = 'irm https://raw.githubusercontent.com/ELY-Open-Source/Elysian/main/install.ps1 | iex';
const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900, isMobile: false },
  { name: 'phone', width: 390, height: 844, isMobile: true },
];
const failures = [];
const fail = (msg) => {
  failures.push(msg);
  console.error(`FAIL ${msg}`);
};

function watch(page, label) {
  page.on('console', (m) => {
    if (m.type() === 'error') fail(`${label}: console error: ${m.text()}`);
  });
  page.on('pageerror', (e) => fail(`${label}: page error: ${e.message}`));
}

async function frameTime(page) {
  return Number(await page.locator('#world').getAttribute('data-t'));
}

/** Scrolls to a point inside a beat (0 = its start, 1 = its settled frame) and waits until the scene has drawn it. */
async function settle(page, section, at = 1) {
  const start = Number(await section.getAttribute('data-start'));
  const end = Number(await section.getAttribute('data-settle'));
  const fraction = start + (end - start) * at;
  await page.evaluate((f) => window.scrollTo(0, f * (document.documentElement.scrollHeight - innerHeight)), fraction);
  const cue = section.locator('.cue');
  await cue.waitFor({ state: 'visible' });
  await page.waitForFunction((cueEl) => cueEl.classList.contains('on'), await cue.elementHandle(), { timeout: 10_000 });
  let last = -1;
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(120);
    const t = await frameTime(page);
    if (t === last) return t;
    last = t;
  }
  throw new Error('the scene never settled after scrolling');
}

/** Sweeps the pointer over the scene until a person's memory card shows, as a visitor would find it. */
async function pointAtSomeone(page, vp) {
  for (let y = 40; y < vp.height * 0.7; y += 18) {
    for (let x = 20; x < vp.width; x += 18) {
      await page.mouse.move(x, y);
      if (await page.locator('#memory-card').isVisible()) return (await page.locator('#memory-card').textContent()) ?? '';
    }
  }
  return null;
}

/** A blank ground compresses to a few KB; a drawn scene with floor type and people does not. */
async function sceneDrawn(page, label, vp) {
  const png = await page.screenshot({ clip: { x: 0, y: 0, width: vp.width, height: Math.round(vp.height * 0.45) } });
  if (png.length < 12_000) fail(`${label}: the scene looks blank (${png.length} bytes in the top band)`);
}

async function journey(browser, vp) {
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.isMobile, hasTouch: vp.isMobile, deviceScaleFactor: vp.isMobile ? 3 : 1 });
  const page = await context.newPage();
  watch(page, vp.name);
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.documentElement.classList.contains('scene'));
  await page.waitForTimeout(4200);
  await page.screenshot({ path: join(out, `${vp.name}-00-intro.png`) });
  const sections = await page.locator('[data-beat]').all();
  if (sections.length !== 7) fail(`${vp.name}: expected 7 beats, found ${sections.length}`);
  let i = 1;
  for (const section of sections) {
    const id = await section.getAttribute('data-beat');
    const n = String(i).padStart(2, '0');
    await settle(page, section, 0.55);
    await page.screenshot({ path: join(out, `${vp.name}-${n}-${id}-mid.png`) });
    const t = await settle(page, section);
    await page.screenshot({ path: join(out, `${vp.name}-${n}-${id}.png`) });
    if (id === 'referral' && !vp.isMobile) {
      const card = await pointAtSomeone(page, vp);
      if (!card || !/archive key|memory of the key/.test(card)) fail(`${vp.name}: pointing at the couple shows no memory card (${card})`);
      else await page.screenshot({ path: join(out, `${vp.name}-${n}-${id}-card.png`) });
      await page.mouse.move(1, 1);
    }
    await sceneDrawn(page, `${vp.name} ${id} (t=${t})`, vp);
    i++;
  }
  const widest = await page.evaluate(() => document.documentElement.scrollWidth);
  if (widest > vp.width) fail(`${vp.name}: page scrolls sideways (${widest}px wide)`);
  const unix = (await page.locator('#install-unix').textContent())?.trim();
  const win = (await page.locator('#install-win').textContent())?.trim();
  if (unix !== INSTALL_UNIX) fail(`${vp.name}: install command is "${unix}"`);
  if (win !== INSTALL_WIN) fail(`${vp.name}: Windows install command is "${win}"`);
  await context.close();
}

async function reducedMotion(browser) {
  const vp = VIEWPORTS[0];
  const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, reducedMotion: 'reduce' });
  const page = await context.newPage();
  watch(page, 'reduced-motion');
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.documentElement.classList.contains('scene'));
  const first = await frameTime(page);
  await page.waitForTimeout(800);
  if ((await frameTime(page)) !== first) fail('reduced-motion: the intro still animates');
  const section = page.locator('[data-beat="cost"]');
  const fraction = Number(await section.getAttribute('data-settle'));
  for (const f of [fraction - 0.01, fraction - 0.005]) {
    await page.evaluate((v) => window.scrollTo(0, v * (document.documentElement.scrollHeight - innerHeight)), f);
    await page.waitForTimeout(300);
  }
  const a = await frameTime(page);
  await page.evaluate((v) => window.scrollTo(0, v * (document.documentElement.scrollHeight - innerHeight)), fraction - 0.03);
  await page.waitForTimeout(300);
  if ((await frameTime(page)) !== a) fail('reduced-motion: scrolling inside a beat still scrubs the scene');
  await page.screenshot({ path: join(out, 'reduced-motion-cost.png') });
  await sceneDrawn(page, 'reduced-motion cost', vp);
  await context.close();
}

async function withoutWebgl() {
  const browser = await chromium.launch({ channel: 'chromium', args: ['--disable-webgl', '--disable-3d-apis'] });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  watch(page, 'no-webgl');
  await page.goto(url, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.documentElement.classList.contains('flat'));
  if (!(await page.getByRole('heading', { level: 1 }).isVisible())) fail('no-webgl: the title is not readable');
  if (!(await page.locator('#install-unix').isVisible())) fail('no-webgl: the install command is not readable');
  await page.screenshot({ path: join(out, 'no-webgl.png'), timeout: 90_000 });
  await browser.close();
}

// Without a GPU a fresh browser's first WebGL context can take 80-90 s; pay it once on about:blank.
const browser = await chromium.launch({ channel: 'chromium', args: ['--enable-unsafe-swiftshader'] });
const warm = await browser.newPage();
await warm.evaluate(() => document.createElement('canvas').getContext('webgl2') !== null);
await warm.close();
for (const vp of VIEWPORTS) await journey(browser, vp);
await reducedMotion(browser);
await browser.close();
await withoutWebgl();

if (failures.length) {
  console.error(`\n${failures.length} check(s) failed`);
  process.exit(1);
}
console.log(`all checks passed; screenshots in ${out}`);
