/**
 * GitHub Pages「지금 갱신」버튼용 설정
 * - proxyUrl: Cloudflare Worker 주소(권장, 토큰 비공개)
 * - githubToken: 비우기 권장. 넣으면 브라우저에 노출됩니다.
 */
window.LAW_REFRESH = {
  owner: "Todayand-cloud",
  repo: "TomorrowHR",
  workflowFile: "refresh-laws.yml",
  ref: "main",
  /** 예: https://tomorrowhr-refresh.xxxxx.workers.dev */
  proxyUrl: "https://wandering-dew-09bd.shkim5.workers.dev",
  githubToken: "",
};
