// Capture the GUI screenshots with headless Edge over the DevTools protocol (no extra packages).
// Usage: node scripts/capture_screenshots.mjs docs/screenshots [http://localhost:3000/]
// Needs a running stack (docker compose up) and Microsoft Edge (Windows default path; set EDGE_PATH elsewhere).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const OUT = process.argv[2];
const BASE = process.argv[3] ?? "http://localhost:3000/";
const EDGE = process.env.EDGE_PATH ?? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = join(tmpdir(), `shots-edge-${Date.now()}`);
mkdirSync(profile, { recursive: true });
const edge = spawn(EDGE, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--no-first-run", "--hide-scrollbars", "--disable-gpu", "about:blank"], { stdio: "ignore" });

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error("Edge did not start");
}

const ws = new WebSocket(await target());
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let seq = 0;
const pending = new Map();
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
  }
});
const cdp = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });

async function js(expression) {
  const r = await cdp("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`JS error: ${r.exceptionDetails.text} in ${expression.slice(0, 80)}`);
  return r.result.value;
}
async function until(expression, what, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await js(expression)) return;
    await sleep(200);
  }
  throw new Error(`timed out waiting for: ${what}`);
}
async function shot(name) {
  await sleep(600); // let transitions and smooth scrolling settle
  const { data } = await cdp("Page.captureScreenshot", { format: "png" });
  writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
  console.log("saved", name);
}
async function viewport(width, height, scale, mobile = false) {
  await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: scale, mobile });
}
async function load() {
  await cdp("Page.navigate", { url: BASE });
  await until("!!document.querySelector('.chatrail') && !!document.querySelector('.hdr-links .dot-high')", "GUI loaded");
}

// ---- page helpers (run inside the page)
const idle = "document.querySelectorAll('.turn').length > 0 && !document.querySelector('.turn-busy')";
const clickTab = (label) => js(`[...document.querySelectorAll('.hdr-tabs button')].find(b => b.textContent.startsWith(${JSON.stringify(label)})).click()`);
const clickSuggestion = (title) => js(`[...document.querySelectorAll('.suggestions button')].find(b => b.textContent.includes(${JSON.stringify(title)})).click()`);
async function ask(text) {
  const before = await js("document.querySelectorAll('.turn').length");
  await js(`(() => {
    const ta = document.querySelector('.composer textarea');
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(ta, ${JSON.stringify(text)});
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('form.composer').requestSubmit();
  })()`);
  await until(`document.querySelectorAll('.turn').length > ${before} && !document.querySelector('.turn-busy')`, `answer to: ${text}`);
}
const scrollContentTo = (id) => js(`(document.getElementById(${JSON.stringify(id)}) || document.body).scrollIntoView({ block: 'start' })`);
const scrollContentTop = () => js("document.getElementById('content').scrollTo({ top: 0 })");

await cdp("Page.enable");
await cdp("Runtime.enable");

// ---------------------------------------------------------------- desktop
await viewport(1600, 1000, 1.5);
await load();
await shot("01-welcome.png");

await clickSuggestion("Recurring high-severity alarms");
await until(idle, "acceptance answer");
await clickTab("Overview");
await scrollContentTop();
await shot("02-acceptance-investigation.png");

await clickTab("Evidence");
await scrollContentTop();
await shot("03-acceptance-sources.png");

await clickTab("Execution trace");
await js(`[...document.querySelectorAll('.trace-head')].find(b => b.textContent.includes('correlate_alarms')).click()`);
await sleep(200);
await js(`(() => { const row = [...document.querySelectorAll('.trace-row')].find(r => r.textContent.includes('correlate_alarms'));
  [...row.querySelectorAll('.tabs button')].find(b => b.textContent.startsWith('API calls')).click();
  row.scrollIntoView({ block: 'center' }); })()`);
await shot("04-acceptance-mcp-trace.png");

await ask("Are the API recommendations consistent with the maintenance manual?");
await clickTab("Overview");
await scrollContentTo("sec-actions");
await shot("05-consistency-conflict.png");

await js("[...document.querySelectorAll('.nav-action')].find(b => b.textContent.includes('New case')).click()");
await sleep(300);
await ask("Investigate alarms for Cooling Water Pump 301");
await clickTab("Overview");
await scrollContentTop();
await shot("06-degraded-recommendations-unavailable.png");

await clickTab("Tool catalog");
await until("document.querySelectorAll('details.tool-card').length >= 13", "tool catalog");
await js(`(() => { const d = [...document.querySelectorAll('details.tool-card')].find(x => x.textContent.includes('correlate_alarms')); d.open = true; })()`);
await scrollContentTop();
await shot("07-mcp-tool-discovery.png");

await js("[...document.querySelectorAll('.nav-action')].find(b => b.textContent.includes('New case')).click()");
await sleep(300);
await ask("Why are compressor discharge pressure alarms repeatedly occurring?");
await clickTab("Evidence");
await scrollContentTop();
await shot("08-prompt-injection-quarantine.png");

// ---------------------------------------------------------------- mobile
await viewport(390, 844, 2, true);
await load();
await clickSuggestion("Recurring high-severity alarms");
await until(idle, "acceptance answer (mobile)");
await js("document.querySelector('.body').scrollTo({ top: 0 }); document.querySelector('.chat-scroll').scrollTo({ top: 0 })");
await shot("09-mobile.png");

ws.close();
edge.kill();
console.log("done");
