// Two OpenCode 2.x locations share one event stream; each must open only its own session, with its own folder.
import { pathToFileURL } from "node:url";
const plugin = (await import(pathToFileURL(process.argv[2]).href)).default;
const listeners = [];
const puts = [];
async function* stream(signal) {
  const queue = [];
  let wake;
  listeners.push((event) => { queue.push(event); wake?.(); });
  while (!signal.aborted) {
    if (!queue.length) await new Promise((resolve) => (wake = resolve));
    while (queue.length) yield queue.shift();
  }
}
const ctx = (directory) => ({
  location: { directory },
  event: { subscribe: ({ signal }) => stream(signal) },
  session: { instructions: { entry: { put: async (entry) => puts.push(entry), remove: async () => {} } }, hook: async () => ({ dispose: async () => {} }) },
});
await plugin.setup(ctx("/w/alpha"));
await plugin.setup(ctx("/w/beta"));
for (const [sessionID, directory] of [["sa", "/w/alpha"], ["sb", "/w/beta"]]) {
  for (const deliver of listeners) deliver({ type: "session.created", data: { sessionID, location: { directory } } });
}
await new Promise((resolve) => setTimeout(resolve, 2000));
const right = puts.length === 2 && puts.every((entry) => (entry.sessionID === "sa") === entry.value.includes("alpha"));
console.log(JSON.stringify(puts));
process.exit(right ? 0 : 1);
