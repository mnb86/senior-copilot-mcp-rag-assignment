// Minimal, dependency-free Postman collection runner (subset of the `pm` API used by the collections).
// Usage: node scripts/postman_runner.mjs <collection.json> [baseUrl] [token]
// CI additionally runs the same collections with newman.
import { readFileSync } from "node:fs";

const [file, baseUrl = "http://localhost:8000", token = process.env.ALARM_API_TOKEN ?? "demo-token"] = process.argv.slice(2);
const col = JSON.parse(readFileSync(file, "utf8"));
const vars = Object.fromEntries((col.variable ?? []).map((v) => [v.key, v.value]));
vars.baseUrl = baseUrl;
vars.auth_token = token;
const sub = (s) => (typeof s === "string" ? s.replace(/\{\{(\w+)\}\}/g, (_, k) => sub(vars[k] ?? "")) : s);

function expect(actual) {
  const api = {
    to: {
      be: { above: (n) => { if (!(actual > n)) throw new Error(`expected ${actual} > ${n}`); } },
      have: { status: (s) => { if (actual !== s) throw new Error(`expected status ${s}, got ${actual}`); } },
      equal: (v) => { if (actual !== v) throw new Error(`expected ${v}, got ${actual}`); },
    },
  };
  return api;
}

let passed = 0, failed = 0;
async function run(item, prefix = "") {
  if (item.item) { for (const child of item.item) await run(child, `${prefix}${item.name ?? ""} / `); return; }
  const req = item.request;
  const url = sub(typeof req.url === "string" ? req.url : req.url.raw);
  const headers = Object.fromEntries((req.header ?? []).map((h) => [h.key, sub(h.value)]));
  const auth = req.auth ?? col.auth;
  if (auth?.type === "bearer") headers.Authorization = `Bearer ${sub(auth.bearer[0].value)}`;
  const body = req.body?.mode === "raw" ? sub(req.body.raw) : undefined;
  const res = await fetch(encodeURI(decodeURI(url)), { method: req.method, headers, body });
  const text = await res.text();
  let json = null; try { json = JSON.parse(text); } catch {}
  const errors = [];
  if (res.status >= 400) errors.push(`HTTP ${res.status}: ${text.slice(0, 200)}`);
  const pm = {
    response: { json: () => json, code: res.status, to: { have: { status: (s) => expect(res.status).to.have.status(s) } } },
    collectionVariables: { set: (k, v) => { vars[k] = v; }, get: (k) => vars[k] },
    expect,
    test: (name, fn) => { try { fn(); } catch (e) { errors.push(`${name}: ${e.message}`); } },
  };
  for (const ev of item.event ?? []) {
    if (ev.listen !== "test") continue;
    try { new Function("pm", ev.script.exec.join("\n"))(pm); } catch (e) { errors.push(`script: ${e.message}`); }
  }
  const echoed = headers.trace_id ? res.headers.get("trace_id") === headers.trace_id : true;
  if (!echoed) errors.push("trace_id header not echoed");
  const label = `${prefix}${item.name}`;
  if (errors.length) { failed++; console.log(`FAIL ${label}\n     ${errors.join("\n     ")}`); }
  else { passed++; console.log(`ok   ${label}  [${res.status}]`); }
}

for (const item of col.item) await run(item);
console.log(`\n${col.info.name}: ${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
