/**
 * Cloudflare Worker — GitHub Actions 갱신 프록시
 *
 * 【필수】Classic PAT 권장 (Fine-grained는 403이 자주 남)
 * 1) https://github.com/settings/tokens → Generate new token (classic)
 * 2) 체크: repo (전체) + workflow
 * 3) dash.cloudflare.com → Workers → wandering-dew-09bd
 *    → Edit code: 이 파일 전체 붙여넣기 → Deploy
 *    → Settings → Variables and Secrets → Secret 이름 GITHUB_TOKEN
 *      값에 새 classic 토큰 붙여넣기 (Production)
 */
export default {
  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method !== "POST") {
      return json({ ok: false, error: "POST only" }, 405, cors);
    }
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

    let body = {};
    try {
      body = await request.json();
    } catch (_) {
      body = {};
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

    // 1) repository_dispatch
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
        return json(
          { ok: true, dispatched: true, via: "repository_dispatch" },
          200,
          cors
        );
      }
      attempts.push(
        "repository_dispatch " + res.status + " " + (await res.text()).slice(0, 120)
      );
    }

    // 2) workflow_dispatch (파일명)
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
        return json(
          { ok: true, dispatched: true, via: "workflow_dispatch" },
          200,
          cors
        );
      }
      attempts.push(
        "workflow_dispatch " + res.status + " " + (await res.text()).slice(0, 120)
      );
    }

    return json(
      {
        ok: false,
        error:
          "GitHub 토큰 권한 부족(403). Classic PAT에 repo+workflow 체크 후 Cloudflare Secret GITHUB_TOKEN을 교체하세요. " +
          attempts.join(" | "),
      },
      502,
      cors
    );
  },
};

function json(obj, status, cors) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
  });
}
