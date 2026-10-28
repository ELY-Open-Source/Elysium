import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(process.cwd(), '..');
const outputDir = process.env.ELYSIUM_UI_SMOKE_DIR ?? path.join(root, '.elysium', 'proofs');
await mkdir(outputDir, { recursive: true });

const apiBase = process.env.ELYSIUM_API ?? 'http://127.0.0.1:8765';
const uiUrl = process.env.ELYSIUM_UI_URL ?? 'http://127.0.0.1:5173/';
// Writes need the operator token since the server checks one; without it every seed is refused.
const token = process.env.ELYSIUM_AUTH_TOKEN;
if (!token) {
  throw new Error('ELYSIUM_AUTH_TOKEN is not set: the server refuses every write without one, so nothing could be seeded');
}
const authorization = { Authorization: `Bearer ${token}` };
// Mirrors PAGE_SIZE in frontend/src/components/MemoryPanel.tsx; the pager is only provable against a known page size.
const PAGE_SIZE = 12;

async function api(route, body) {
  const response = await fetch(`${apiBase}${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authorization },
    body: JSON.stringify(body ?? {}),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${route} was rejected: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function apiGet(route) {
  const response = await fetch(`${apiBase}${route}`, { headers: authorization });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(`${route} was rejected: ${JSON.stringify(payload)}`);
  }
  return payload;
}

async function seed() {
  const statements = ['the spare glasses are in the hall drawer'];
  for (let index = 1; index < 14; index += 1) {
    statements.push(`shelf position ${index} holds the ${index} box of cables`);
  }
  for (const statement of statements) {
    await api('/api/memory', { text: statement, scenario: 'home' });
  }
  const png = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
    'base64',
  );
  const imagePath = path.join(outputDir, 'wordless-cup.png');
  await writeFile(imagePath, png);
  await api('/api/ingest/path', { path: imagePath, cartridge_name: 'ui-smoke' });
  // The store, not the test, decides what kind of picture a file became.
  const page = await apiGet('/api/atoms?limit=50');
  const picture = page.atoms.find((atom) => atom.image_ref);
  if (!picture) {
    throw new Error(`ingesting ${imagePath} left no atom with a picture: ${JSON.stringify(page.atoms.map((atom) => [atom.atom_id, atom.modality]))}`);
  }
  return picture.modality;
}

const pictureModality = await seed();

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
// The console keeps the token in localStorage under elysium_token (frontend/src/api.ts), never in the bundle.
await page.addInitScript((value) => window.localStorage.setItem('elysium_token', value), token);
const consoleErrors = [];
const failedRequests = [];
page.on('pageerror', (error) => consoleErrors.push(`uncaught: ${error.message}`));
page.on('console', (message) => {
  if (message.type() === 'error' && !message.text().startsWith('Failed to load resource')) {
    consoleErrors.push(message.text());
  }
});
function routeOf(url) {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}

page.on('response', (response) => {
  if (response.status() >= 400) {
    failedRequests.push(`${response.status()} ${routeOf(response.url())}`);
  }
});
// A store that has never run the proof suite answers 404, and the panel says "pending".
const expectedFailures = ['404 /api/proof-suite/latest'];

const observed = { mount: 'unknown', adapters: 'unknown' };

async function evidence(label) {
  await page.screenshot({ path: path.join(outputDir, 'ui-failure.png'), fullPage: true }).catch(() => undefined);
  const text = await page
    .locator('.panel', { has: page.getByRole('heading', { name: 'Memory' }) })
    .first()
    .innerText()
    .catch(() => '(the memory panel is gone)');
  const served = await fetch(`${apiBase}/api/atoms?limit=5&modality=image`)
    .then((response) => response.json())
    .catch((err) => ({ error: String(err) }));
  console.error(
    `${label}\n--- memory panel ---\n${text}\n--- what the API serves ---\n${JSON.stringify(served, null, 2)}\n--- screenshot ---\n${path.join(outputDir, 'ui-failure.png')}`,
  );
}

await page.goto(uiUrl, { waitUntil: 'networkidle' });
await page.getByRole('heading', { name: 'Local VLM Context OS' }).waitFor();
await page.getByLabel('system status').getByText('Qwen/Qwen3.5-9B').waitFor();
await page.getByRole('heading', { name: 'Adapter Matrix' }).waitFor();
await page.getByRole('heading', { name: 'PRD Proof Suite' }).waitFor();
await page.getByText(/(\d+\/\d+ passed|pending)/).waitFor();

// 1. search: ask what someone knows, in a scenario.
await page.getByPlaceholder('where are the keys').fill('spare glasses');
await page.getByPlaceholder('any').nth(1).fill('home');
await page.getByRole('button', { name: 'Search', exact: true }).click();
const hit = page.locator('.atom-row', { hasText: 'spare glasses are in the hall drawer' }).first();
await hit.waitFor();
const hitText = await hit.innerText();
if (!hitText.includes('home') || !hitText.includes('wife')) {
  throw new Error(`the search row does not name who knows it and in what setting: ${hitText}`);
}

// 2. browse: page the store and look at a wordless picture.
await page.getByLabel('Modality').selectOption(pictureModality);
try {
  await page.waitForFunction(
    () => {
      const image = document.querySelector('img.thumb');
      return Boolean(image) && image.complete && image.naturalWidth > 0;
    },
    undefined,
    { timeout: 30_000 },
  );
} catch (error) {
  await evidence('the picture atom never rendered pixels in the browse list');
  throw error;
}
await page.getByLabel('Modality').selectOption('');
// Paging is proved by row identity, not row count: the search list above uses the same row class,
// so a count that "changes" can be the search hit appearing and going away.
await page.waitForFunction(
  (size) =>
    document.querySelectorAll('[data-testid="browse-list"] .atom-row').length === size,
  PAGE_SIZE,
  { timeout: 15_000 },
);
const firstIds = await page.locator('[data-testid="browse-list"] .atom-row').evaluateAll((rows) =>
  rows.map((row) => row.getAttribute('data-atom') ?? ''),
);
await page.getByTitle('Next page').click();
try {
  await page.waitForFunction((previous) => {
    const ids = Array.from(document.querySelectorAll('[data-testid="browse-list"] .atom-row')).map(
      (row) => row.getAttribute('data-atom') ?? '',
    );
    return ids.length > 0 && ids.join(',') !== previous.join(',');
  }, firstIds, { timeout: 15_000 });
} catch {
  await evidence('the next page showed the same atoms as the first');
  throw new Error('Next page did not swap the page: the pager is not paging');
}
const secondIds = await page.locator('[data-testid="browse-list"] .atom-row').evaluateAll((rows) =>
  rows.map((row) => row.getAttribute('data-atom') ?? ''),
);
const repeated = secondIds.filter((id) => firstIds.includes(id));
if (repeated.length > 0) {
  throw new Error(`the next page repeated ${repeated.length} of ${firstIds.length} atoms from the first page`);
}
const behind = await apiGet('/api/atoms?limit=1');
if (secondIds.length !== behind.total - PAGE_SIZE) {
  throw new Error(
    `the second page held ${secondIds.length} rows, expected ${behind.total - PAGE_SIZE} of ${behind.total} atoms`,
  );
}
await page.getByTitle('Previous page').click();
await page.waitForFunction(
  (expected) =>
    Array.from(document.querySelectorAll('[data-testid="browse-list"] .atom-row'))
      .map((row) => row.getAttribute('data-atom') ?? '')
      .join(',') === expected.join(','),
  firstIds,
  { timeout: 15_000 },
);

// 3. forget: remove a memory and watch it leave the store.
await page.getByPlaceholder('where are the keys').fill('spare glasses');
await page.getByRole('button', { name: 'Search', exact: true }).click();
await page.locator('.atom-row', { hasText: 'spare glasses are in the hall drawer' }).first().waitFor();
await page
  .locator('.atom-row', { hasText: 'spare glasses are in the hall drawer' })
  .first()
  .getByTitle('Forget this memory')
  .click();
await page.getByText(/forgotten: \d+ atom/).waitFor();
await page.getByPlaceholder('where are the keys').fill('spare glasses');
await page.getByRole('button', { name: 'Search', exact: true }).click();
await page.getByText(/Nothing in the store answers/).waitFor();

// 4. mount: a cartridge is a scope you mount, and the machine decides if it may.
const mountRow = page.locator('.adapter-row', { hasText: 'ui-smoke' }).first();
await mountRow.waitFor();
await mountRow.getByRole('button', { name: 'Mount', exact: true }).click();
const mountedPill = mountRow.locator('.proof-pill.passed', { hasText: 'mounted' });
const refusal = page.locator('.error-line').first();
if (await mountedPill.isVisible().catch(() => false)) {
  observed.mount = 'accepted';
  await mountRow.getByRole('button', { name: 'Unmount', exact: true }).click();
  await page.getByText(/unmount ui-smoke/).waitFor();
} else {
  await refusal.waitFor();
  observed.mount = `refused: ${(await refusal.innerText()).slice(0, 200)}`;
  const cartridges = await apiGet('/api/cartridges');
  const cartridge = cartridges.find((entry) => entry.name === 'ui-smoke');
  if (!cartridge) {
    throw new Error('the ui-smoke cartridge vanished from the store while the console was mounting it');
  }
  expectedFailures.push(`400 /api/cartridges/${cartridge.cartridge_id}/mount`);
}

// 5. adapter states: the panel says what is attached and why the rest is not.
await page.getByRole('heading', { name: 'Adapter Matrix' }).scrollIntoViewIfNeeded();
const loadStrip = page
  .locator('.panel', { has: page.getByRole('heading', { name: 'Adapter Matrix' }) })
  .first();
await loadStrip.getByText(/\d+ mounted/).waitFor();
const states = await loadStrip.locator('.layer-row').evaluateAll((rows) =>
  rows.map((row) => [
    row.querySelector('strong')?.textContent ?? '',
    (row.querySelector('small')?.textContent ?? '').trim(),
  ]),
);
if (states.length === 0) {
  await evidence('the adapter panel named no adapter kind at all');
  throw new Error('the adapter panel reported no states; the load report was empty');
}
for (const [state, reason] of states) {
  if (!/^(loaded|available|deferred|missing)$/.test(state)) {
    throw new Error(`an adapter row reported the state "${state}"`);
  }
  if (!reason) {
    throw new Error(`the adapter row "${state}" gave no reason`);
  }
}
observed.adapters = `${states.length} kinds: ${states.map(([state]) => state).join(', ')}`;

await page.screenshot({ path: path.join(outputDir, 'elysium-dashboard.png'), fullPage: true });
const status = await page.locator('.kpi-grid').innerText();
await browser.close();

const unexpected = failedRequests.filter(
  (line) => !expectedFailures.some((allowed) => line === allowed || line.startsWith(allowed)),
);
if (unexpected.length > 0 || consoleErrors.length > 0) {
  throw new Error(
    [`${unexpected.length} unexpected failed request(s): ${unexpected.join(', ')}`, ...consoleErrors].join('\n'),
  );
}

console.log(
  JSON.stringify(
    {
      screenshot: path.join(outputDir, 'elysium-dashboard.png'),
      mount: observed.mount,
      adapters: observed.adapters,
      expected_failures: expectedFailures.filter((line) => failedRequests.includes(line)),
      status,
    },
    null,
    2,
  ),
);
