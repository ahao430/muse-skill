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

/** Follow one turn, collecting reply text. `first` handles a brand-new side
 * chat: the message creates the chat, then we subscribe and track the turn
 * (small race if Muse answers before the subscription opens — same known
 * limitation as the official CLI; surfaced as a timeout + retry hint). */
async function chatTurn(client, message, chatOpts) {
  let text = '';
  const collect = (events) => {
    for (const ev of events) if (ev.type === 'reply') text = ev.text;
  };
  if (!chatOpts.first) {
    for await (const ev of client.chat(message, chatOpts)) {
      if (ev.type === 'reply') text = ev.text;
    }
    return text;
  }
  const { MuseTurn } = await import('muse-client');
  const ack = await client.sendMessage(message, { sessionId: chatOpts.sessionId, images: chatOpts.images });
  const sub = await client.subscribe({ sessionId: chatOpts.sessionId });
  try {
    const turn = new MuseTurn({ sessionId: chatOpts.sessionId, ownsChat: true });
    collect(turn.acknowledge(ack));
    for await (const ev of sub) {
      collect(turn.feed(ev));
      if (turn.complete()) break;
    }
  } finally {
    sub.close();
  }
  return text;
}

/** Send a message and collect the reply plus any public image URLs from
 * Muse's generated-media presentations. Muse hosts finished media on
 * muse.ai/files/… (sandbox paths are unreachable externally). */
async function chatCollect(message, chatOpts) {
  let client = arguments.length >= 3 ? arguments[2] : await connect(chatOpts.rootOpts ?? {});
  let reply = '';
  const images = [];
  const addImage = (img) => {
    if (img && img.url && !images.some(i => i.url === img.url)) images.push(img);
  };
  if (!chatOpts.first) {
    const { MuseTurn } = await import('muse-client');
    const signal = AbortSignal.timeout(chatOpts.timeoutMs ?? 240000);
    const sub = await client.subscribe({ sessionId: chatOpts.sessionId, signal });
    try {
      const turn = new MuseTurn({ sessionId: chatOpts.sessionId, ownsChat: true });
      const ack = await client.sendMessage(message, { sessionId: chatOpts.sessionId, images: chatOpts.images, signal });
      for (const ev of turn.acknowledge(ack)) collectFromEvent(ev, addImage, t => reply = t);
      for await (const ev of sub) {
        collectFromEvent(ev, addImage, t => reply = t);
        turn.feed(ev);
        if (turn.complete()) break;
      }
    } catch (e) {
      if (!/timeout|abort|TimeoutError/i.test(String(e?.name) + String(e?.message))) throw e;
    } finally { sub.close(); }
    return { reply, images };
  }
  // first:true — message creates the chat; subscribe only after send
  const signal = AbortSignal.timeout(chatOpts.timeoutMs ?? 240000);
  const ack = await client.sendMessage(message, { sessionId: chatOpts.sessionId, images: chatOpts.images, signal });
  const sub = await client.subscribe({ sessionId: chatOpts.sessionId, signal });
  try {
    const { MuseTurn } = await import('muse-client');
    const turn = new MuseTurn({ sessionId: chatOpts.sessionId, ownsChat: true });
    for (const ev of turn.acknowledge(ack)) collectFromEvent(ev, addImage, t => reply = t);
    for await (const ev of sub) {
      collectFromEvent(ev, addImage, t => reply = t);
      turn.feed(ev);
      if (turn.complete()) break;
    }
  } catch (e) {
    if (!/timeout|abort|TimeoutError/i.test(String(e?.name) + String(e?.message))) throw e;
  } finally { sub.close(); }
  return { reply, images };
}

function collectFromEvent(ev, addImage, setText) {
  if (ev?.type === 'reply') setText(ev.text);
  const payload = ev?.raw?.payload ?? ev?.payload;
  const pres = payload?.presentations ?? (payload?.data ? [payload.data] : []);
  for (const p of pres) {
    for (const img of p?.images ?? []) {
      const url = img?.variants?.original ?? img?.variants?.large ?? null;
      // Only public muse.ai links are fetchable; sandbox URLs are not.
      if (url && /https:\/\/(muse\.ai|www\.muse\.ai)\//.test(url) && img.missing !== true) {
        addImage({ url, label: img.label ?? '', mime: img.mime ?? 'image/webp',
                   width: img.width, height: img.height, byte_len: img.byte_len });
      }
    }
  }
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
      let client = await connect(opts);
      try {
        if (cmd === 'send') {
          const ack = await client.sendMessage(message, { sessionId: opts.session, images });
          out({ ok: true, message_id: ack.messageId });
          return;
        }
        const timeoutMs = (opts.timeout ? Number(opts.timeout) : 120) * 1000;
        const images2 = images; // captured above
        let text = '';
        let timedOut = false;
        try {
          if (opts.session) {
            // New side chats must be created by their first message; the
            // subscribe-first path 400s on them. Fall back on a FRESH
            // connection (a failed subscribe leaves the shared one unusable):
            // send first to create the chat, then subscribe and track.
            try {
              text = await chatTurn(client, message, { sessionId: opts.session, ownsChat: true, timeoutMs, images: images2 });
            } catch (e) {
              const msg = String(e?.message);
              if (/HTTP 400/.test(msg)) {
                // Muse only accepts UUID-shaped side chat ids; a 400 on send
                // usually means the id is malformed, not merely "chat unknown".
                if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(opts.session)) {
                  throw new Error(
                    `side chat id '${opts.session}' was rejected (HTTP 400). ` +
                    'Muse requires UUID-format session ids — create one via muse_sessions.'
                  );
                }
              }
              if (!/HTTP (400|404)/.test(msg)) throw e;
              // 404: the side chat does not exist yet. A failed subscribe also
              // leaves the shared connection unusable — retry on a FRESH one,
              // send first to create the chat, then subscribe and track.
              client.close();
              client = await connect(opts);
              text = await chatTurn(client, message, { sessionId: opts.session, ownsChat: true, timeoutMs, images: images2, first: true });
            }
          } else {
            for await (const ev of client.chat(message, { timeoutMs, images: images2 })) {
              if (ev.type === 'reply') text = ev.text;
            }
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

  if (cmd === 'images') {
    // Ask Muse to generate (or re-share) media, then collect public
    // muse.ai/files links from the reply's presentations.
    const message = pos[0] ?? '把你最近生成的图片上传为公网可访问的 muse.ai/files 链接，只发链接。';
    const timeoutMs = (opts.timeout ? Number(opts.timeout) : 240) * 1000;
    try {
      let client = await connect(opts);
      try {
        if (!opts.session) fail('images requires --session <uuid> (use muse_sessions to create one)');
        let result;
        try {
          result = await chatCollect(message, { sessionId: opts.session, ownsChat: true, timeoutMs });
        } catch (e) {
          if (!/HTTP (400|404)/.test(String(e?.message))) throw e;
          client.close();
          client = await connect(opts);
          result = await chatCollect(message, { sessionId: opts.session, ownsChat: true, timeoutMs, first: true });
        }
        out({ ok: true, reply: result.reply, images: result.images });
      } finally { client.close(); }
    } catch (e) { fail(e); }
    return;
  }

  fail(`unknown command: ${cmd}`);
}

main().catch((e) => fail(e));
