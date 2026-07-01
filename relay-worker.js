// relay-worker.js -- Deploy to Cloudflare Workers
// Secrets: TELEGRAM_BOT_TOKEN, SPACE_URL, AUTH_TOKEN

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // -- Health --
    if (url.pathname === '/health') {
      return json({ ok: true });
    }

    // -- Manual poll (fallback / test) --
    if (url.pathname === '/poll') {
      if (!authorized(request, env)) return unauthorized();
      return pollOutbox(env);
    }

    // -- Webhook receiver (Telegram posts here) --
    if (url.pathname === '/webhook/telegram' && request.method === 'POST') {
      const update = await request.clone().json();

      // Reply 200 immediately to ack Telegram (prevents retry floods).
      // Forward to Space + poll for reply in background via ctx.waitUntil.
      ctx.waitUntil((async () => {
        // 1. Forward update to Space
        try {
          await fetch(env.SPACE_URL + '/webhook/telegram', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(update),
          });
        } catch (e) {
          // Space may be cold-booting; keep polling anyway
        }

        // 2. Poll outbox until reply appears (up to ~90s for cold-boot)
        // Workers Free: waitUntil limited to ~30s, paid to ~900s.
        const pollTimeout = parseInt(env.SPACE_POLL_TIMEOUT || '60000');
        const deadline = Date.now() + pollTimeout;
        while (Date.now() < deadline) {
          let msgs;
          try {
            const resp = await fetch(env.SPACE_URL + '/api/tg_outbox', { timeout: 15000 });
            msgs = (await resp.json()).messages || [];
          } catch {
            msgs = [];
          }
          if (msgs.length > 0) {
            // Drain ALL messages (typing + reply + config items like setMyCommands)
            for (const msg of msgs) {
              await deliver(env, msg);
            }
            break;
          }
          await sleep(500);
        }
      })());

      return json({ ok: true, queued: true });
    }

    return json({ ok: false, error: 'not found' }, 404);
  },
};

// -- Helper functions --------------------------------------------------------

async function fetchOutbox(env) {
  try {
    const resp = await fetch(env.SPACE_URL + '/api/tg_outbox', { timeout: 10000 });
    return (await resp.json()).messages || [];
  } catch { return []; }
}

async function pollOutbox(env) {
  const messages = await fetchOutbox(env);
  const results = [];
  for (const msg of messages) {
    const result = await deliver(env, msg);
    results.push(result);
  }
  return json({ ok: true, processed: results.length, results });
}

async function deliver(env, msg) {
  const method = msg._method || 'sendMessage';
  const payload = { ...msg };
  delete payload._method;
  const maxRetries = 3;
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const resp = await fetch('https://api.telegram.org/bot' + env.TELEGRAM_BOT_TOKEN + '/' + method, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!data.ok && data.error_code === 429 && attempt < maxRetries - 1) {
        await sleep((data.parameters?.retry_after || 5) * 1000);
        continue;
      }
      return { method, ok: data.ok, description: data.description };
    } catch (e) {
      if (attempt < maxRetries - 1) await sleep(1000);
      else return { method, ok: false, description: e.message };
    }
  }
}

function authorized(request, env) {
  if (!env.AUTH_TOKEN) return true;
  return request.headers.get('Authorization') === 'Bearer ' + env.AUTH_TOKEN;
}

function unauthorized() {
  return json({ ok: false, error: 'unauthorized' }, 401);
}

function json(data, status) {
  if (status === undefined) status = 200;
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function sleep(ms) {
  return new Promise(function(r) { setTimeout(r, ms); });
}
