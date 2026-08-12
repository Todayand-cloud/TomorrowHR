# 인사 관련 법령문 개정 현황

근로기준법·퇴직급여법·남녀고용평등법·기간제법의 최근 개정·주요 법령 3단보기 사이트입니다.  
데이터는 **국가법령정보센터(law.go.kr)** 기준입니다.

## 「지금 갱신」버튼 (GitHub Pages)

버튼 → GitHub Actions가 법제처를 받아 `js/` 파일을 커밋 → 페이지가 새 데이터를 불러옵니다.

공개 GitHub Pages에서는 토큰을 브라우저에 넣을 수 없어, **무료 Cloudflare Worker 1회 연결**이 필요합니다.

### 최초 1회 설정

1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate  
   - Repository: `TomorrowHR` only  
   - Permissions → **Actions: Read and write**
2. [Cloudflare Workers](https://dash.cloudflare.com) → Create Worker  
   - `_law_fetch/cloudflare-refresh-worker.js` 내용 붙여넣기 → Deploy  
   - Settings → Variables → Secret `GITHUB_TOKEN` = 위에서 만든 PAT
3. Worker 주소(예: `https://xxxx.workers.dev`)를 `js/refresh-config.js`의 `proxyUrl`에 넣고 업로드

이후에는 사이트에서 **「지금 갱신」**만 누르면 됩니다. (보통 1~3분)

자동 스케줄: Actions가 **6시간마다**도 갱신합니다.

## 로컬

1. `사이트실행.bat`  
2. `http://127.0.0.1:8787/`  
3. 「지금 갱신」
