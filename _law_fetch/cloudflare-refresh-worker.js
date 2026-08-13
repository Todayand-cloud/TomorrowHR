/**
 * Cloudflare Worker — TomorrowHR 갱신 프록시
 *
 * 역할
 * 1) POST (기본): GitHub Actions repository_dispatch / workflow_dispatch
 * 2) POST {action:"fetch",url}: law.go.kr·moel.go.kr 본문 대리 수집
 *    → GitHub Actions IP가 법제처에 timed out 되는 문제 우회
 * 3) Cron(scheduled): 매일 09:00 KST(UTC 00:00) 자동 dispatch
 *
 * 【배포】
 * 1) dash.cloudflare.com → Workers → wandering-dew-09bd
 * 2) Edit code: 이 파일 전체 붙여넣기 → Deploy
 * 3) Settings → Variables and Secrets → Secret `GITHUB_TOKEN`
 *    Classic PAT: repo + workflow
 * 4) Triggers → Cron Triggers → Add: `0 0 * * *`  (UTC 00:00 = 한국 09:00)
 *
 * (선택) Secret `PROXY_SECRET` 을 넣으면 fetch 시 헤더 X-Proxy-Secret 필요
 */

const ALLOWED_HOSTS = new Set([
  "www.law.go.kr",
  "law.go.kr",
  "www.moel.go.kr",
  "moel.go.kr",
]);

export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Proxy-Secret",
    };
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method !== "POST") {
      return json({ ok: false, error: "POST only" }, 405, cors);
    }

    let body = {};
    try {
      body = await request.json();
    } catch (_) {
      body = {};
    }

    if (body.action === "fetch") {
      return handleProxyFetch(request, env, body, cors);
    }

    return handleDispatch(env, body, cors);
  },

  /** Cloudflare Cron: 0 0 * * * (UTC) = 매일 한국시간 오전 9시 */
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchRefresh(env, { reason: "cron" }));
  },
};

async function handleProxyFetch(request, env, body, cors) {
  if (env.PROXY_SECRET) {
    const got = request.headers.get("X-Proxy-Secret") || "";
    if (got !== env.PROXY_SECRET) {
      return json({ ok: false, error: "invalid proxy secret" }, 401, cors);
    }
  }

  const url = String(body.url || "").trim();
  let parsed;
  try {
    parsed = new URL(url);
  } catch (_) {
    return json({ ok: false, error: "invalid url" }, 400, cors);
  }
  if (parsed.protocol !== "https:" || !ALLOWED_HOSTS.has(parsed.hostname)) {
    return json(
      { ok: false, error: "host not allowed: " + parsed.hostname },
      403,
      cors
    );
  }

  const upstreamHeaders = {
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
    Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
  };
  if (body.headers && typeof body.headers === "object") {
    for (const [k, v] of Object.entries(body.headers)) {
      if (/^(user-agent|accept|cache-control|pragma)$/i.test(k) && typeof v === "string") {
        upstreamHeaders[k] = v;
      }
    }
  }

  try {
    const res = await fetch(url, {
      method: "GET",
      headers: upstreamHeaders,
      redirect: "follow",
    });
    const text = await res.text();
    if (!res.ok) {
      return json(
        {
          ok: false,
          error: `upstream ${res.status}`,
          status: res.status,
          bodyPreview: text.slice(0, 200),
        },
        502,
        cors
      );
    }
    return json(
      {
        ok: true,
        status: res.status,
        contentType: res.headers.get("content-type") || "",
        body: text,
      },
      200,
      cors
    );
  } catch (err) {
    return json(
      { ok: false, error: String(err && err.message ? err.message : err) },
      502,
      cors
    );
  }
}

async function handleDispatch(env, body, cors) {
  if (!env.GITHUB_TOKEN) {
    return json(
      {
        ok: false,
        error:
          "GITHUB_TOKEN secret missing — Cloudflare Settings에 Secret GITHUB_TOKEN을 넣으세요",
      },
      500,
      cors
    );
  }

  const result = await dispatchRefresh(env, body);
  if (result.ok) {
    return json(result, 200, cors);
  }
  return json(result, 502, cors);
}

async function dispatchRefresh(env, body = {}) {
  if (!env.GITHUB_TOKEN) {
    return { ok: false, error: "GITHUB_TOKEN secret missing" };
  }

  const owner = body.owner || "Todayand-cloud";
  const repo = body.repo || "TomorrowHR";
  const workflow = body.workflowFile || "refresh-laws.yml";
  const ref = body.ref || "main";
  const base = body.base ? String(body.base) : "";

  const headers = {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "TomorrowHR-refresh-proxy",
    "Content-Type": "application/json",
  };

  const attempts = [];

  {
    const res = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/dispatches`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          event_type: "refresh-laws",
          client_payload: base ? { base } : {},
        }),
      }
    );
    if (res.status === 204 || res.status === 200) {
      return {
        ok: true,
        dispatched: true,
        via: "repository_dispatch",
        reason: body.reason || "http",
      };
    }
    attempts.push(
      "repository_dispatch " + res.status + " " + (await res.text()).slice(0, 120)
    );
  }

  {
    const res = await fetch(
      `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${encodeURIComponent(
        workflow
      )}/dispatches`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({
          ref,
          inputs: base ? { base } : {},
        }),
      }
    );
    if (res.status === 204 || res.status === 200) {
      return {
        ok: true,
        dispatched: true,
        via: "workflow_dispatch",
        reason: body.reason || "http",
      };
    }
    attempts.push(
      "workflow_dispatch " + res.status + " " + (await res.text()).slice(0, 120)
    );
  }

  return {
    ok: false,
    error:
      "GitHub 토큰 권한 부족(403). Classic PAT에 repo+workflow 체크 후 Cloudflare Secret GITHUB_TOKEN을 교체하세요. " +
      attempts.join(" | "),
  };
}

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
  });
}
