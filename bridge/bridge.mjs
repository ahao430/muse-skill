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
 * muse.ai/files/… (sandbox paths are unreachable externally).
 *
 * Returns a task-state object (never throws for timeouts):
 *   status: completed | timeout | failed
 *   reply, images[], approvals[], task_done
 * Approvals: when Muse's VM needs egress approval (files.upload etc.) the
 * approvals.snapshot event carries pending_approvals — surfaced so the
 * caller can tell "waiting for human approval" apart from a dead turn. */
async function chatCollect(message, chatOpts) {
  const client = await connect(chatOpts.rootOpts ?? {});
  let reply = '';
  const images = [];
  const approvals = [];
  const addImage = (img) => {
    if (img && img.url && !images.some(i => i.url === img.url)) images.push(img);
  };
  const { MuseTurn } = await import('muse-client');
  let first = !!chatOpts.first;
  let timedOut = false;
  const turn = new MuseTurn({ sessionId: chatOpts.sessionId, ownsChat: true });
  // Hard cap on the whole wait. MuseTurn.complete() only flips when events
  // arrive; without this the iterator can hang forever on a silent turn.
  const signal = AbortSignal.timeout(chatOpts.timeoutMs ?? 240000);
  let sub;
  let sendError = null;
  try {
    if (!first) sub = await client.subscribe({ sessionId: chatOpts.sessionId, signal });
  } catch (e) {
    // 404: chat does not exist yet → create it by sending first (below).
    if (!/HTTP (400|404)/.test(String(e?.message))) { client.close(); throw e; }
    sub = null;
    first = true;
  }
  try {
    let ack;
    try {
      ack = await client.sendMessage(message, { sessionId: chatOpts.sessionId, images: chatOpts.images, signal });
    } catch (e) {
      sendError = e;   // send failed → task genuinely failed, do not fake success
      throw e;
    }
    if (!sub) sub = await client.subscribe({ sessionId: chatOpts.sessionId, signal });
    for (const ev of turn.acknowledge(ack)) collectFromEvent(ev, addImage, t => reply = t);
    for await (const ev of sub) {
      if (ev.event === 'approvals.snapshot') {
        const pending = ev.payload?.pending_approvals ?? [];
        if (pending.length) approvals.push(...pending.map(p => ({
          action_label: p?.display?.action_label ?? '',
          detail_rows: p?.display?.detail_rows ?? [],
          approval_id: p?.approval_id ?? '',
        })));
      }
      collectFromEvent(ev, addImage, t => reply = t);
      turn.feed(ev);
      if (turn.complete()) break;
    }
  } catch (e) {
    if (/timeout|abort|cancel|TimeoutError/i.test(String(e?.name) + String(e?.message))) {
      timedOut = true;
    } else if (!sendError) {
      throw e;
    }
  } finally {
    try { sub?.close(); } catch { /* already closed by abort */ }
    client.close();
  }
  return {
    status: sendError ? 'failed' : (timedOut ? 'timeout' : 'completed'),
    reply, images, approvals,
    detail: sendError ? String(sendError.message) : '',
  };
}

function collectFromEvent(ev, addImage, setText) {
  if (ev?.type === 'reply') setText(ev.text);
  const payload = ev?.raw?.payload ?? ev?.payload;
  const pres = payload?.presentations ?? (payload?.data ? [payload.data] : []);
  for (const p of pres) {
    // File-card form: {url, fallback_text} — Muse shares a single finished
    // media link this way (no images[] array at all).
    const cardUrl = p?.url ?? null;
    if (cardUrl && /https:\/\/(muse\.ai|www\.muse\.ai)\//.test(cardUrl)) {
      addImage({ url: cardUrl, label: (p.fallback_text ?? '').slice(0, 60),
                 mime: cardUrl.endsWith('.png') ? 'image/png' : 'image/webp' });
    }
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

  if (cmd === 'notifications') {
    // Passive listen: subscribe WITHOUT sending; collect text messages and
    // public muse.ai/files links Muse pushes while we listen. Events are
    // live-only (no replay), so this sees only what arrives during the window.
    const listenSec = Math.min(Math.max(Number(opts.timeout ?? 8), 1), 60);
    if (!opts.session) fail('notifications requires --session <uuid>');
    const client = await connect(opts);
    const messages = [];   // {message_id, text, done}
    const images = [];     // same shape as images command
    const buffers = new Map();
    const addImage = (img) => {
      if (img && img.url && !images.some(i => i.url === img.url)) images.push(img);
    };
    try {
      const signal = AbortSignal.timeout(listenSec * 1000);
      const sub = await client.subscribe({ sessionId: opts.session, signal });
      try {
        for await (const ev of sub) {
          if (ev.event === 'delta.text_append') {
            const p = ev.payload ?? {};
            const buf = buffers.get(p.message_id) ?? { message_id: p.message_id, text: '', done: false };
            buf.text += p.text ?? '';
            buffers.set(p.message_id, buf);
          } else if (ev.event === 'delta.message_done') {
            const id = (ev.payload ?? {}).message_id;
            const buf = buffers.get(id);
            if (buf) { buf.done = true; messages.push(buf); buffers.delete(id); }
          } else if (ev.event === 'delta.presentation') {
            // reuse the card/images extraction from collectFromEvent
            collectFromEvent({ payload: ev.payload }, addImage, () => {});
          }
        }
      } finally { sub.close?.(); }
    } catch (e) {
      if (!/timeout|abort|cancel|TimeoutError/i.test(String(e?.name) + String(e?.message))) throw e;
    } finally { client.close(); }
    // keep partial (undone) streams too — Muse may still have been mid-reply
    for (const buf of buffers.values()) if (buf.text.trim()) messages.push(buf);
    out({ ok: true, messages, images });
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
    // muse.ai/files links from the reply's presentations. Status-aware:
    // timeout/approval_required are surfaced, never faked as success.
    const message = pos[0] ?? '把你最近生成的图片上传为公网可访问的 muse.ai/files 链接，只发链接。';
    const timeoutMs = (opts.timeout ? Number(opts.timeout) : 240) * 1000;
    if (!opts.session) fail('images requires --session <uuid> (use muse_sessions to create one)');
    try {
      let result;
      try {
        result = await chatCollect(message, { sessionId: opts.session, ownsChat: true, timeoutMs, rootOpts: opts });
      } catch (e) {
        if (!/HTTP (400|404)/.test(String(e?.message))) throw e;
        result = await chatCollect(message, { sessionId: opts.session, ownsChat: true, timeoutMs, first: true, rootOpts: opts });
      }
      // Muse renders into its sandbox (no public URLs yet). Unless the ask
      // was itself an upload/reshare request, chain a second turn asking
      // Muse to re-share the media as public muse.ai/files links.
      const isReshareAsk = /muse\.ai\/files|转存|上传/i.test(message);
      if (result.status === 'completed' && result.images.length === 0 && !isReshareAsk) {
        const share = await chatCollect(
          '把刚才生成的图片上传为公网可访问的 muse.ai/files 链接，只发链接。',
          { sessionId: opts.session, ownsChat: true,
            timeoutMs: Math.min(timeoutMs, 240000), rootOpts: opts });
        result.images.push(...share.images);
        result.approvals.push(...share.approvals);
        if (!result.reply) result.reply = share.reply;
        if (share.status === 'failed') result.status = 'failed';
        else if (share.status === 'timeout' && result.images.length === 0) result.status = 'timeout';
        else result.status = 'completed';
      }
      const blocked = result.status === 'completed' && result.images.length === 0 && result.approvals.length > 0;
      out({
        ok: result.status !== 'failed',
        status: blocked ? 'approval_required' : result.status,
        reply: result.reply,
        images: result.images,
        approvals: result.approvals,
        detail: result.detail || (result.status === 'timeout'
          ? 'still generating (or waiting for upload approval) — task is NOT lost, retry images/muse_get_images later'
          : ''),
      });
    } catch (e) { fail(e); }
    return;
  }

  fail(`unknown command: ${cmd}`);
}

main().catch((e) => fail(e));
