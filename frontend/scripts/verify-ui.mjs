import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(process.cwd(), '..');
const outputDir = process.env.ELYSIAN_UI_SMOKE_DIR ?? path.join(root, '.elysian', 'proofs');
await mkdir(outputDir, { recursive: true });

const apiBase = process.env.ELYSIAN_API ?? 'http://127.0.0.1:8765';
const uiUrl = process.env.ELYSIAN_UI_URL ?? 'http://127.0.0.1:5173/';
// Writes need the operator token since the server checks one; without it every seed is refused.
const token = process.env.ELYSIAN_AUTH_TOKEN;
if (!token) {
  throw new Error('ELYSIAN_AUTH_TOKEN is not set: the server refuses every write without one, so nothing could be seeded');
}
const authorization = { Authorization: `Bearer ${token}` };
// Mirrors PAGE_SIZE in frontend/src/components/Memory.tsx; the pager is only provable against a known page size.
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
const status = await apiGet('/api/status');

// The scene is WebGL; headless Chromium draws it only on SwiftShader, so a missing GPU cannot fail the run.
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
// The console keeps the token in localStorage under elysian_token (frontend/src/api.ts), never in the bundle.
await page.addInitScript((value) => window.localStorage.setItem('elysian_token', value), token);
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
// A store that has never run the proof suite answers 404, and the console says "not run yet".
const expectedFailures = ['404 /api/proof-suite/latest'];

const observed = { mount: 'unknown', adapters: 'unknown', supersede: 'unknown' };
const memory = page.locator('#memory');
const browseRows = memory.locator('[data-testid="browse-list"] .atom');
const searchRows = memory.locator('[data-testid="search-list"] .atom');
const tell = memory.getByRole('form', { name: 'Tell it something' });
const scene = page.getByTestId('store-scene');

async function evidence(label) {
  await page.screenshot({ path: path.join(outputDir, 'ui-failure.png'), fullPage: true }).catch(() => undefined);
  const text = await memory.innerText().catch(() => '(the memory section is gone)');
  const served = await apiGet('/api/atoms?limit=5').catch((err) => ({ error: String(err) }));
  const drawn = await scene.evaluate((node) => ({ ...node.dataset })).catch((err) => ({ error: String(err) }));
  console.error(
    `${label}\n--- memory section ---\n${text}\n--- store scene ---\n${JSON.stringify(drawn)}\n` +
      `--- what the API serves ---\n${JSON.stringify(served, null, 2)}\n--- screenshot ---\n${path.join(outputDir, 'ui-failure.png')}`,
  );
}

async function step(label, work) {
  try {
    await work();
  } catch (error) {
    await evidence(`${label}: ${error.message.split('\n')[0]}`);
    throw error;
  }
}

async function rowIds(rows) {
  return rows.evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-atom') ?? ''));
}

async function searchFor(query) {
  await memory.getByPlaceholder('where are the keys').fill(query);
  await memory.getByRole('button', { name: 'Search', exact: true }).click();
}

async function sceneLit(holder) {
  const selector = `[data-testid="store-scene"][data-lit="${holder}"][data-drawn="yes"]`;
  await page.waitForSelector(selector, { state: 'attached', timeout: 60_000 });
}

await page.goto(uiUrl, { waitUntil: 'networkidle' });
// Playwright clicks only after painted frames; this host's headless Chromium has taken 14 s to paint its first.
const paintStarted = Date.now();
const painted = await Promise.race([
  page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => resolve(true)))),
  new Promise((resolve) => setTimeout(() => resolve(false), 60_000)),
]);
if (!painted) {
  throw new Error('the headless browser drew no frame in 60 s, so no click can land; the browser is stalled, not the console');
}
console.log(`first frame painted after ${Date.now() - paintStarted} ms`);

await step('the console never showed its sections', async () => {
  await page.getByRole('heading', { name: 'Elysian', level: 1 }).waitFor();
  await page.getByLabel('system status').getByText(status.runtime.model_id).waitFor();
  await page.getByRole('heading', { name: 'Machine' }).waitFor();
  await page.getByRole('heading', { name: 'Proofs' }).waitFor();
  await page.getByTestId('suite-tally').getByText(/^(\d+\/\d+ passed|not run yet)$/).waitFor();
  await page.waitForSelector('[data-testid="store-scene"][data-drawn="yes"] canvas', { state: 'attached', timeout: 60_000 });
});

// 1. bring in: upload a wordless picture through the form, into a cartridge.
await step('the upload form did not report what it read', async () => {
  const ingest = page.locator('#ingest');
  await ingest.getByLabel('Cartridge').fill('ui-smoke');
  await ingest.getByLabel('Files').setInputFiles(imagePath);
  await ingest.getByRole('button', { name: 'Upload files', exact: true }).click();
  await ingest.getByText(/^Read 1 source, 1 atom, .* into ui_smoke/).waitFor();
});
// The store, not the test, decides what kind of picture a file became.
const stored = await apiGet('/api/atoms?limit=50');
const picture = stored.atoms.find((atom) => atom.image_ref);
if (!picture) {
  throw new Error(`uploading ${imagePath} left no atom with a picture: ${JSON.stringify(stored.atoms.map((atom) => [atom.atom_id, atom.modality]))}`);
}

// 2. search: ask what someone knows, in a scenario; the holder's shelf lights in the store.
await step('the search row or the lit shelf never appeared', async () => {
  await memory.getByLabel('Scenario').fill('home');
  await searchFor('spare glasses');
  const hit = searchRows.filter({ hasText: 'spare glasses are in the hall drawer' }).first();
  await hit.waitFor();
  const hitText = await hit.innerText();
  if (!hitText.includes('home') || !hitText.includes('wife')) {
    throw new Error(`the search row does not name who knows it and in what setting: ${hitText}`);
  }
  if (!(await searchRows.first().evaluate((node) => node.classList.contains('match')))) {
    throw new Error('the best hit is not marked as the matching memory');
  }
  await sceneLit('wife');
});

// 3. browse: page the store and look at a wordless picture.
await step('the picture atom never rendered pixels in the browse list', async () => {
  await memory.getByLabel('Modality').selectOption(picture.modality);
  await page.waitForFunction(
    () => {
      const image = document.querySelector('[data-testid="browse-list"] img.thumb');
      return Boolean(image) && image.complete && image.naturalWidth > 0;
    },
    undefined,
    { timeout: 30_000 },
  );
  await memory.getByLabel('Modality').selectOption('');
});
// Paging is proved by row identity, not row count: a count that "changes" can be a stale page.
await page.waitForFunction(
  (size) => document.querySelectorAll('#memory [data-testid="browse-list"] .atom').length === size,
  PAGE_SIZE,
  { timeout: 15_000 },
);
const firstIds = await rowIds(browseRows);
await memory.getByTitle('Next page').click();
try {
  await page.waitForFunction((previous) => {
    const ids = Array.from(document.querySelectorAll('#memory [data-testid="browse-list"] .atom')).map(
      (row) => row.getAttribute('data-atom') ?? '',
    );
    return ids.length > 0 && ids.join(',') !== previous.join(',');
  }, firstIds, { timeout: 15_000 });
} catch {
  await evidence('the next page showed the same atoms as the first');
  throw new Error('Next page did not swap the page: the pager is not paging');
}
const secondIds = await rowIds(browseRows);
const repeated = secondIds.filter((id) => firstIds.includes(id));
if (repeated.length > 0) {
  throw new Error(`the next page repeated ${repeated.length} of ${firstIds.length} atoms from the first page`);
}
const behind = await apiGet('/api/atoms?limit=1');
if (secondIds.length !== behind.total - PAGE_SIZE) {
  throw new Error(`the second page held ${secondIds.length} rows, expected ${behind.total - PAGE_SIZE} of ${behind.total} atoms`);
}
await memory.getByTitle('Previous page').click();
await page.waitForFunction(
  (expected) =>
    Array.from(document.querySelectorAll('#memory [data-testid="browse-list"] .atom'))
      .map((row) => row.getAttribute('data-atom') ?? '')
      .join(',') === expected.join(','),
  firstIds,
  { timeout: 15_000 },
);

// 4. remember, then replace: the new memory supersedes the old one, which leaves the shelf.
const kept = 'the umbrella hangs behind the kitchen door';
const replacement = 'the umbrella hangs in the hall closet';
await step('remembering through the form did not reach the shelf', async () => {
  await tell.getByPlaceholder('the spare glasses are in the hall drawer').fill(kept);
  await tell.getByRole('button', { name: 'Remember', exact: true }).click();
  await memory.getByText(`Kept: ${kept}`).waitFor();
  await browseRows.filter({ hasText: kept }).first().waitFor();
});
const oldId = await browseRows.filter({ hasText: kept }).first().getAttribute('data-atom');
await step('replacing a memory did not supersede it', async () => {
  await browseRows.filter({ hasText: kept }).first().getByTitle('Replace this memory').click();
  await memory.getByText(`Was: “${kept}”`).waitFor();
  await tell.getByPlaceholder('the spare glasses are in the hall drawer').fill(replacement);
  await tell.getByRole('button', { name: 'Replace', exact: true }).click();
  await memory.getByText(`Replaced: ${replacement}`).waitFor();
  await browseRows.filter({ hasText: replacement }).first().waitFor();
  await browseRows.filter({ hasText: kept }).waitFor({ state: 'detached' });
});
const shelf = await apiGet('/api/atoms?limit=50');
const successor = shelf.atoms.find((atom) => atom.text === replacement);
if (!successor || !successor.supersedes.includes(oldId) || shelf.atoms.some((atom) => atom.atom_id === oldId)) {
  throw new Error(`the store did not record ${successor?.atom_id ?? 'a successor'} as replacing ${oldId}: ${JSON.stringify(successor)}`);
}
observed.supersede = `${successor.atom_id} supersedes ${oldId}`;

// 5. forget: remove a memory and watch it leave the store.
await step('forgetting did not remove the memory', async () => {
  await searchFor('spare glasses');
  const hit = searchRows.filter({ hasText: 'spare glasses are in the hall drawer' }).first();
  await hit.waitFor();
  await hit.getByTitle('Forget this memory').click();
  await memory.getByText(/^Forgotten: \d+ atom/).waitFor();
  await searchFor('spare glasses');
  await memory.getByText(/Nothing in the store answers/).waitFor();
});

// 6. ask: the model is stubbed at the browser, so this proves what the console shows, not the server's answer.
const ask = page.locator('#ask');
await step('a refused question was not shown', async () => {
  await page.route('**/api/chat', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'no model is served here' }) }),
  );
  await ask.getByLabel('Question').fill('where is the umbrella');
  await ask.getByRole('button', { name: 'Ask', exact: true }).click();
  await ask.getByRole('alert').getByText('503 /api/chat: no model is served here').waitFor();
});
expectedFailures.push('503 /api/chat');
await step('a compiled answer and its evidence were not shown', async () => {
  const evidenceHits = (await api('/api/search', { query: 'umbrella', top_k: 3 })).hits;
  await page.unroute('**/api/chat');
  await page.route('**/api/chat', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        answer: 'It hangs in the hall closet.',
        citations: evidenceHits.map((hit) => hit.atom.atom_id),
        context: { hits: evidenceHits, token_equivalent: 0, cache_trace_id: 'ui-smoke' },
        verifier: { cited_atom_ids: [], missing_atom_ids: [], citation_accuracy: 1, contradiction_notes: [], confidence: 1 },
        runtime_backend: 'ui-smoke-stub',
      }),
    }),
  );
  await ask.getByRole('button', { name: 'Ask', exact: true }).click();
  const answer = ask.getByTestId('answer');
  await answer.getByText('It hangs in the hall closet.').waitFor();
  await answer.getByText(`${evidenceHits.length} hits · 100% of citations hold · ui-smoke-stub`).waitFor();
  await answer.getByText(replacement).first().waitFor();
});

// 7. mount: a cartridge is a scope you mount, and the machine decides if it may.
const mountRow = page.locator('#cartridges [data-cartridge="ui-smoke"]');
await mountRow.waitFor();
await mountRow.getByRole('button', { name: 'Mount', exact: true }).click();
const mountedState = mountRow.locator('.state', { hasText: 'mounted' });
const refusal = page.locator('#cartridges .fault').first();
await mountedState.or(refusal).waitFor();
if (await mountedState.isVisible()) {
  observed.mount = 'accepted';
  await mountRow.getByRole('button', { name: 'Unmount', exact: true }).click();
  await page.locator('#cartridges').getByText('Unmounted ui-smoke.').waitFor();
} else {
  observed.mount = `refused: ${(await refusal.innerText()).slice(0, 200)}`;
  const cartridges = await apiGet('/api/cartridges');
  const cartridge = cartridges.find((entry) => entry.name === 'ui-smoke');
  if (!cartridge) {
    throw new Error('the ui-smoke cartridge vanished from the store while the console was mounting it');
  }
  expectedFailures.push(`400 /api/cartridges/${cartridge.cartridge_id}/mount`);
}

// 8. adapter states: the section says what is attached and why the rest is not.
const loadStates = page.getByTestId('adapter-states');
await loadStates.scrollIntoViewIfNeeded();
await page.locator('#machine').getByText(/\d+ mounted/).waitFor();
const states = await loadStates.locator('.ledger-row').evaluateAll((rows) =>
  rows.map((row) => [row.querySelector('.state')?.textContent ?? '', (row.querySelector('small')?.textContent ?? '').trim()]),
);
if (states.length === 0) {
  await evidence('the adapter section named no adapter kind at all');
  throw new Error('the adapter section reported no states; the load report was empty');
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

// 9. pick a shelf: the holder filter follows, the shelf lights, and the browse list holds only that holder.
await step('picking a shelf did not narrow the memories to its holder', async () => {
  await page.locator('.legend').getByRole('button', { name: 'wife', exact: true }).click();
  await sceneLit('wife');
  if ((await memory.getByLabel('Holder').inputValue()) !== 'wife') {
    throw new Error('the holder filter did not take the picked shelf');
  }
  await page.waitForFunction(() => {
    const rows = Array.from(document.querySelectorAll('#memory [data-testid="browse-list"] .atom-who strong'));
    return rows.length > 0 && rows.every((row) => row.textContent === 'wife');
  }, undefined, { timeout: 15_000 });
});

// 10. the masthead: a section link scrolls (smoothly, through Lenis) until that section sits under the bar.
await step('a section link did not bring its section into view', async () => {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByRole('navigation', { name: 'sections' }).getByRole('link', { name: 'Cartridges' }).click();
  await page.waitForFunction(() => {
    const top = document.getElementById('cartridges')?.getBoundingClientRect().top;
    const bar = document.querySelector('.masthead')?.getBoundingClientRect().height;
    return top !== undefined && bar !== undefined && Math.abs(top - bar - 12) < 24;
  }, undefined, { timeout: 15_000 });
  await page.getByRole('navigation', { name: 'sections' }).locator('a.active', { hasText: 'Cartridges' }).waitFor();
});

await page.evaluate(() => window.scrollTo(0, 0));
await page.screenshot({ path: path.join(outputDir, 'elysian-dashboard.png'), fullPage: true });
const statusText = await page.getByLabel('system status').innerText();
await browser.close();

const unexpected = failedRequests.filter((line) => !expectedFailures.some((allowed) => line === allowed || line.startsWith(allowed)));
if (unexpected.length > 0 || consoleErrors.length > 0) {
  throw new Error([`${unexpected.length} unexpected failed request(s): ${unexpected.join(', ')}`, ...consoleErrors].join('\n'));
}

console.log(
  JSON.stringify(
    {
      screenshot: path.join(outputDir, 'elysian-dashboard.png'),
      mount: observed.mount,
      supersede: observed.supersede,
      adapters: observed.adapters,
      expected_failures: expectedFailures.filter((line) => failedRequests.includes(line)),
      status: statusText,
    },
    null,
    2,
  ),
);
