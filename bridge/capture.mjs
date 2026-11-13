#!/usr/bin/env bun
// Subscribe to a side chat, optionally send a message, dump raw events to
// a JSONL file, and print any http(s) URLs found in payloads (Muse puts
// generated images / files / cards there).
//
//   bun capture.mjs --session <uuid> [--send "message"] [--out events.jsonl] [--timeout 180]

import { appendFileSync, writeFileSync } from 'node:fs';
import { loadCredentials, saveCredentials } from 'muse-client/credentials';
import { MuseClient } from 'muse-client';

function parseArgs(argv) {
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--session' || a === '--send' || a === '--out' || a === '--timeout') opts[a.slice(2)] = argv[++i];
  }
  return opts;
}

const opts = parseArgs(process.argv.slice(2));
const out = opts.out ?? 'muse-events.jsonl';
const timeout = Number(opts.timeout ?? 180) * 1000;
if (!opts.session) { console.error('missing --session'); process.exit(2); }

const credentials = await loadCredentials();
const client = await MuseClient.connect({
  credentials,
  onCredentials: (c) => saveCredentials(c),
});

let sent = false;
const urls = new Set();
writeFileSync(out, '');

const deadline = Date.now() + timeout;
const sub = await client.subscribe({ sessionId: opts.session });
(async () => {
  for await (const ev of sub) {
    const line = { t: new Date().toISOString(), ...ev };
    appendFileSync(out, JSON.stringify(line) + '\n');
    const urlsIn = JSON.stringify(ev.raw ?? ev.payload ?? {}).match(/https?:\/\/[^"\\\s]+/g) ?? [];
    for (const u of urlsIn) {
      if (!/\.(png|jpe?g|webp|gif|mp3|mp4|pdf|zip|bin)(\?|$)/i.test(u) && !/resource|media|file|image|cdn|storage/i.test(u)) continue;
      if (!urls.has(u)) { urls.add(u); console.error('URL:', u); }
    }
    if (Date.now() > deadline) break;
  }
})();

if (opts.send) {
  const ack = await client.sendMessage(opts.send, { sessionId: opts.session });
  sent = true;
  console.error('sent:', ack.messageId);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
while (Date.now() < deadline) await sleep(2000);
client.close();
console.log(JSON.stringify({ ok: true, sent, urls: [...urls], events: out }));
