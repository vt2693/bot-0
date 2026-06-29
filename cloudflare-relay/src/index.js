// relay-worker.js -- Deploy to Cloudflare Workers
// Secrets: TELEGRAM_BOT_TOKEN, SPACE_URL, AUTH_TOKEN

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/health') {
      return json({ ok: true });
    }

    if (url.pathname === '/poll') {
      if (!authorized(request, env)) return unauthorized();
      return json(await pollOutbox(env));
    }

    if (url.pathname === '/webhook/telegram' && request.method === 'POST') {
      const update = await request.clone().json();

      // Forward to Space AND WAIT for the response.
      // If Space is cold-booting, this may take 15-60s.
      // Telegram's webhook timeout is ~30s; if we exceed it, Telegram retries.
      // This is BETTER than returning 200 and losing the update.
      try {
        const fwd = await fetch(env.SPACE_URL + '/webhook/telegram', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(update),
          signal: AbortSignal.timeout(25000),
        });
        if (!fwd.ok) {
          return json({ ok: false, error: 'space returned ' + fwd.status }, 502);
        }
      } catch (e) {
        return json({ ok: false, error: 'space unreachable: ' + e.message }, 502);
      }

      // Space confirmed receipt. Now poll outbox in background.
      ctx.waitUntil(drainOutboxUntilEmpty(env));

      return json({ ok: true });
    }

    return json({ ok: false, error: 'not found' }, 404);
  },

  async scheduled(event, env, ctx) {
    const result = await pollOutbox(env);
    console.log('cron:', JSON.stringify(result));
  },
};

async function drainOutboxUntilEmpty(env) {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const msgs = await fetchOutbox(env);
    if (msgs.length === 0) {
      await sleep(2000);
      continue;
    }
    for (const msg of msgs) {
      await deliver(env, msg);
    }
    break;
  }
}

async function fetchOutbox(env) {
  try {
    const resp = await fetch(env.SPACE_URL + '/api/tg_outbox', { timeout: 15000 });
    return (await resp.json()).messages || [];
  } catch { return []; }
}

async function pollOutbox(env) {
  const messages = await fetchOutbox(env);
  const results = [];
  for (const msg of messages) {
    results.push(await deliver(env, msg));
  }
  return { ok: true, processed: results.length, results };
}

async function deliver(env, msg) {
  const method = msg._method || 'sendMessage';
  const payload = { ...msg };
  delete payload._method;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const resp = await fetch('https://api.telegram.org/bot' + env.TELEGRAM_BOT_TOKEN + '/' + method, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!data.ok && data.error_code === 429 && attempt < 2) {
        await sleep((data.parameters?.retry_after || 5) * 1000);
        continue;
      }
      return { method, ok: data.ok };
    } catch (e) {
      if (attempt < 2) await sleep(1000);
      else return { method, ok: false, error: e.message };
    }
  }
}

function authorized(request, env) {
  if (!env.AUTH_TOKEN) return true;
  return request.headers.get('Authorization') === 'Bearer ' + env.AUTH_TOKEN;
}

function unauthorized() { return json({ ok: false, error: 'unauthorized' }, 401); }
function json(data, status) {
  if (status === undefined) status = 200;
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}
function sleep(ms) { return new Promise(function(r) { setTimeout(r, ms); }); }
