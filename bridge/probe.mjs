import { loadCredentials, saveCredentials } from 'muse-client/credentials';
import { MuseClient } from 'muse-client';
const sessionId = 'fff81465-c232-4c0e-be81-f6817c4374d0';
const creds = await loadCredentials();
const client = await MuseClient.connect({ credentials: creds, onCredentials: (c) => saveCredentials(c) });
console.error('connected, subscribing…');
const sub = await client.subscribe({ sessionId });
console.error('subscribed ok');
const deadline = Date.now() + 15000;
let n = 0;
try {
  for await (const ev of sub) {
    n++;
    console.error('EVENT:', ev.event ?? ev.type);
    if (Date.now() > deadline) break;
  }
} catch (e) { console.error('sub error:', e.message); }
console.error('events seen:', n, '(stream ended without close =', n >= 0, ')');
client.close();
