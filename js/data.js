/**
 * 인사 관련 법령문 개정 현황 — 목록·이슈·개정 메타
 * 조문 본문은 js/law-articles.js (국가법령정보센터 https://www.law.go.kr/ 기준)
 */

window.LAW_DATA = {
  siteName: "인사 관련 법령문 개정 현황",
  sourceNote:
    "개정일·시행일·하이라이트는 「수동 갱신」으로 법제처(law.go.kr)에서 새로 수집·교차검증한 결과만 표시합니다. 샘플 일자는 사용하지 않습니다.",
  laws: [
    {
      id: "labor-standards",
      shortName: "근로기준법",
      name: "근로기준법",
      decreeName: "근로기준법 시행령",
      ruleName: "근로기준법 시행규칙",
      summary: "근로조건의 기준을 정하여 근로자의 기본적 생활을 보장·향상하고 균형 있는 국민경제 발전을 꾀하는 법률",
      sourceUrl: "https://www.law.go.kr/법령/근로기준법",
    },
    {
      id: "retirement",
      shortName: "퇴직급여보장법",
      name: "근로자퇴직급여 보장법",
      decreeName: "근로자퇴직급여 보장법 시행령",
      ruleName: "근로자퇴직급여 보장법 시행규칙",
      summary: "퇴직급여제도의 설정·운영에 필요한 사항을 정하여 근로자의 안정적인 노후생활을 보장하는 법률",
      sourceUrl: "https://www.law.go.kr/법령/근로자퇴직급여보장법",
    },
    {
      id: "equal-employment",
      shortName: "남녀고용평등법",
      name: "남녀고용평등과 일·가정 양립 지원에 관한 법률",
      decreeName: "남녀고용평등과 일·가정 양립 지원에 관한 법률 시행령",
      ruleName: "남녀고용평등과 일·가정 양립 지원에 관한 법률 시행규칙",
      summary: "고용에서 남녀의 평등한 기회·대우와 일·가정 양립을 지원하는 법률",
      sourceUrl: "https://www.law.go.kr/법령/남녀고용평등과일ㆍ가정양립지원에관한법률",
    },
    {
      id: "fixed-term",
      shortName: "기간제법",
      name: "기간제 및 단시간근로자 보호 등에 관한 법률",
      decreeName: "기간제 및 단시간근로자 보호 등에 관한 법률 시행령",
      ruleName: "기간제 및 단시간근로자 보호 등에 관한 법률 시행규칙",
      summary: "기간제·단시간근로자에 대한 불합리한 차별을 시정하고 근로조건 보호를 강화하는 법률",
      sourceUrl: "https://www.law.go.kr/법령/기간제및단시간근로자보호등에관한법률",
    },
  ],

  // consultations: js/consultations-data.js 에서 로드

  /**
   * 개정 현황(샘플 금지)
   * - 실제 표시·일자는 수동 갱신으로 수집한 js/amendments-cache.json 만 사용
   * - 공포일·시행일·하이라이트는 법제처 연혁과 교차 검증된 항목만 반영
   */
  amendments: [],
};
