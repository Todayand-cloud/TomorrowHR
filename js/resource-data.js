/**
 * 질의회시집 / 시행예정 법령 / 입법·행정예고
 * 출처: 고용노동부 공개 게시판 (2026-08 기준 정리)
 */
window.LAW_DATA = window.LAW_DATA || {};

window.LAW_DATA.compilationsMeta = {
  sourcePortal:
    "https://www.moel.go.kr/info/publicdata/majorpublish/majorPublishList.do?searchDivCd=4",
  note: "고용노동부 「주요발간자료 > 질의회시집」 PDF 발간물입니다.",
};

window.LAW_DATA.compilations = [
  {
    id: "comp-20251000303",
    title: "사내 및 공동근로복지기금 질의회시집(2025)",
    category: "근로복지",
    dept: "노무제공자지원과",
    date: "2025-10-29",
    views: 14055,
    summary: "사내근로복지기금·공동근로복지기금 관련 질의회시를 모은 2025년 발간 PDF입니다.",
    url: "https://www.moel.go.kr/info/publicdata/majorpublish/majorPublishView.do?bbs_seq=20251000303&searchDivCd=4",
  },
  {
    id: "comp-20250301239",
    title: "기간제법 질의회시집(2018.4.~2024.8.)",
    category: "비정규직",
    dept: "고용차별개선과",
    date: "2025-03-19",
    views: 0,
    summary: "기간제 및 단시간근로자 보호 등에 관한 법률 질의회시를 정리한 발간물입니다.",
    url: "https://www.moel.go.kr/policy/policydata/view.do?bbs_seq=20250301239",
  },
  {
    id: "comp-20240600297",
    title: "근로자퇴직급여보장법 질의회시집",
    category: "퇴직급여",
    dept: "퇴직연금복지과",
    date: "2024-06-07",
    views: 46840,
    summary: "퇴직금·퇴직연금 질의회시를 수록한 PDF입니다. (수록기간 ~2022.1.)",
    url: "https://www.moel.go.kr/info/publicdata/majorpublish/majorPublishView.do?bbs_seq=20240600297&searchDivCd=4",
  },
  {
    id: "comp-20240500833",
    title: "산업안전보건법 질의회시집",
    category: "산업안전",
    dept: "산업안전보건정책과",
    date: "2024-05-21",
    views: 79182,
    summary: "산업안전보건법 분야 질의회시 모음 PDF입니다.",
    url: "https://www.moel.go.kr/info/publicdata/majorpublish/majorPublishView.do?bbs_seq=20240500833&searchDivCd=4",
  },
  {
    id: "comp-20240101604",
    title: "근로기준법 질의회시집(2018.4.~2023.6.)",
    category: "근로기준",
    dept: "근로기준정책과",
    date: "2024-01-24",
    views: 70133,
    summary: "근로기준법 등 근로기준 분야 주요 질의회시를 기간별로 묶은 발간물입니다.",
    url: "https://www.moel.go.kr/info/publicdata/majorpublish/majorPublishView.do?bbs_seq=20240101604&searchDivCd=4",
  },
  {
    id: "comp-20230501310",
    title: "노동조합및노동관계조정법 질의회시집(2020)",
    category: "노사관계",
    dept: "노사관계법제과",
    date: "2023-05-23",
    views: 53023,
    summary: "노동조합법 관련 질의회시 정리본입니다.",
    url: "https://www.moel.go.kr/info/publicdata/majorpublish/majorPublishView.do?bbs_seq=20230501310&searchDivCd=4",
  },
];

window.LAW_DATA.upcomingMeta = {
  note: "시행예정은 「최근 개정」과 연동됩니다. 카드의 「개정 조문 대조 보기」에서 노란 음영·개정 전 내용을 확인할 수 있습니다.",
};

window.LAW_DATA.upcomingLaws = [
  {
    id: "up-1",
    lawId: "retirement",
    lawName: "고용보험법",
    tier: "법률",
    title: "소득(보수) 기반 고용보험 적용기준 전환",
    amendedDate: "2026-03-17",
    effectiveDate: "2027-01-01",
    summary:
      "근로자 고용보험 적용기준을 소정근로시간에서 보수로 개편하는 내용 등이 포함됩니다. (법률 제21473호)",
    status: "시행예정",
    url: "https://www.law.go.kr/",
  },
  {
    id: "up-2",
    lawId: "equal-employment",
    lawName: "남녀고용평등법 시행령",
    tier: "시행령",
    title: "일·가정 양립 지원 관련 시행령 후속 정비",
    amendedDate: "2026-07-27",
    effectiveDate: "2026-10-01",
    summary:
      "남녀고용평등법 시행령 일부개정과 연계된 후속 정비·재입법예고 흐름을 반영한 시행예정 항목입니다.",
    status: "시행예정",
    url: "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700877",
  },
  {
    id: "up-3",
    lawId: "labor-standards",
    lawName: "근로기준법 시행령",
    tier: "시행령",
    title: "근로기준법 시행령 일부개정 후속 시행",
    amendedDate: "2026-07-13",
    effectiveDate: "2026-09-01",
    summary: "임금·근로시간 정책과 연계된 시행령 개정안의 후속 시행 일정입니다.",
    status: "시행예정",
    url: "https://www.moel.go.kr/info/lawinfo/lawmaking/list.do",
  },
  {
    id: "up-4",
    lawId: "fixed-term",
    lawName: "기간제 및 단시간근로자 보호 등에 관한 법률 시행령",
    tier: "시행령",
    title: "기간제 사용기간 제한 예외 운용 기준 점검",
    amendedDate: "2026-09-01",
    effectiveDate: "2026-11-01",
    summary: "전문자격·연구기관 등 2년 초과 사용 예외 사유 운용과 관련한 시행예정 이슈입니다.",
    status: "시행예정",
    url: "law.html?id=fixed-term",
  },
  {
    id: "up-5",
    lawId: "labor-standards",
    lawName: "근로감독관규정",
    tier: "훈령·예규",
    title: "근로감독관규정 일부개정 시행",
    amendedDate: "2026-07-14",
    effectiveDate: "2026-10-15",
    summary: "근로감독 기획·집행 관련 규정 개정에 따른 시행예정 항목입니다.",
    status: "시행예정",
    url: "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700511",
  },
];

window.LAW_DATA.noticesMeta = {
  "sourcePortal": "https://www.moel.go.kr/info/lawinfo/lawmaking/list.do",
  "note": "고용노동부 「입법·행정예고」 게시판을 기준일 기준으로 자동 수집한 결과입니다.",
  "fetchedAt": "2026-08-13T23:44:55",
  "baseDate": "2026-08-14"
};

window.LAW_DATA.notices = [
  {
    "id": "nt-20260800403",
    "type": "입법",
    "title": "고용노동부와 그 소속기관 직제 시행규칙 일부개정령(안) 입법예고",
    "dept": "혁신행정담당관",
    "date": "2026-08-12",
    "views": 506,
    "summary": "입법예고 · 혁신행정담당관",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260800403",
    "bbsSeq": "20260800403"
  },
  {
    "id": "nt-20260800400",
    "type": "입법",
    "title": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령 일부개정령안 입법예고",
    "dept": "고용문화개선정책과",
    "date": "2026-08-12",
    "views": 641,
    "summary": "입법예고 · 고용문화개선정책과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260800400",
    "bbsSeq": "20260800400"
  },
  {
    "id": "nt-20260800340",
    "type": "행정",
    "title": "장애인 직업능력개발훈련 지원규정 일부개정(안) 행정예고",
    "dept": "장애인고용과",
    "date": "2026-08-10",
    "views": 1074,
    "summary": "행정예고 · 장애인고용과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260800340",
    "bbsSeq": "20260800340"
  },
  {
    "id": "nt-20260800111",
    "type": "행정",
    "title": "체불청산지원 사업주 특별융자 심사 업무 처리규정제정안 행정예고",
    "dept": "퇴직연금복지과",
    "date": "2026-08-04",
    "views": 1817,
    "summary": "행정예고 · 퇴직연금복지과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260800111",
    "bbsSeq": "20260800111"
  },
  {
    "id": "nt-20260800042",
    "type": "행정",
    "title": "도산등사실인정 및 확인업무 처리규정 일부개정예규안 행정예고",
    "dept": "퇴직연금복지과",
    "date": "2026-08-03",
    "views": 1984,
    "summary": "행정예고 · 퇴직연금복지과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260800042",
    "bbsSeq": "20260800042"
  },
  {
    "id": "nt-20260701059",
    "type": "입법",
    "title": "유해·위험작업의 취업 제한에 관한 규칙 일부개정령안 입법예고",
    "dept": "산업안전기준과",
    "date": "2026-07-30",
    "views": 2753,
    "summary": "입법예고 · 산업안전기준과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260701059",
    "bbsSeq": "20260701059"
  },
  {
    "id": "nt-20260700877",
    "type": "입법",
    "title": "남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령 일부개정령안 재입법예고",
    "dept": "고용문화개선정책과",
    "date": "2026-07-27",
    "views": 3439,
    "summary": "입법예고 · 고용문화개선정책과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700877",
    "bbsSeq": "20260700877"
  },
  {
    "id": "nt-20260700860",
    "type": "행정",
    "title": "고령자고용연장지원금액 등 고시 폐지(안) 행정예고",
    "dept": "고령사회인력정책과",
    "date": "2026-07-24",
    "views": 2869,
    "summary": "행정예고 · 고령사회인력정책과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700860",
    "bbsSeq": "20260700860"
  },
  {
    "id": "nt-20260700840",
    "type": "입법",
    "title": "노동감독관 직무집행법 시행규칙 제정안 입법예고",
    "dept": "근로감독기획과",
    "date": "2026-07-24",
    "views": 2538,
    "summary": "입법예고 · 근로감독기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700840",
    "bbsSeq": "20260700840"
  },
  {
    "id": "nt-20260700839",
    "type": "입법",
    "title": "노동감독관 직무집행법 시행령 제정안 입법예고",
    "dept": "근로감독기획과",
    "date": "2026-07-24",
    "views": 2669,
    "summary": "입법예고 · 근로감독기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700839",
    "bbsSeq": "20260700839"
  },
  {
    "id": "nt-20260700735",
    "type": "입법",
    "title": "고용보험법 시행령 일부개정령안 입법예고",
    "dept": "고용보험기획과",
    "date": "2026-07-22",
    "views": 2826,
    "summary": "입법예고 · 고용보험기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700735",
    "bbsSeq": "20260700735"
  },
  {
    "id": "nt-20260700511",
    "type": "입법",
    "title": "근로감독관규정 일부개정령안 입법예고",
    "dept": "근로감독기획과",
    "date": "2026-07-14",
    "views": 4172,
    "summary": "입법예고 · 근로감독기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700511",
    "bbsSeq": "20260700511"
  },
  {
    "id": "nt-20260700464",
    "type": "행정",
    "title": "근로자 신용보증지원사업 관리 운영규정 일부개정고시안 행정예고",
    "dept": "퇴직연금복지과",
    "date": "2026-07-13",
    "views": 3188,
    "summary": "행정예고 · 퇴직연금복지과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700464",
    "bbsSeq": "20260700464"
  },
  {
    "id": "nt-20260700463",
    "type": "행정",
    "title": "근로복지사업 운영규정 일부개정고시안 행정예고",
    "dept": "퇴직연금복지과",
    "date": "2026-07-13",
    "views": 2395,
    "summary": "행정예고 · 퇴직연금복지과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700463",
    "bbsSeq": "20260700463"
  },
  {
    "id": "nt-20260700458",
    "type": "행정",
    "title": "장애인 취업지원 업무처리 규정 일부개정(안) 행정예고",
    "dept": "장애인고용과",
    "date": "2026-07-13",
    "views": 2225,
    "summary": "행정예고 · 장애인고용과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700458",
    "bbsSeq": "20260700458"
  },
  {
    "id": "nt-20260700444",
    "type": "입법",
    "title": "근로기준법 시행령 일부개정령안 입법예고",
    "dept": "임금근로시간정책과",
    "date": "2026-07-13",
    "views": 3633,
    "summary": "입법예고 · 임금근로시간정책과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700444",
    "bbsSeq": "20260700444"
  },
  {
    "id": "nt-20260700397",
    "type": "입법",
    "title": "고용산재보험료징수법 시행규칙 일부개정령안 입법예고",
    "dept": "고용보험기획과",
    "date": "2026-07-10",
    "views": 2081,
    "summary": "입법예고 · 고용보험기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700397",
    "bbsSeq": "20260700397"
  },
  {
    "id": "nt-20260700396",
    "type": "입법",
    "title": "고용산재보험료징수법 시행령 일부개정령안 입법예고",
    "dept": "고용보험기획과",
    "date": "2026-07-10",
    "views": 2231,
    "summary": "입법예고 · 고용보험기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700396",
    "bbsSeq": "20260700396"
  },
  {
    "id": "nt-20260700395",
    "type": "입법",
    "title": "고용보험법 시행규칙 일부개정령안 입법예고",
    "dept": "고용보험기획과",
    "date": "2026-07-10",
    "views": 1821,
    "summary": "입법예고 · 고용보험기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700395",
    "bbsSeq": "20260700395"
  },
  {
    "id": "nt-20260700394",
    "type": "입법",
    "title": "고용보험법 시행령 일부개정령안 입법예고",
    "dept": "고용보험기획과",
    "date": "2026-07-10",
    "views": 2221,
    "summary": "입법예고 · 고용보험기획과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700394",
    "bbsSeq": "20260700394"
  },
  {
    "id": "nt-20260700381",
    "type": "입법",
    "title": "고용보험 및 산업재해보상보험의 보험료징수 등에 관한 법률 시행령 일부개정령안 입법예고",
    "dept": "산재보상정책과",
    "date": "2026-07-09",
    "views": 2122,
    "summary": "입법예고 · 산재보상정책과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700381",
    "bbsSeq": "20260700381"
  },
  {
    "id": "nt-20260700380",
    "type": "입법",
    "title": "산업재해보상보험법 시행령 일부개정령안 입법예고",
    "dept": "산재보상정책과",
    "date": "2026-07-09",
    "views": 1072,
    "summary": "입법예고 · 산재보상정책과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700380",
    "bbsSeq": "20260700380"
  },
  {
    "id": "nt-20260700192",
    "type": "입법",
    "title": "근로복지기본법 시행규칙 일부개정령(안) 입법예고",
    "dept": "노무제공자지원과",
    "date": "2026-07-06",
    "views": 1391,
    "summary": "입법예고 · 노무제공자지원과",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700192",
    "bbsSeq": "20260700192"
  },
  {
    "id": "nt-20260700073",
    "type": "입법",
    "title": "고용노동부와 그 소속기관 직제 시행규칙 일부개정령(안) 입법예고",
    "dept": "혁신행정담당관",
    "date": "2026-07-02",
    "views": 1254,
    "summary": "입법예고 · 혁신행정담당관",
    "url": "https://www.moel.go.kr/info/lawinfo/lawmaking/view.do?bbs_seq=20260700073",
    "bbsSeq": "20260700073"
  }
];
