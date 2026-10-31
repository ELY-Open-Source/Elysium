// Elysian local memory for OpenCode: OpenCode 1.x loads `server`, OpenCode 2.x loads `setup`.
import { execFile } from "node:child_process";

// Filled in by `elysian-mcp setup`: the elysian-mcp binary, and the Elysian home or null for the default.
const BINARY = __ELYSIAN_BINARY__;
const HOME = __ELYSIAN_HOME__;
const HOOK_TIMEOUT_MS = 15000;

// hook runs one Elysian hook event and resolves to the text it adds to the context; a failure is logged and adds none.
function hook(event, payload) {
  const args = ["hook", "--client", "opencode", ...(HOME === null ? [] : ["--elysian-home", HOME]), event];
  return new Promise((resolve) => {
    const child = execFile(BINARY, args, { timeout: HOOK_TIMEOUT_MS, maxBuffer: 4 << 20 }, (error, stdout, stderr) => {
      if (error) {
        console.error(`elysian: the ${event} hook failed, this turn runs without memory: ${String(stderr).trim() || error.message}`);
        resolve("");
        return;
      }
      resolve(String(stdout).trim());
    });
    // A hook that exits before reading stdin is reported by the callback above, so its broken pipe is not.
    child.stdin.on("error", () => {});
    child.stdin.end(JSON.stringify(payload));
  });
}

// perSession runs `open` once per session, so a prompt that races the session event still waits for it.
function perSession(open) {
  const started = new Map();
  return (sessionID) => {
    if (!started.has(sessionID)) {
      started.set(sessionID, open(sessionID));
    }
    return started.get(sessionID);
  };
}

// promptText is what the user typed: OpenCode's own synthetic and ignored parts are left out.
function promptText(parts) {
  return parts
    .filter((part) => part.type === "text" && !part.synthetic && !part.ignored)
    .map((part) => part.text)
    .join("\n")
    .trim();
}

export default {
  id: "elysian",

  // OpenCode 2.x: memory is a keyed instruction entry of the session; a changed entry reaches the next model call.
  async setup(ctx) {
    const cwd = ctx.location.directory;
    const entries = ctx.session.instructions.entry;
    const put = async (sessionID, key, text) => {
      try {
        await (text ? entries.put({ sessionID, key, value: text }) : entries.remove({ sessionID, key }));
      } catch (error) {
        console.error(`elysian: could not ${text ? "set" : "clear"} the ${key} instructions: ${error?.message ?? error}`);
      }
    };
    // Events reach every location's plugin, so each session keeps its own folder and only its location opens it.
    const folders = new Map();
    const folderOf = (sessionID) => folders.get(sessionID) ?? cwd;
    const open = perSession(async (sessionID) => put(sessionID, "elysian-session", await hook("session-start", { session_id: sessionID, cwd: folderOf(sessionID) })));
    const stop = new AbortController();
    const watching = (async () => {
      for await (const event of ctx.event.subscribe({ types: ["session.created"], signal: stop.signal })) {
        const location = event.data.location;
        if (event.type !== "session.created" || location?.directory !== cwd) {
          continue;
        }
        folders.set(event.data.sessionID, event.data.subpath ? `${location.directory}/${event.data.subpath}` : location.directory);
        open(event.data.sessionID);
      }
    })().catch((error) => stop.signal.aborted || console.error(`elysian: stopped watching new sessions: ${error?.message ?? error}`));
    const registration = await ctx.session.hook("prompt", async (input) => {
      await open(input.sessionID);
      const prompt = input.prompt.text.trim();
      if (prompt) {
        await put(input.sessionID, "elysian-recall", await hook("prompt", { session_id: input.sessionID, cwd: folderOf(input.sessionID), prompt }));
      }
    });
    return async () => {
      stop.abort();
      await registration.dispose();
      await watching;
    };
  },

  // OpenCode 1.x: memory is added to the system prompt of every model call in the session.
  async server(input) {
    const cwd = input.directory;
    const open = perSession((sessionID) => hook("session-start", { session_id: sessionID, cwd }));
    const recalls = new Map();
    return {
      event: async ({ event }) => {
        if (event.type === "session.created") {
          open(event.properties.info.id);
        }
      },
      "chat.message": async (message, output) => {
        await open(message.sessionID);
        const prompt = promptText(output.parts);
        if (prompt) {
          recalls.set(message.sessionID, await hook("prompt", { session_id: message.sessionID, cwd, prompt }));
        }
      },
      "experimental.chat.system.transform": async (request, output) => {
        if (!request.sessionID) {
          return;
        }
        for (const text of [await open(request.sessionID), recalls.get(request.sessionID)]) {
          if (text) {
            output.system.push(text);
          }
        }
      },
    };
  },
};
