#!/usr/bin/env bun
// Thin CLI over muse-client for the muse-agent MCP server.
// Every command prints one JSON object on stdout (exit 0 = ok, 1 = failure).
//
// Commands:
//   pair [--directory DIR]                      interactive BLE pairing (run in a terminal)
//   status [--directory DIR]                    credentials + connection check
//   send    <message> [--session ID] [--directory DIR]
//   chat    <message> [--session ID] [--timeout S] [--directory DIR]
//   image   <path> [message] [--session ID] [--timeout S] [--directory DIR]
//
// Credentials default to muse-client's own directory
// (~/Library/Application Support/MuseGadgetPair on macOS).

import { readFile } from 'node:fs/promises';
import path from 'node:path';

function parseArgs(argv) {
  const pos = [];
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--session' || a === '--timeout' || a === '--directory') {
      opts[a.slice(2)] = argv[++i];
    } else if (a.startsWith('--')) {
      opts[a.slice(2)] = true;
    } else {
      pos.push(a);
    }
  }
  return { pos, opts };
}

function out(payload) {
  console.log(JSON.stringify(payload));
}

function fail(error, detail) {
  out({ ok: false, error: String(error?.message || error), ...(detail ? { detail } : {}) });
  process.exit(1);
}

async function connect(opts) {
  const { MuseClient } = await import('muse-client');
  const { loadCredentials, saveCredentials } = await import('muse-client/credentials');
  const directory = opts.directory;
  const credentials = await loadCredentials(directory);
  const client = await MuseClient.connect({
    credentials,
    onCredentials: (c) => saveCredentials(c, directory),
  });
  return client;
}

async function loadImage(pathStr) {
  const ext = path.extname(pathStr).toLowerCase();
  const mime = { '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                 '.gif': 'image/gif', '.webp': 'image/webp' }[ext];
  if (!mime) throw new Error(`unsupported image type ${ext} (JPEG/PNG/GIF/WebP only)`);
  return { data: await readFile(pathStr), mimeType: mime, filename: path.basename(pathStr) };
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  const { pos, opts } = parseArgs(rest);

  if (cmd === 'pair') {
    const { pairMacOS, validateSDKToken } = await import('muse-client/pairing');
    let token = process.env.MUSE_SDK_TOKEN;
    if (!token) {
      process.stdout.write('SDK token (gadgets.muse.ai/settings/sdk-tokens): ');
      for (;;) {
        const line = await new Promise((r) => process.stdin.once('data', r));
        token = String(line).trim();
        if (!token) process.exit(1);
        try { validateSDKToken(token); break; } catch { process.stdout.write('Invalid token, retry: '); }
      }
    }
    const creds = await pairMacOS({
      sdkToken: validateSDKToken(token),
      directory: opts.directory,
      onProgress: (m) => console.error(m),
    });
    out(creds ? { ok: true, paired: true } : { ok: false, error: 'pairing window closed' });
    return;
  }

  if (cmd === 'status') {
    try {
      const { loadCredentials } = await import('muse-client/credentials');
      const creds = await loadCredentials(opts.directory).catch(() => null);
      if (!creds) { out({ ok: true, paired: false, ready: false }); return; }
      const client = await connect(opts);
      out({ ok: true, paired: true, ready: true,
            vm: { id: client.vm.id ?? client.vm.vmId, name: client.vm.name } });
      client.close();
    } catch (e) { fail(e); }
    return;
  }

  if (cmd === 'send' || cmd === 'chat' || cmd === 'image') {
    const message = cmd === 'image' ? (pos[1] ?? '') : pos[0];
    if (cmd !== 'image' && message === undefined) fail('missing message');
    const images = cmd === 'image' ? [await loadImage(pos[0])] : undefined;
    try {
      const client = await connect(opts);
      try {
        if (cmd === 'send') {
          const ack = await client.sendMessage(message, { sessionId: opts.session, images });
          out({ ok: true, message_id: ack.messageId });
          return;
        }
        const timeoutMs = (opts.timeout ? Number(opts.timeout) : 120) * 1000;
        const chatOpts = { timeoutMs, images };
        if (opts.session) { chatOpts.sessionId = opts.session; chatOpts.ownsChat = true; }
        let text = '';
        let timedOut = false;
        try {
          for await (const ev of client.chat(message, chatOpts)) {
            if (ev.type === 'reply') text = ev.text;
          }
        } catch (e) {
          if (/timeout|deadline/i.test(String(e?.message))) timedOut = true; else throw e;
        }
        out(timedOut
          ? { ok: true, reply: '', detail: `delivered, but no complete answer within ${opts.timeout || 120}s — retry` }
          : { ok: true, reply: text });
      } finally {
        client.close();
      }
    } catch (e) { fail(e); }
    return;
  }

  fail(`unknown command: ${cmd}`);
}

main().catch((e) => fail(e));
