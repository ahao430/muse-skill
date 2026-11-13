// 免 TUN 运行器：node + global-agent 让 ws 库走 HTTP 代理（CONNECT 隧道）
// 用法: node node-proxy.mjs <bridge 参数...>   需 GLOBAL_AGENT_HTTP_PROXY 环境变量
import { bootstrap } from 'global-agent';
import { ProxyAgent, setGlobalDispatcher } from 'undici';

// Route Node's native fetch (undici) through the proxy too — global-agent
// only covers http/https module sockets (the ws library), not fetch.
const PROXY = process.env.GLOBAL_AGENT_HTTP_PROXY || process.env.HTTPS_PROXY || '';
if (PROXY) setGlobalDispatcher(new ProxyAgent(PROXY));

// node <22.17 lacks AbortSignal.any (muse-client needs it; bun has it)
if (typeof AbortSignal.any !== 'function') {
  AbortSignal.any = function any(signals) {
    const controller = new AbortController();
    for (const s of signals) {
      if (s.aborted) { controller.abort(s.reason); break; }
      s.addEventListener('abort', () => controller.abort(s.reason), { once: true });
    }
    return controller.signal;
  };
}

bootstrap();
await import('./bridge.mjs');
