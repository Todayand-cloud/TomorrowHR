(function () {
  "use strict";

  const DATA = window.LAW_DATA;
  const ARTICLES = window.LAW_ARTICLES || {};
  if (!DATA) return;

  const AMD_FORWARD_DAYS = 182; // 공포 ±6개월
  const AMD_LOOKBACK_DAYS = 182;
  const EFF_FORWARD_DAYS = 182; // 시행 ±6개월
  const EFF_LOOKBACK_DAYS = 182;
  const FORWARD_DAYS = AMD_FORWARD_DAYS;
  const LOOKBACK_DAYS = AMD_LOOKBACK_DAYS;
  const CONSULT_TOP_N = 10;
  const MAX_MONTHS_BACK = 3;
  const REFRESH_HOST = "http://127.0.0.1:8787";
  const AMENDMENTS_CACHE_URL = "js/amendments-cache.json";
  const NOTICES_CACHE_URL = "js/notices-cache.json";
  const ENSURE_SERVER_HREF = "_law_fetch/ensure_server.bat";
  const bundledAmendments = Array.isArray(DATA.amendments) ? DATA.amendments.slice() : [];
  let liveAmendments = null;
  let liveAmendmentsMeta = null;
  let currentBaseDate = null;

  /* ---------- utils ---------- */
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function formatDate(date) {
    return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())}`;
  }

  function toInputValue(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function startOfDay(date) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  function parseYMD(str) {
    const [y, m, d] = str.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  function addMonths(date, months) {
    const d = startOfDay(date);
    const day = d.getDate();
    d.setMonth(d.getMonth() + months);
    if (d.getDate() < day) d.setDate(0);
    return d;
  }

  function daysBetween(a, b) {
    const ms = 24 * 60 * 60 * 1000;
    const utcA = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate());
    const utcB = Date.UTC(b.getFullYear(), b.getMonth(), b.getDate());
    return Math.abs(Math.round((utcA - utcB) / ms));
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getQueryParam(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function normalizePhrase(phrase, item) {
    if (typeof phrase === "string") {
      const isNew = /신설/.test(phrase) || /\[본조신설/.test(phrase);
      return {
        text: phrase,
        beforeText: "",
        beforeNote: isNew
          ? "신설된 내용으로, 개정 전 해당 문구는 없습니다."
          : "개정 전 전문은 법제처 조문 연혁·비교보기에서 확인하세요.",
        isNew: isNew,
        amendedDate: item.amendedDate,
        effectiveDate: item.effectiveDate,
        amendmentTitle: item.title,
        locator: "",
      };
    }
    const text = phrase.text || "";
    const isNew =
      Boolean(phrase.isNew) ||
      (!phrase.beforeText && (/신설/.test(text) || /\[본조신설/.test(text)));
    return {
      text: text,
      beforeText: phrase.beforeText || "",
      beforeNote:
        phrase.beforeNote ||
        (isNew
          ? "신설된 내용으로, 개정 전 해당 문구는 없습니다."
          : "개정 전 전문은 법제처 조문 연혁·비교보기에서 확인하세요."),
      pending: Boolean(phrase.pending),
      isNew: isNew,
      pendingDelete:
        Boolean(phrase.pendingDelete) ||
        (Boolean(phrase.pending) && /^\d+(?:의\d+)?\.\s*삭제\b/.test(text)),
      amendedDate: phrase.amendedDate || item.amendedDate,
      effectiveDate: phrase.effectiveDate || item.effectiveDate,
      amendmentTitle: phrase.amendmentTitle || item.title,
      amendmentSummary: item.summary || item.briefSummary || "",
      locator: phrase.locator || "",
    };
  }

  function formatDotDate(ymd) {
    return ymd ? ymd.replace(/-/g, ".") : "-";
  }

  function renderBeforeMemo(phrase) {
    // 미시행 호 삭제: 본문은 현행 유지 → 호버에 시행 후(삭제) 안내
    if (phrase.pending && phrase.pendingDelete && phrase.text) {
      return (
        '<span class="amend-mark__memo" role="tooltip">' +
        '<span class="amend-mark__memo-label">시행 후 조항</span>' +
        '<span class="amend-mark__memo-body">' +
        escapeHtml(phrase.text) +
        "</span>" +
        (phrase.beforeNote
          ? '<span class="amend-mark__memo-empty">' +
            escapeHtml(phrase.beforeNote) +
            "</span>"
          : "") +
        "</span>"
      );
    }
    const hasBefore = Boolean(phrase.beforeText);
    const body = hasBefore
      ? '<span class="amend-mark__memo-body">' + escapeHtml(phrase.beforeText) + "</span>"
      : '<span class="amend-mark__memo-empty">' +
        escapeHtml(
          phrase.beforeNote ||
            (phrase.isNew
              ? "신설된 내용으로, 개정 전 해당 문구는 없습니다."
              : "개정 전 전문은 법제처 조문 연혁·비교보기에서 확인하세요.")
        ) +
        "</span>";

    return (
      '<span class="amend-mark__memo" role="tooltip">' +
      '<span class="amend-mark__memo-label">' +
      (hasBefore ? "개정 전 조항" : "법제처 연혁 안내") +
      "</span>" +
      body +
      "</span>"
    );
  }

  /** 음영 1개 = 공포·시행 칩 1쌍 (다중 칩 금지 — 제110조 이중 일자 오류 방지) */
  function buildAmendMark(phrase, afterEsc) {
    const amd = phrase.amendedDate || "";
    const eff = phrase.effectiveDate || "";
    const deleteChip =
      phrase.pending && phrase.pendingDelete
        ? '<span class="amend-mark__chip amend-mark__chip--del">삭제예정</span>'
        : "";
    return (
      '<mark class="amend-mark" tabindex="0" data-amended="' +
      escapeHtml(amd) +
      '" data-effective="' +
      escapeHtml(eff) +
      (phrase.pendingDelete ? '" data-pending-delete="1' : "") +
      '">' +
      afterEsc +
      '<span class="amend-mark__meta" aria-hidden="true">' +
      (phrase.locator
        ? '<span class="amend-mark__chip amend-mark__chip--loc">' +
          escapeHtml(phrase.locator) +
          "</span>"
        : "") +
      deleteChip +
      '<span class="amend-mark__chip">공포 ' +
      escapeHtml(formatDotDate(amd)) +
      "</span>" +
      '<span class="amend-mark__chip amend-mark__chip--eff">시행 ' +
      escapeHtml(formatDotDate(eff)) +
      "</span>" +
      "</span>" +
      renderBeforeMemo(phrase) +
      "</mark>"
    );
  }

  function stripHistTags(text) {
    return String(text || "")
      .replace(/\s*<(?:개정|신설)\s[^>]*>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  /** before/after 전문에서 최소 치환(old→new) 추출 — 연쇄 pending 합성용 */
  function minimalSubstitution(before, after) {
    const b = stripHistTags(before);
    const a = stripHistTags(after);
    if (!b || !a || b === a) return null;
    let pre = 0;
    while (pre < b.length && pre < a.length && b.charAt(pre) === a.charAt(pre)) {
      pre += 1;
    }
    let suf = 0;
    while (
      suf < b.length - pre &&
      suf < a.length - pre &&
      b.charAt(b.length - 1 - suf) === a.charAt(a.length - 1 - suf)
    ) {
      suf += 1;
    }
    // '제2항'처럼 너무 짧으면 다른 항까지 지워지므로, 본문에 1회만 나오도록 좌측 확장
    while (pre > 0) {
      const old = b.slice(pre, b.length - suf);
      const occurrences = old ? b.split(old).length - 1 : 0;
      if (old.length >= 8 && occurrences === 1) break;
      if (old.length >= 24 && occurrences >= 1) break;
      pre -= 1;
    }
    return {
      old: b.slice(pre, b.length - suf),
      neu: a.slice(pre, a.length - suf),
    };
  }

  function replaceFirst(haystack, oldStr, newStr) {
    const at = haystack.indexOf(oldStr);
    if (at === -1) return haystack;
    return haystack.slice(0, at) + newStr + haystack.slice(at + oldStr.length);
  }

  /** 최소 치환이 '제'를 공통접두로 빼면 음영이 '104조'처럼 끊김 → 본문에 '제'+old 있으면 복원 */
  function withJoPrefix(raw, oldStr, newStr) {
    if (!oldStr || !newStr) return { old: oldStr, neu: newStr };
    if (oldStr.charAt(0) === "제") return { old: oldStr, neu: newStr };
    const prefixed = "제" + oldStr;
    if (raw.indexOf(prefixed) !== -1) {
      return { old: prefixed, neu: "제" + newStr };
    }
    return { old: oldStr, neu: newStr };
  }

  function isCleanSpan(oldStr, newStr) {
    if (!oldStr || !newStr) return false;
    if (oldStr.length < 4 || newStr.length < 2) return false;
    if (/^[\s,·ㆍ]/.test(oldStr) || /[\s,·ㆍ]$/.test(oldStr)) return false;
    if (/^[\s,·ㆍ]/.test(newStr) || /[\s,·ㆍ]$/.test(newStr)) return false;
    return true;
  }

  /** 요약 「A」→「B」 또는 최소 치환으로 독립 음영 구간 확정 */
  function resolveIndependentSpan(p, raw) {
    const summary = p.amendmentSummary || p.amendmentTitle || "";
    const sm = String(summary).match(/「([^」]{2,120})」\s*→\s*「([^」]{2,120})」/);
    let sub = null;
    if (sm && raw.indexOf(sm[1]) !== -1 && isCleanSpan(sm[1], sm[2])) {
      sub = { old: sm[1], neu: sm[2] };
    } else {
      const sub0 = minimalSubstitution(p.beforeText, p.text);
      if (!(sub0 && sub0.old && raw.indexOf(sub0.old) !== -1)) return null;
      sub = withJoPrefix(raw, sub0.old, sub0.neu);
      if (raw.indexOf(sub.old) === -1) return null;
      if (!isCleanSpan(sub.old, sub.neu)) return null;
    }
    // 조사 을/를 이 old 바로 뒤에 있으면 함께 치환 (제104조제2항을 → 제104조를)
    if (raw.indexOf(sub.old + "을") !== -1) {
      sub = {
        old: sub.old + "을",
        neu: /[을를]$/.test(sub.neu) ? sub.neu : sub.neu + "를",
      };
    } else if (raw.indexOf(sub.old + "를") !== -1) {
      sub = {
        old: sub.old + "를",
        neu: /[을를]$/.test(sub.neu) ? sub.neu : sub.neu + "를",
      };
    }
    return sub;
  }

  function fixJosaJoEul(text) {
    // 제104조제2항을 → 제104조을 잔여를 제104조를 로 보정
    return String(text || "").replace(/조을(?=\s|위반|위반한|,|\.|$)/g, "조를");
  }

  /**
   * 같은 조·호에 미시행 개정이 여러 건이면 시행일 순으로 합성.
   * (예: 제110조 제1호 — 제104조제2항→제104조 후 제4항 및 제5항→부터)
   */
  function phraseKey(p) {
    return (
      (p.text || "") + "|" + (p.locator || "") + "|" + (p.amendedDate || "")
    );
  }

  /**
   * 같은 항·호에 미시행 개정이 여러 건이면 시행일 순으로 항·호 전문을 합성.
   * - 조각(단어·구) 음영 금지: 항상 항·호 단위 1음영
   * - 칩은 공포·시행 1쌍만 (최종 합성문 기준 = 가장 늦은 시행)
   * - 개정 전(호버) = 현행 본문 항·호(앵커)
   */
  function composePendingGroup(raw, group) {
    if (!group || group.length <= 1) return group || [];

    const sorted = group.slice().sort(function (a, b) {
      const de = parseYMD(a.effectiveDate) - parseYMD(b.effectiveDate);
      if (de !== 0) return de;
      return parseYMD(a.amendedDate) - parseYMD(b.amendedDate);
    });

    // 가장 긴 beforeText(항·호 전문)를 앵커로 — 조각 음영 방지
    let anchor = null;
    const byLen = sorted.slice().sort(function (a, b) {
      return (b.beforeText || "").length - (a.beforeText || "").length;
    });
    for (let i = 0; i < byLen.length; i += 1) {
      const b = byLen[i].beforeText || "";
      if (b && raw.indexOf(b) !== -1) {
        anchor = b;
        break;
      }
      const bs = stripHistTags(b);
      if (bs && raw.indexOf(bs) !== -1) {
        anchor = bs;
        break;
      }
    }
    if (!anchor) return group;

    let working = stripHistTags(anchor);
    const applied = [];
    sorted.forEach(function (p) {
      const sub = minimalSubstitution(p.beforeText, p.text);
      if (sub && sub.old && working.indexOf(sub.old) !== -1) {
        working = replaceFirst(working, sub.old, sub.neu);
        working = fixJosaJoEul(working);
        applied.push(p);
        return;
      }
      const pb = stripHistTags(p.beforeText);
      const pa = stripHistTags(p.text);
      if (pb && working.indexOf(pb) !== -1) {
        working = replaceFirst(working, pb, pa);
        working = fixJosaJoEul(working);
        applied.push(p);
      }
    });

    if (applied.length <= 1) {
      // 합성 실패 시에도 가장 긴 항·호 전문 1개만 (조각·중복 칩 제거)
      const full = byLen[0];
      if (
        full &&
        stripHistTags(full.beforeText || "") !== stripHistTags(full.text || "")
      ) {
        return [full];
      }
      return group.slice(0, 1);
    }

    // 연쇄 합성: 본문은 합치고, 칩은 가장 늦은 시행 1쌍(최종 문구 기준)
    const byEff = applied.slice().sort(function (a, b) {
      const de = parseYMD(a.effectiveDate) - parseYMD(b.effectiveDate);
      if (de !== 0) return de;
      return parseYMD(a.amendedDate) - parseYMD(b.amendedDate);
    });
    const primary = byEff[byEff.length - 1];
    const latest = applied[applied.length - 1];
    return [
      {
        text: working,
        beforeText: anchor,
        beforeNote: latest.beforeNote || "",
        pending: true,
        isNew: false,
        amendedDate: primary.amendedDate,
        effectiveDate: primary.effectiveDate,
        amendmentTitle: latest.amendmentTitle,
        locator: latest.locator || applied[0].locator || "",
      },
    ];
  }

  function composePendingPhrases(body, phrases) {
    const raw = body || "";
    const pending = [];
    const rest = [];
    (phrases || []).forEach(function (p) {
      if (p && p.pending && !p.isNew && p.beforeText && p.text) pending.push(p);
      else rest.push(p);
    });
    if (pending.length <= 1) return phrases || [];

    // locator(제1항/제2항/제1호…) 단위로만 합성 — 항 삭제와 다른 항 치환을 섞지 않음
    // 제110조처럼 '제1호'와 '제110조제1호'가 섞여도 같은 호로 묶음
    function normalizeLocatorKey(loc) {
      const s = String(loc || "").trim();
      if (!s) return "_";
      const ho = s.match(/제\s*(\d+(?:의\d+)?)\s*호\s*$/);
      const hang = s.match(/제\s*(\d+)\s*항(?:제\s*(\d+(?:의\d+)?)\s*호)?\s*$/);
      if (hang) {
        return hang[2]
          ? "제" + hang[1] + "항제" + hang[2] + "호"
          : "제" + hang[1] + "항";
      }
      if (ho) return "제" + ho[1] + "호";
      return s;
    }
    const groups = {};
    const order = [];
    pending.forEach(function (p) {
      const key = normalizeLocatorKey(p.locator);
      if (!groups[key]) {
        groups[key] = [];
        order.push(key);
      }
      groups[key].push(p);
    });

    let out = rest.slice();
    order.forEach(function (key) {
      out = out.concat(composePendingGroup(raw, groups[key]));
    });
    return out;
  }

  /** ①②…⑮ — 항 번호 삽입 시 다음 항 원문자 찾기 */
  const CIRCLE_HANGS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮";

  /** locator·문구에서 호 번호 추출 (1호 / 제1호 / 제2항제1호 / "1. …") */
  function extractHoNum(locator, text) {
    const loc = String(locator || "").replace(/\s/g, "");
    let m = loc.match(/^(?:제\d+항)?제?(\d+)(?:의\d+)?호$/);
    if (m) return parseInt(m[1], 10);
    m = String(text || "")
      .replace(/^\s+/, "")
      .match(/^(\d+)(?:의\d+)?\./);
    if (m) return parseInt(m[1], 10);
    return null;
  }

  /** 신설 항·호 삽입 순서: 항 → 호 오름차순 (길이순 정렬로 2·1·3 섞임 방지) */
  function phraseStructureSortKey(phrase) {
    const loc = String((phrase && phrase.locator) || "").replace(/\s/g, "");
    const text = String((phrase && phrase.text) || "").replace(/^\s+/, "");
    let hang = 0;
    const hangM = loc.match(/제(\d+)항/);
    if (hangM) hang = parseInt(hangM[1], 10);
    else if (text && CIRCLE_HANGS.indexOf(text.charAt(0)) !== -1) {
      hang = CIRCLE_HANGS.indexOf(text.charAt(0)) + 1;
    }
    const ho = extractHoNum(loc, text);
    return hang * 100000 + (ho == null ? 0 : ho);
  }

  /**
   * 미시행 신설 항·호: 조 끝이 아니라 구조 위치에 삽입.
   * - 제N항제M호: 해당 항(①…다음항) 블록 안에서만 호 번호순 배치
   * - 1호/제1호(항 없음): 조 전체에서 호 번호순
   */
  function insertIndexForNewPhrase(html, phrase) {
    const loc = String(phrase.locator || "").replace(/\s/g, "");
    const hoNum = extractHoNum(loc, phrase.text);
    const hangM = loc.match(/제(\d+)항/);

    let rangeStart = 0;
    let rangeEnd = html.length;
    if (hangM) {
      const hangN = parseInt(hangM[1], 10);
      if (hangN >= 1 && hangN <= CIRCLE_HANGS.length) {
        const circle = CIRCLE_HANGS.charAt(hangN - 1);
        const at = html.indexOf(circle);
        if (at !== -1) rangeStart = at;
        if (hangN < CIRCLE_HANGS.length) {
          const nextCircle = CIRCLE_HANGS.charAt(hangN);
          const endAt = html.indexOf(nextCircle, rangeStart + 1);
          if (endAt !== -1) rangeEnd = endAt;
        }
      }
    }

    if (hoNum != null) {
      const slice = html.slice(rangeStart, rangeEnd);
      for (let n = hoNum + 1; n <= hoNum + 40; n++) {
        const re = new RegExp("(^|\\n)" + n + "\\.");
        const m = re.exec(slice);
        if (m) {
          return rangeStart + m.index + (m[1] ? m[1].length : 0);
        }
      }
      if (hoNum > 1) {
        const re = new RegExp("(^|\\n)" + (hoNum - 1) + "\\.[^\\n]*", "g");
        let last = null;
        let m;
        while ((m = re.exec(slice))) last = m;
        if (last) return rangeStart + last.index + last[0].length;
      }
      // 항 블록 끝(다음 항 앞) — 제1항제2호 → ② 앞
      if (hangM && rangeEnd < html.length) return rangeEnd;
      return -1;
    }

    if (hangM) {
      const hangN = parseInt(hangM[1], 10);
      if (hangN >= 1 && hangN <= CIRCLE_HANGS.length) {
        // 다음 항·그 이후 항(⑦⑧⑨…) 중 본문에 있는 첫 자리 앞
        // 제6항 신설 시 기존 ⑥→⑨ 이동 후 ⑨ 앞에 삽입하기 위함
        for (let n = hangN; n < CIRCLE_HANGS.length; n++) {
          const nextCircle = CIRCLE_HANGS.charAt(n);
          const at = html.indexOf(nextCircle);
          if (at !== -1) return at;
        }
      }
    }
    return -1;
  }

  function insertNewPendingPhrase(html, phrase) {
    const afterEsc = escapeHtml(phrase.text);
    if (!afterEsc) return html;
    if (html.indexOf(afterEsc) !== -1) return html;
    const markHtml = buildAmendMark(phrase, afterEsc);
    const at = insertIndexForNewPhrase(html, phrase);
    if (at < 0) {
      return (html.trim() ? html + "\n" : "") + markHtml;
    }
    let prefix = html.slice(0, at);
    let suffix = html.slice(at);
    if (prefix && !/\n$/.test(prefix)) prefix += "\n";
    if (suffix && suffix.charAt(0) !== "\n") suffix = "\n" + suffix;
    return prefix + markHtml + suffix;
  }

  function highlightBody(body, phrases) {
    let html = escapeHtml(body || "");
    if (!phrases || !phrases.length) return html;

    const composed = composePendingPhrases(body, phrases);
    const list = composed
      .slice()
      .filter(function (p) {
        return p && p.text;
      })
      .sort(function (a, b) {
        return b.text.length - a.text.length;
      });

    // 미시행 신설: 본문이 비어 있으면 개정문 전문을 한 덩어리로 표시
    if (!html.trim()) {
      const neo = list.find(function (p) {
        return p.pending && p.isNew && p.text;
      });
      if (neo) {
        return buildAmendMark(neo, escapeHtml(neo.text));
      }
    }

    list.forEach(function (phrase) {
      const afterEsc = escapeHtml(phrase.text);
      const beforeEsc = escapeHtml(phrase.beforeText || "");
      if (!afterEsc) return;

      // 미시행 호 삭제: 법제처처럼 현행 문구를 노란 음영으로 두고, 시행 후 삭제는 호버·칩으로
      if (
        phrase.pending &&
        phrase.pendingDelete &&
        beforeEsc &&
        html.indexOf(beforeEsc) !== -1
      ) {
        let searchEsc = beforeEsc;
        const histTail = /^\s*&lt;(?:개정|신설)\s[\s\S]*?&gt;/;
        const at = html.indexOf(beforeEsc);
        if (at !== -1) {
          const rest = html.slice(at + beforeEsc.length);
          const hm = rest.match(histTail);
          if (hm) searchEsc = beforeEsc + hm[0];
        }
        html = html
          .split(searchEsc)
          .join(buildAmendMark(phrase, beforeEsc));
        return;
      }

      // 본문에 개정 후가 있으면 그대로, 없으면(시행 전) 개정 전 자리에 개정 후를 표기
      let searchEsc = afterEsc;
      if (html.indexOf(afterEsc) === -1) {
        if (phrase.pending && beforeEsc && html.indexOf(beforeEsc) !== -1) {
          searchEsc = beforeEsc;
          // 연혁 태그 없이 매칭된 경우 바로 뒤 &lt;개정…&gt; 까지 함께 치환
          // (잔여 `<개정` 조각이 노란 음영 밖으로 남는 오류 방지)
          const histTail = /^\s*&lt;(?:개정|신설)\s[\s\S]*?&gt;/;
          const at = html.indexOf(beforeEsc);
          if (at !== -1) {
            const rest = html.slice(at + beforeEsc.length);
            const hm = rest.match(histTail);
            if (hm) searchEsc = beforeEsc + hm[0];
          }
        } else {
          return;
        }
      }

      html = html.split(searchEsc).join(buildAmendMark(phrase, afterEsc));
    });

    // 미시행 항·호 신설: 항·호 번호 오름차순으로 삽입 (길이순이면 2→1→3 섞임)
    list
      .filter(function (phrase) {
        return phrase.pending && phrase.isNew && phrase.text;
      })
      .slice()
      .sort(function (a, b) {
        return phraseStructureSortKey(a) - phraseStructureSortKey(b);
      })
      .forEach(function (phrase) {
        html = insertNewPendingPhrase(html, phrase);
      });

    return html;
  }

  function ensureHighlightEntry(map, articleId) {
    if (!map[articleId]) {
      map[articleId] = { phrases: [], amendments: [] };
    }
    return map[articleId];
  }

  function getRangeStart(baseDate) {
    const start = new Date(baseDate);
    start.setDate(start.getDate() - AMD_LOOKBACK_DAYS);
    return start;
  }

  function getRangeEnd(baseDate) {
    const end = new Date(baseDate);
    end.setDate(end.getDate() + AMD_FORWARD_DAYS);
    return end;
  }

  function getEffRangeStart(baseDate) {
    const start = new Date(baseDate);
    start.setDate(start.getDate() - EFF_LOOKBACK_DAYS);
    return start;
  }

  function getEffRangeEnd(baseDate) {
    const end = new Date(baseDate);
    end.setDate(end.getDate() + EFF_FORWARD_DAYS);
    return end;
  }

  function isInAmendmentWindow(item, baseDate) {
    if (!item || !item.amendedDate) return false;
    const base = startOfDay(baseDate);
    const amdStart = getRangeStart(base);
    const amdEnd = getRangeEnd(base);
    const effStart = getEffRangeStart(base);
    const effEnd = getEffRangeEnd(base);
    const amd = parseYMD(item.amendedDate);
    const eff = item.effectiveDate ? parseYMD(item.effectiveDate) : null;
    // 공포 ±6개월, 시행 ±6개월 (OR)
    const amdIn = amd >= amdStart && amd <= amdEnd;
    const effIn = eff ? eff >= effStart && eff <= effEnd : false;
    return amdIn || effIn;
  }

  function hasArticleDetail(item) {
    return Boolean(
      item &&
        ((item.articleIds && item.articleIds.length) ||
          (item.highlights && item.highlights.length))
    );
  }

  function hasPhraseHighlights(item) {
    return Boolean(
      item &&
        (item.highlights || []).some(function (h) {
          return h && h.phrases && h.phrases.length;
        })
    );
  }

  /** 주요 법령 3단 대조용: 조문 단위 변경만 (「일부개정(법률 제○○호)」 이력 카드 제외) */
  function isMajorLawComparable(item) {
    if (!item) return false;
    if (item.articleLevel) return true;
    if (hasPhraseHighlights(item)) return true;
    return false;
  }

  function isBillLevelRevisionTitle(item) {
    const title = (item && item.title) || "";
    return (
      /(일부개정|타법개정)/.test(title) &&
      /\((법률|대통령령|총리령|부령|고용노동부령)\s*제\d+호\)/.test(title)
    );
  }

  function getComparePair(item) {
    if (!item) return { before: "", after: "" };
    let before = (item.compareBefore || "").trim();
    let after = (item.compareAfter || "").trim();
    if (!before && !after) {
      (item.highlights || []).some(function (h) {
        return (h.phrases || []).some(function (ph) {
          if (ph.beforeText || ph.text) {
            before = (ph.beforeText || "").trim();
            after = (ph.text || "").trim();
            return true;
          }
          return false;
        });
      });
    }
    if (!before && !after) {
      const text = (item.summary || "").replace(/\s+/g, " ").trim();
      let m = text.match(
        /종전에는\s*(.+?)\s*(?:하던\s*것을|하도록\s*하던\s*것을|로\s*하던\s*것을|이었으나|였으나)\s*앞으로는\s*(.+?)(?:\s*함으로써|\s*하려는|\s*하도록|\.|$)/
      );
      if (m) {
        before = m[1].replace(/[,·\s]+$/, "");
        after = m[2].replace(/[,·\s]+$/, "");
      } else {
        m = text.match(/[‘']([^‘']{2,80})[’']\s*를\s*[‘']([^‘']{2,80})[’']\s*로/);
        if (m) {
          before = m[1].trim();
          after = m[2].trim();
        } else {
          m = text.match(
            /[‘']([^‘']{2,120})[’']\s*에서\s*[‘']([^‘']{2,120})[’']\s*(?:으로|로)/
          );
          if (m) {
            before = m[1].trim();
            after = m[2].trim();
          } else {
            m = text.match(
              /([0-9]+일|[0-9]+명\s*(?:이하|미만|이상|초과)?(?:\s*기업)?)\s*에서\s*([0-9]+일|[0-9]+명\s*(?:이하|미만|이상|초과)?(?:\s*기업)?)\s*(?:으로|로)/
            );
            if (m) {
              before = m[1].trim();
              after = m[2].trim();
            } else {
              m = text.match(
                /현행\s*([0-9][^.]{0,60}?|[‘'][^‘']{2,80}[’'])\s*에서\s*([0-9][^.]{0,60}?|[‘'][^‘']{2,80}[’'])\s*(?:으로|로)\s*(?:상향|강화|확대|조정|변경)/
              );
              if (m) {
                before = m[1].replace(/[,·\s]+$/, "");
                after = m[2].replace(/[,·\s]+$/, "");
              }
            }
          }
        }
      }
    }
    return { before: before, after: after };
  }

  function renderCompareBlock(item) {
    const pair = getComparePair(item);
    if (!pair.before && !pair.after) return "";
    return (
      '<div class="amend-compare" aria-label="개정 전후 비교">' +
      '<div class="amend-compare__col amend-compare__col--before">' +
      '<span class="amend-compare__label">개정 전</span>' +
      '<p class="amend-compare__text">' +
      escapeHtml(pair.before || "해당 문구 없음(신설) 또는 원문 대조 필요") +
      "</p></div>" +
      '<div class="amend-compare__col amend-compare__col--after">' +
      '<span class="amend-compare__label">개정 후</span>' +
      '<p class="amend-compare__text">' +
      escapeHtml(pair.after || item.briefSummary || item.summary || "") +
      "</p></div></div>"
    );
  }

  function getDetailAmendmentsForLaw(lawId, baseDate) {
    const base = baseDate || currentBaseDate || getBaseDateBounds().today;
    // 주요 법령: 조문 단위 개정 + (펼치지 못한) 하이라이트 있는 이력을 3단에 표시
    // 단순 「일부개정(법률 제○○호)」 묶음만 있고 조문 음영이 없으면 제외
    return filterAmendments(base)
      .filter(function (item) {
        if (item.lawId !== lawId) return false;
        if (item.articleLevel || hasPhraseHighlights(item)) return true;
        if (hasArticleDetail(item) && !isBillLevelRevisionTitle(item)) return true;
        return false;
      })
      .slice()
      .sort(function (a, b) {
        return parseYMD(b.amendedDate) - parseYMD(a.amendedDate);
      });
  }

  /** 최근 개정: 4대 법령 개정일을 일자별로 나열 (조문 단위 우선, 없으면 묶음 이력) */
  function filterRecentAmendments(baseDate) {
    const items = filterAmendments(baseDate);
    const parentHasArticleChild = {};
    items.forEach(function (item) {
      if (item.articleLevel && item.parentId) {
        parentHasArticleChild[item.parentId] = true;
      }
    });
    return items.filter(function (item) {
      if (item.articleLevel) return true;
      if (parentHasArticleChild[item.id]) return false;
      return true;
    });
  }

  function makeChangeBrief(item) {
    const pair = getComparePair(item);
    if (pair.before && pair.after) {
      const b = pair.before.length > 48 ? pair.before.slice(0, 47) + "…" : pair.before;
      const a = pair.after.length > 48 ? pair.after.slice(0, 47) + "…" : pair.after;
      return "변경 전: " + b + " → 변경 후: " + a;
    }
    if (pair.after) return "변경 후: " + pair.after;
    return item.briefSummary || item.summary || "";
  }

  function firstArticleId(item) {
    if (!item) return "";
    if (item.articleIds && item.articleIds[0]) return item.articleIds[0];
    if (item.highlights && item.highlights[0] && item.highlights[0].articleId) {
      return item.highlights[0].articleId;
    }
    return "";
  }

  function buildHighlightMap(lawId, baseDate) {
    const map = {};
    getDetailAmendmentsForLaw(lawId, baseDate).forEach(function (item) {
      if (!hasArticleDetail(item)) return;

      function attachAmendment(aid) {
        const entry = ensureHighlightEntry(map, aid);
        const exists = entry.amendments.some(function (a) {
          return a.id === item.id;
        });
        if (!exists) {
          entry.amendments.push({
            id: item.id,
            title: item.title,
            amendedDate: item.amendedDate,
            effectiveDate: item.effectiveDate,
            status: item.status,
            summary: item.summary,
            briefSummary: item.briefSummary,
            compareBefore: item.compareBefore,
            compareAfter: item.compareAfter,
          });
        }
      }

      (item.articleIds || []).forEach(attachAmendment);

      (item.highlights || []).forEach(function (h) {
        attachAmendment(h.articleId);
        const entry = ensureHighlightEntry(map, h.articleId);
        (h.phrases || []).forEach(function (phrase) {
          if (phrase && phrase.skipHighlight) return;
          const normalized = normalizePhrase(phrase, item);
          const key =
            (normalized.text || "") +
            "|" +
            (normalized.locator || "") +
            "|" +
            (normalized.amendedDate || "");
          const exists = entry.phrases.some(function (p) {
            return (
              (p.text || "") +
                "|" +
                (p.locator || "") +
                "|" +
                (p.amendedDate || "") ===
              key
            );
          });
          if (!exists && normalized.text) entry.phrases.push(normalized);
        });
      });

      // 시행 완료로 highlights 가 비었지만 compare 가 있으면 음영 복구
      // (퇴직급여법 제2조 「100명 미만」 등 — 개정 배지만 있고 노란 음영 없던 오류)
      if (item.articleLevel && (item.compareAfter || "").trim()) {
        const aid = firstArticleId(item);
        if (aid) {
          attachAmendment(aid);
          const entry = ensureHighlightEntry(map, aid);
          if (!entry.phrases.length) {
            entry.phrases.push(
              normalizePhrase(
                {
                  text: (item.compareAfter || "").trim(),
                  beforeText: (item.compareBefore || "").trim(),
                  pending: item.bodyApplied === false,
                  locator: item.articleNo || "",
                  amendedDate: item.amendedDate,
                  effectiveDate: item.effectiveDate,
                },
                item
              )
            );
          }
        }
      }
    });
    return map;
  }

  /**
   * 3단에 실제로 펼쳐지는 고유 조문 키 집합.
   * 동일 조에 공포가 여러 번 있어도 1건(홈·상세·단별 건수 공통).
   */
  function collectDisplayedArticleKeys(lawId, baseDate) {
    const map = buildHighlightMap(lawId, baseDate);
    const items = getDetailAmendmentsForLaw(lawId, baseDate);
    const keys = {};
    Object.keys(map).forEach(function (aid) {
      keys[aid] = true;
    });
    items.forEach(function (item) {
      const aid = firstArticleId(item);
      if (aid && keys[aid]) return;
      if (item.articleLevel || hasPhraseHighlights(item)) {
        keys[aid || "extra:" + item.id] = true;
      }
    });
    return keys;
  }

  function countDisplayedArticlesForLaw(lawId, baseDate) {
    return Object.keys(collectDisplayedArticleKeys(lawId, baseDate)).length;
  }

  /** 고유 조문을 법률·시행령·시행규칙 단별로 집계 */
  function countDisplayedArticlesByTier(lawId, baseDate) {
    const items = getDetailAmendmentsForLaw(lawId, baseDate);
    const keys = collectDisplayedArticleKeys(lawId, baseDate);
    const buckets = { 법률: {}, 시행령: {}, 시행규칙: {} };

    function tierOf(key) {
      if (String(key).indexOf("extra:") === 0) {
        const id = String(key).slice(6);
        const hit = items.find(function (it) {
          return it.id === id;
        });
        return (hit && hit.tier) || "법률";
      }
      const hit = items.find(function (it) {
        return (
          (it.articleIds || []).indexOf(key) >= 0 ||
          (it.highlights || []).some(function (h) {
            return h.articleId === key;
          })
        );
      });
      return (hit && hit.tier) || "법률";
    }

    Object.keys(keys).forEach(function (key) {
      const t = tierOf(key);
      if (buckets[t]) buckets[t][key] = true;
    });

    return {
      법률: Object.keys(buckets["법률"]).length,
      시행령: Object.keys(buckets["시행령"]).length,
      시행규칙: Object.keys(buckets["시행규칙"]).length,
    };
  }

  function renderAmendmentMeta(highlightInfo) {
    if (!highlightInfo || !highlightInfo.amendments.length) return "";
    // 4법 공통: 안내문은 한 줄만 (개정일·시행일·중복 힌트 없음)
    return (
      '<div class="amend-meta">' +
      '<p class="amend-note">개정·신설된 항·호만 노란 음영으로 표시합니다. 마우스를 올리면 개정 전 내용을 확인할 수 있습니다.</p>' +
      "</div>"
    );
  }

  /** 미시행 신설 등 현행 본문이 비어 있을 때 개정문(compareAfter/phrase)로 표시 본문 확보 */
  function resolveDisplayBody(article, highlightInfo) {
    const body = (article && article.body) || "";
    if (body.trim()) return body;
    if (!highlightInfo) return "";
    const phrases = highlightInfo.phrases || [];
    let best = "";
    phrases.forEach(function (p) {
      if (!p || !p.text) return;
      if (p.pending && p.isNew && p.text.length > best.length) best = p.text;
    });
    if (best) return best;
    (highlightInfo.amendments || []).forEach(function (am) {
      const after = (am && am.compareAfter) || "";
      const before = (am && am.compareBefore) || "";
      if (
        after &&
        after.length > best.length &&
        (/신설/.test(before) || /신설/.test(am.summary || "") || /신설/.test(am.briefSummary || ""))
      ) {
        best = after;
      }
    });
    return best;
  }

  /* ---------- header menu ---------- */
  function initMenu() {
    const toggle = document.getElementById("menuToggle");
    const nav = document.getElementById("mainNav");
    if (!toggle || !nav) return;

    toggle.addEventListener("click", function () {
      const open = nav.classList.toggle("is-open");
      toggle.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
    });

    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("is-open");
      });
    });
  }

  /* ---------- home: overview + panel views ---------- */
  const HOME_PANELS = [
    "amendments",
    "laws",
    "upcoming",
    "notices",
    "compilations",
    "faqs",
  ];

  const PANEL_NOTES = {
    amendments: "공포 · 시행 ±6개월",
    laws: "조문 3단 대조 · 노란 음영",
    upcoming: "시행일 요약 · 조문 대조 연동",
    notices: "입법예고",
    compilations: "분야별 질의회시 PDF",
    faqs: "고용노동부 FAQ 조회수 상위",
  };

  function getPanelFromHash() {
    const hash = (window.location.hash || "").replace(/^#/, "");
    return HOME_PANELS.indexOf(hash) !== -1 ? hash : "";
  }

  function setNavActive(panelId) {
    document.querySelectorAll("[data-nav]").forEach(function (link) {
      link.classList.toggle("is-active", link.getAttribute("data-nav") === panelId);
    });
  }

  function updateOverviewPreviews(baseDate) {
    const date = baseDate || getBaseDateBounds().today;
    const setText = function (key, text) {
      const el = document.querySelector('[data-overview="' + key + '"]');
      if (el) el.textContent = text;
    };

    const faqTop = sortByViews(DATA.consultations).slice(0, CONSULT_TOP_N);
    if (faqTop.length) {
      setText(
        "faqs",
        "조회수 상위 " + faqTop.length + "건 · " + (faqTop[0].title || "")
      );
    }

    const comps = DATA.compilations || [];
    if (comps.length) {
      const latest = comps.slice().sort(function (a, b) {
        return parseYMD(b.date) - parseYMD(a.date);
      })[0];
      setText(
        "compilations",
        comps.length + "건 · 최근 " + (latest.title || "")
      );
    }

    const upcoming = filterUpcoming(date);
    setText(
      "upcoming",
      upcoming.length
        ? "요약 " +
            upcoming.length +
            "건 · 최근접 D-" +
            Math.round(
              (parseYMD(upcoming[0].effectiveDate) - date) / (24 * 60 * 60 * 1000)
            ) +
            " · " +
            (upcoming[0].lawName || upcoming[0].title || "")
        : "기준일 이후 시행 예정 없음"
    );

    const notices = (DATA.notices || []).slice().sort(function (a, b) {
      return parseYMD(b.date) - parseYMD(a.date);
    });
    if (notices.length) {
      setText(
        "notices",
        notices.length + "건 · 최근 " + (notices[0].title || "")
      );
    }

    const amends = filterRecentAmendments(date);
    setText(
      "amendments",
      amends.length
        ? "공포·시행 ±6개월 " + amends.length + "건 · " + (amends[0].title || "")
        : "공포 · 시행 ±6개월 내 개정 없음"
    );

    const laws = DATA.laws || [];
    const base = date;
    let articleTotal = 0;
    const touched = laws.filter(function (law) {
      const n = countDisplayedArticlesForLaw(law.id, base);
      articleTotal += n;
      return n > 0;
    }).length;
    setText(
      "laws",
      laws.length
        ? "법령군 " +
            laws.length +
            "개 · 조문 3단 " +
            touched +
            "개 · 개정 조문 " +
            articleTotal +
            "건"
        : "등록된 법령 없음"
    );
  }

  function showHomeOverview(options) {
    const opts = options || {};
    const overview = document.getElementById("homeOverview");
    const stage = document.getElementById("panelStage");
    if (!overview || !stage) return;

    document.body.classList.add("is-home-view");
    document.body.classList.remove("is-panel-view");
    setNavActive("");

    stage.hidden = true;
    stage.classList.remove("is-switching");
    document.querySelectorAll(".panel").forEach(function (panel) {
      panel.hidden = true;
    });

    overview.hidden = false;
    overview.classList.remove("is-leaving");
    void overview.offsetWidth;
    overview.classList.add("is-entering");

    if (!opts.keepHash && window.location.hash) {
      history.replaceState(null, "", window.location.pathname + window.location.search);
    }

    window.scrollTo({ top: 0, behavior: opts.instant ? "auto" : "smooth" });
  }

  function showHomePanel(panelId, options) {
    const opts = options || {};
    if (HOME_PANELS.indexOf(panelId) === -1) {
      showHomeOverview(opts);
      return;
    }

    const overview = document.getElementById("homeOverview");
    const stage = document.getElementById("panelStage");
    const note = document.getElementById("panelNote");
    if (!overview || !stage) return;

    const wasPanel = document.body.classList.contains("is-panel-view");
    const applyPanel = function () {
      document.body.classList.remove("is-home-view");
      document.body.classList.add("is-panel-view");
      overview.hidden = true;
      overview.classList.remove("is-leaving");
      stage.hidden = false;

      document.querySelectorAll(".panel").forEach(function (panel) {
        panel.hidden = panel.getAttribute("data-panel") !== panelId;
      });

      if (note) note.textContent = PANEL_NOTES[panelId] || "";
      setNavActive(panelId);

      stage.classList.remove("is-switching");
      void stage.offsetWidth;
      stage.classList.add(wasPanel ? "is-switching" : "is-entering");

      if (!opts.skipHash && window.location.hash !== "#" + panelId) {
        history.pushState(null, "", "#" + panelId);
      }

      window.scrollTo({ top: 0, behavior: opts.instant ? "auto" : "smooth" });
    };

    if (!wasPanel && !overview.hidden) {
      overview.classList.add("is-leaving");
      window.setTimeout(applyPanel, 220);
    } else {
      applyPanel();
    }
  }

  function initHomeViews() {
    if (!document.getElementById("homeOverview")) return;

    const back = document.getElementById("panelBack");
    if (back) {
      back.addEventListener("click", function () {
        showHomeOverview();
      });
    }

    const logo = document.getElementById("homeLogo");
    if (logo) {
      logo.addEventListener("click", function (e) {
        if (!document.getElementById("homeOverview")) return;
        e.preventDefault();
        showHomeOverview();
      });
    }

    document.addEventListener("click", function (e) {
      const link = e.target.closest('a[href^="#"]');
      if (!link) return;
      const id = (link.getAttribute("href") || "").replace(/^#/, "");
      if (HOME_PANELS.indexOf(id) === -1) return;
      e.preventDefault();
      showHomePanel(id);
    });

    window.addEventListener("hashchange", function () {
      const panel = getPanelFromHash();
      if (panel) showHomePanel(panel, { skipHash: true });
      else showHomeOverview({ keepHash: true });
    });

    window.addEventListener("popstate", function () {
      const panel = getPanelFromHash();
      if (panel) showHomePanel(panel, { skipHash: true, instant: true });
      else showHomeOverview({ keepHash: true, instant: true });
    });

    const initial = getPanelFromHash();
    if (initial) showHomePanel(initial, { skipHash: true, instant: true });
    else showHomeOverview({ keepHash: true, instant: true });
  }

  /* ---------- home: 자주하는 질문 ---------- */
  function formatViews(n) {
    return Number(n || 0).toLocaleString("ko-KR");
  }

  function sortByViews(list) {
    return (list || [])
      .slice()
      .sort(function (a, b) {
        return (b.views || 0) - (a.views || 0);
      });
  }

  function renderFaqs() {
    const root = document.getElementById("faqsRoot");
    if (!root) return;

    const items = sortByViews(DATA.consultations).slice(0, CONSULT_TOP_N);
    if (!items.length) {
      root.innerHTML = '<div class="empty-state">자주하는 질문 데이터가 없습니다.</div>';
      return;
    }

    const footnote =
      DATA.consultationsMeta && DATA.consultationsMeta.viewsBasis
        ? '<p class="consult-footnote">' + escapeHtml(DATA.consultationsMeta.viewsBasis) + "</p>"
        : "";

    root.innerHTML =
      '<ol class="consult-list">' +
      items
        .map(function (item, index) {
          return (
            '<li class="consult-item">' +
            '<a class="consult-item__linkcard" href="consult.html?id=' +
            encodeURIComponent(item.id) +
            '">' +
            '<span class="consult-item__rank" aria-label="' +
            (index + 1) +
            '위">' +
            (index + 1) +
            "</span>" +
            '<div class="consult-item__body">' +
            '<div class="consult-item__meta">' +
            '<span class="badge badge--source">' +
            escapeHtml(item.source || "") +
            "</span>" +
            '<span class="consult-item__cat">' +
            escapeHtml(item.category || "") +
            "</span>" +
            "</div>" +
            '<h3 class="consult-item__title">' +
            escapeHtml(item.title) +
            "</h3>" +
            '<span class="consult-item__cta">답변 보기 →</span>' +
            "</div>" +
            '<div class="consult-item__views"><em>조회</em><strong>' +
            formatViews(item.views) +
            '</strong><span class="consult-item__views-basis">고용부 FAQ</span></div>' +
            "</a></li>"
          );
        })
        .join("") +
      "</ol>" +
      footnote;
  }

  function renderConsultDetail() {
    const root = document.getElementById("consultDetailRoot");
    if (!root) return;

    const list = DATA.consultations || [];
    const id = getQueryParam("id");
    const item =
      list.find(function (c) {
        return c.id === id;
      }) || list[0];

    if (!item) {
      root.innerHTML =
        '<div class="container"><div class="empty-state">자주하는 질문을 찾을 수 없습니다.</div></div>';
      return;
    }

    document.title = item.title + " — 자주하는 질문";

    const titleEl = document.getElementById("consultTitle");
    const metaEl = document.getElementById("consultMeta");
    const eyeEl = document.getElementById("consultEyebrow");
    const navFaq = document.getElementById("navFaq");

    if (titleEl) titleEl.textContent = item.title;
    if (eyeEl) eyeEl.textContent = (item.source || "") + " · " + (item.category || "");
    if (navFaq) navFaq.classList.add("is-active");
    if (metaEl) {
      metaEl.innerHTML =
        "조회 " +
        formatViews(item.views) +
        " <span class='page-hero__note'>(" +
        escapeHtml(item.viewsBasis || "고용노동부 FAQ 표기") +
        ")</span>" +
        (item.relatedLaw ? "<br>관련 " + escapeHtml(item.relatedLaw) : "");
    }

    root.innerHTML =
      '<div class="container consult-detail__inner">' +
      '<section class="consult-block consult-block--q">' +
      '<h2 class="consult-block__label">질문</h2>' +
      '<p class="consult-block__text consult-block__text--pre">' +
      escapeHtml(item.question || item.title || "") +
      "</p></section>" +
      '<section class="consult-block consult-block--a">' +
      '<h2 class="consult-block__label">답변 (고용노동부 FAQ)</h2>' +
      '<div class="consult-block__text consult-block__text--pre">' +
      escapeHtml(item.answer || "등록된 내용이 없습니다. 아래 원문에서 확인하세요.") +
      "</div></section>" +
      '<div class="consult-detail__actions">' +
      '<a class="btn--sm" href="index.html#faqs">목록으로</a>' +
      (item.url
        ? '<a class="btn--sm btn--source" href="' +
          escapeHtml(item.url) +
          '" target="_blank" rel="noopener">고용노동부 원문(해당 FAQ) 열기</a>'
        : "") +
      "</div>" +
      '<p class="consult-detail__disclaimer">「고용노동부 원문 열기」는 해당 FAQ 상세 페이지로 이동합니다. 조회수는 고용노동부 자주하는 질문 목록 표기값입니다.</p>' +
      "</div>";
  }

  /* ---------- home: 질의회시집 / 시행예정 / 예고 ---------- */
  function renderCompilations() {
    const root = document.getElementById("compilationsRoot");
    if (!root) return;

    const items = (DATA.compilations || []).slice().sort(function (a, b) {
      return parseYMD(b.date) - parseYMD(a.date);
    });

    if (!items.length) {
      root.innerHTML = '<div class="empty-state">등록된 질의회시집이 없습니다.</div>';
      return;
    }

    root.innerHTML =
      '<ul class="resource-list">' +
      items
        .map(function (item) {
          return (
            '<li class="resource-item">' +
            '<a class="resource-item__link" href="' +
            escapeHtml(item.url) +
            '" target="_blank" rel="noopener">' +
            '<div class="resource-item__meta">' +
            '<span class="badge badge--source">PDF</span>' +
            '<span class="resource-item__cat">' +
            escapeHtml(item.category || "") +
            "</span>" +
            "<span>" +
            escapeHtml((item.date || "").replace(/-/g, ".")) +
            "</span>" +
            (item.dept ? "<span>" + escapeHtml(item.dept) + "</span>" : "") +
            "</div>" +
            '<h3 class="resource-item__title">' +
            escapeHtml(item.title) +
            "</h3>" +
            '<p class="resource-item__summary">' +
            escapeHtml(item.summary || "") +
            "</p>" +
            '<span class="resource-item__cta">원문·PDF 보기 →</span>' +
            "</a></li>"
          );
        })
        .join("") +
      "</ul>" +
      (DATA.compilationsMeta && DATA.compilationsMeta.note
        ? '<p class="consult-footnote">' + escapeHtml(DATA.compilationsMeta.note) + "</p>"
        : "");
  }

  function resolveUpcomingArticle(item) {
    return firstArticleId(item);
  }

  function filterUpcoming(baseDate) {
    const base = startOfDay(baseDate);
    const seen = {};
    const fromAmends = getAmendmentSource()
      .filter(function (item) {
        if (!item.effectiveDate) return false;
        return parseYMD(item.effectiveDate) > base;
      })
      .map(function (item) {
        return {
          id: item.id,
          lawId: item.lawId,
          lawName: item.lawName,
          tier: item.tier,
          title: item.title,
          amendedDate: item.amendedDate,
          effectiveDate: item.effectiveDate,
          summary: item.summary,
          briefSummary: item.briefSummary || "",
          locators: item.locators || [],
          status: "시행예정",
          sourceUrl: item.sourceUrl || "",
          articleId: resolveUpcomingArticle(item),
          fromAmendment: true,
        };
      });

    fromAmends.forEach(function (item) {
      seen[item.lawId + "|" + item.effectiveDate + "|" + (item.title || "")] = true;
    });

    const extras = (DATA.upcomingLaws || [])
      .filter(function (item) {
        if (!item.effectiveDate) return false;
        if (parseYMD(item.effectiveDate) <= base) return false;
        const key = item.lawId + "|" + item.effectiveDate + "|" + (item.title || "");
        return !seen[key];
      })
      .map(function (item) {
        return {
          id: item.id,
          lawId: item.lawId,
          lawName: item.lawName,
          tier: item.tier,
          title: item.title,
          amendedDate: item.amendedDate,
          effectiveDate: item.effectiveDate,
          summary: item.summary,
          briefSummary: item.summary ? item.summary.slice(0, 90) + "…" : "",
          locators: [],
          status: "시행예정",
          sourceUrl: item.url || "",
          articleId: resolveUpcomingArticle(item),
          fromAmendment: false,
        };
      });

    return fromAmends.concat(extras).sort(function (a, b) {
      return parseYMD(a.effectiveDate) - parseYMD(b.effectiveDate);
    });
  }

  function makeBriefSummary(item) {
    if (item.briefSummary) return item.briefSummary;
    const raw = (item.summary || "").replace(/\s+/g, " ").trim();
    if (!raw) return "시행 예정 개정 내용입니다. 조문 대조에서 상세를 확인하세요.";
    if (raw.length <= 90) return raw;
    return raw.slice(0, 89).replace(/[,·\s]+$/, "") + "…";
  }

  function renderUpcoming(baseDate) {
    const root = document.getElementById("upcomingRoot");
    const rangeEl = document.getElementById("upcomingRange");
    if (!root) return;

    if (rangeEl) {
      rangeEl.textContent = "기준일 " + formatDate(baseDate) + " 이후 시행 · 한 줄 요약";
    }

    const items = filterUpcoming(baseDate);
    if (!items.length) {
      root.innerHTML =
        '<div class="empty-state">기준일 이후 시행 예정인 법령이 없습니다. 「최근 개정」에서 수동 갱신 후 다시 확인해 주세요.</div>';
      return;
    }

    root.innerHTML =
      '<div class="upcoming-brief">' +
      '<p class="upcoming-brief__lead">시행일·D-day와 핵심 요약만 모았습니다. 상세 조·항 음영은 「개정 조문 보기」에서 확인하세요.</p>' +
      '<ul class="upcoming-brief__list">' +
      items
        .map(function (item) {
          const daysLeft = Math.round(
            (parseYMD(item.effectiveDate) - baseDate) / (24 * 60 * 60 * 1000)
          );
          const detailHref = item.lawId
            ? "law.html?id=" +
              encodeURIComponent(item.lawId) +
              (item.articleId ? "&article=" + encodeURIComponent(item.articleId) : "")
            : item.sourceUrl || "#";
          const loc =
            item.locators && item.locators.length
              ? item.locators.slice(0, 3).join(" · ")
              : "";
          return (
            '<li class="upcoming-brief__item">' +
            '<div class="upcoming-brief__when">' +
            '<span class="upcoming-brief__dday">D-' +
            daysLeft +
            "</span>" +
            "<span>시행 " +
            escapeHtml(formatDotDate(item.effectiveDate)) +
            "</span>" +
            "</div>" +
            '<div class="upcoming-brief__main">' +
            '<p class="upcoming-brief__law">' +
            escapeHtml(item.lawName || "") +
            (item.tier ? " · " + escapeHtml(item.tier) : "") +
            (loc ? " · " + escapeHtml(loc) : "") +
            "</p>" +
            '<p class="upcoming-brief__summary">' +
            escapeHtml(makeBriefSummary(item)) +
            "</p>" +
            "</div>" +
            '<a class="upcoming-brief__link" href="' +
            escapeHtml(detailHref) +
            '">개정 조문 보기</a>' +
            "</li>"
          );
        })
        .join("") +
      "</ul></div>";
  }

  function renderNotices() {
    const root = document.getElementById("noticesRoot");
    if (!root) return;

    const items = (DATA.notices || []).slice().sort(function (a, b) {
      return parseYMD(b.date) - parseYMD(a.date);
    });

    if (!items.length) {
      root.innerHTML = '<div class="empty-state">등록된 예고가 없습니다.</div>';
      return;
    }

    root.innerHTML =
      '<ul class="resource-list">' +
      items
        .map(function (item) {
          const typeClass = item.type === "행정" ? "badge--admin" : "badge--live";
          return (
            '<li class="resource-item">' +
            '<a class="resource-item__link" href="' +
            escapeHtml(item.url) +
            '" target="_blank" rel="noopener">' +
            '<div class="resource-item__meta">' +
            '<span class="badge ' +
            typeClass +
            '">' +
            escapeHtml(item.type || "예고") +
            "</span>" +
            (item.dept ? "<span>" + escapeHtml(item.dept) + "</span>" : "") +
            "<span>" +
            escapeHtml((item.date || "").replace(/-/g, ".")) +
            "</span>" +
            (item.views
              ? "<span>조회 " + formatViews(item.views) + "</span>"
              : "") +
            "</div>" +
            '<h3 class="resource-item__title">' +
            escapeHtml(item.title) +
            "</h3>" +
            '<p class="resource-item__summary">' +
            escapeHtml(item.summary || "") +
            "</p>" +
            '<span class="resource-item__cta">예고 원문 보기 →</span>' +
            "</a></li>"
          );
        })
        .join("") +
      "</ul>" +
      (DATA.noticesMeta && DATA.noticesMeta.note
        ? '<p class="consult-footnote">' + escapeHtml(DATA.noticesMeta.note) + "</p>"
        : "");
  }

  /* ---------- home: amendments from base date through +1 year ---------- */
  function getBaseDateBounds() {
    const today = startOfDay(new Date());
    const minDate = addMonths(today, -MAX_MONTHS_BACK);
    return { today: today, minDate: minDate, maxDate: today };
  }

  function clampBaseDate(date) {
    const bounds = getBaseDateBounds();
    let d = startOfDay(date);
    if (d < bounds.minDate) d = bounds.minDate;
    if (d > bounds.maxDate) d = bounds.maxDate;
    return d;
  }

  function getAmendmentSource() {
    if (liveAmendments && liveAmendments.length) return liveAmendments;
    return bundledAmendments;
  }

  /** 성공한 갱신 캐시인지(실패·차단 건은 갱신 시각에 쓰지 않음) */
  function isSuccessfulRefreshPayload(payload) {
    if (!payload || !Array.isArray(payload.amendments) || !payload.amendments.length) {
      return false;
    }
    const sc = payload.selfCheck || {};
    if (sc.commitBlocked) return false;
    if (sc.ok === false) return false;
    const sim = sc.simulation || {};
    if (sim.passed === false) return false;
    // 구버전 캐시(selfCheck 없음)는 amendments 가 있으면 성공으로 본다
    return true;
  }

  /** 마지막 성공 갱신 시각 표시 (YYYY-MM-DD HH:mm:ss) */
  function formatRefreshAt(iso) {
    const raw = String(iso || "").trim();
    if (!raw) return "";
    return raw.replace("T", " ").replace(/\.\d+/, "").replace(/([+-]\d{2}:\d{2}|Z)$/i, "");
  }

  function applyLiveAmendments(payload) {
    if (!payload || !Array.isArray(payload.amendments)) return false;
    const success = isSuccessfulRefreshPayload(payload);
    // 데이터는 표시하되, 갱신 시각은 성공 건만 반영
    const prevAt =
      (liveAmendmentsMeta && liveAmendmentsMeta.fetchedAt) ||
      window.__lastFetchedAt ||
      "";
    const nextAt = success ? payload.fetchedAt || prevAt || "" : prevAt;
    // 최근 개정 목록만 라이브로 갱신. 주요 법령 조문 대조(curated)는 덮어쓰지 않음.
    liveAmendments = payload.amendments;
    liveAmendmentsMeta = {
      baseDate: payload.baseDate || "",
      from: payload.from || "",
      to: payload.to || "",
      fetchedAt: nextAt,
      count: payload.count || payload.amendments.length,
      live: true,
      refreshOk: success,
    };
    if (success && nextAt) {
      window.__lastFetchedAt = nextAt;
    }
    return true;
  }

  function filterAmendments(baseDate) {
    const base = baseDate || currentBaseDate || getBaseDateBounds().today;
    return getAmendmentSource()
      .filter(function (item) {
        return isInAmendmentWindow(item, base);
      })
      .sort(function (a, b) {
        return parseYMD(b.amendedDate) - parseYMD(a.amendedDate);
      });
  }

  function renderAmendmentList(baseDate) {
    const root = document.getElementById("amendmentsRoot");
    const rangeEl = document.getElementById("amendmentRange");
    if (!root) return;

    currentBaseDate = baseDate;
    const from = getRangeStart(baseDate);
    const to = getRangeEnd(baseDate);

    if (rangeEl) {
      let text =
        "기준일 " +
        formatDate(baseDate) +
        " · 조회 " +
        formatDate(from) +
        " ~ " +
        formatDate(to) +
        " (공포 · 시행 ±6개월)";
      const refreshed = formatRefreshAt(
        liveAmendmentsMeta && liveAmendmentsMeta.fetchedAt
      );
      if (refreshed) {
        text += " · 갱신 " + refreshed;
      }
      rangeEl.textContent = text;
    }

    const filtered = filterRecentAmendments(baseDate);

    if (!filtered.length) {
      root.innerHTML =
        '<div class="empty-state">기준일 기준 공포 또는 시행 ±6개월 범위에 해당하는 개정이 없습니다. 「지금 갱신」으로 최신 이력을 가져올 수 있습니다.</div>';
      return;
    }

    root.innerHTML = `
      <ul class="amend-list">
        ${filtered
          .map(function (item) {
            const badgeClass = item.status === "시행예정" ? "badge--soon" : "badge--live";
            const firstArticle =
              (item.articleIds && item.articleIds[0]) ||
              (item.highlights && item.highlights[0] && item.highlights[0].articleId) ||
              "";
            const detailHref =
              "law.html?id=" +
              encodeURIComponent(item.lawId) +
              "&amend=" +
              encodeURIComponent(item.id) +
              (firstArticle ? "&article=" + encodeURIComponent(firstArticle) : "");
            const locs = [];
            (item.locators || []).forEach(function (loc) {
              if (loc && locs.indexOf(loc) === -1) locs.push(loc);
            });
            (item.mentionedArticles || []).forEach(function (loc) {
              if (loc && locs.indexOf(loc) === -1) locs.push(loc);
            });
            (item.highlights || []).forEach(function (h) {
              (h.phrases || []).forEach(function (ph) {
                if (ph.locator && locs.indexOf(ph.locator) === -1) locs.push(ph.locator);
              });
            });
            const changeSummary = makeChangeBrief(item);
            return `
            <li class="amend-item">
              <div class="amend-item__date">
                <span class="amend-item__date-label">개정</span>
                ${escapeHtml(item.amendedDate.replace(/-/g, "."))}
                <span class="amend-item__eff">시행 ${escapeHtml(
                  item.effectiveDate.replace(/-/g, ".")
                )}</span>
              </div>
              <div class="amend-item__body">
                <div class="amend-item__meta">
                  <span class="badge badge--tier">${escapeHtml(item.tier)}</span>
                  ${escapeHtml(item.lawName)}
                  ${item.revisionType ? " · " + escapeHtml(item.revisionType) : ""}
                  ${
                    item.noticeNo
                      ? " · " +
                        escapeHtml((item.instrument || "법률") + " 제" + item.noticeNo + "호")
                      : ""
                  }
                </div>
                <h3 class="amend-item__title">
                  <a class="amend-item__detail-link" href="${detailHref}">${escapeHtml(item.title)}</a>
                </h3>
                ${
                  locs.length
                    ? '<p class="amend-item__locators">' +
                      escapeHtml(locs.slice(0, 6).join(" · ")) +
                      "</p>"
                    : ""
                }
                <p class="amend-item__summary">${escapeHtml(changeSummary)}</p>
                ${renderCompareBlock(item)}
              </div>
              <div class="amend-item__aside">
                <span class="badge ${badgeClass}">${escapeHtml(item.status)}</span>
                ${
                  item.sourceUrl
                    ? '<a class="amend-item__source" href="' +
                      escapeHtml(item.sourceUrl) +
                      '" target="_blank" rel="noopener">원문보기</a>'
                    : ""
                }
              </div>
            </li>`;
          })
          .join("")}
      </ul>
    `;
  }

  function setRefreshStatus(message, isError) {
    const el = document.getElementById("amendmentRefreshStatus");
    if (!el) return;
    el.textContent = message || "";
    el.classList.toggle("is-error", !!isError);
  }

  function applyLiveNotices(payload) {
    if (!payload || !Array.isArray(payload.notices) || !payload.notices.length) {
      return false;
    }
    DATA.notices = payload.notices;
    DATA.noticesMeta = Object.assign({}, DATA.noticesMeta || {}, {
      sourcePortal: payload.sourcePortal || (DATA.noticesMeta && DATA.noticesMeta.sourcePortal),
      note: payload.note || (DATA.noticesMeta && DATA.noticesMeta.note),
      fetchedAt: payload.fetchedAt,
      baseDate: payload.baseDate,
    });
    return true;
  }

  function loadNoticesCache() {
    return fetch(NOTICES_CACHE_URL + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("notices cache missing");
        return res.json();
      })
      .then(function (payload) {
        if (applyLiveNotices(payload)) {
          renderNotices();
        }
      })
      .catch(function () {
        /* keep bundled DATA.notices */
      });
  }

  function loadAmendmentsCache() {
    return fetch(AMENDMENTS_CACHE_URL + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("cache missing");
        return res.json();
      })
      .then(function (payload) {
        if (!payload || !Array.isArray(payload.amendments) || !payload.amendments.length) {
          return;
        }
        // 실패 캐시면 목록은 쓰되 갱신 시각은 올리지 않음(applyLiveAmendments 내부 처리)
        if (applyLiveAmendments(payload)) {
          const at = formatRefreshAt(
            liveAmendmentsMeta && liveAmendmentsMeta.fetchedAt
          );
          const ok = isSuccessfulRefreshPayload(payload);
          setRefreshStatus(
            (ok ? "저장된 수동갱신 데이터 " : "이전 성공 데이터 표시 · ") +
              (payload.count || payload.amendments.length) +
              "건 (수집 기준일 " +
              (payload.baseDate || "") +
              " · " +
              (payload.from || "") +
              " ~ " +
              (payload.to || "") +
              ")" +
              (at ? " · 마지막 갱신 " + at : "") +
              (ok
                ? ". 기준일이 바뀌면 「수동 갱신」을 다시 실행하세요."
                : ". 최근 갱신이 실패해 시각을 갱신하지 않았습니다.")
          );
        }
      })
      .catch(function () {
        /* keep bundled DATA.amendments */
      });
  }

  function refreshApiCandidates(base) {
    const q = "?base=" + encodeURIComponent(base);
    const urls = [];
    if (location.protocol === "http:" || location.protocol === "https:") {
      urls.push(location.origin + "/api/refresh" + q);
      urls.push(location.origin + "/refresh" + q);
    }
    urls.push(REFRESH_HOST + "/api/refresh" + q);
    urls.push(REFRESH_HOST + "/refresh" + q);
    return urls.filter(function (url, idx, arr) {
      return arr.indexOf(url) === idx;
    });
  }

  function postRefresh(url) {
    return fetch(url, { method: "POST", cache: "no-store" }).then(function (res) {
      return res.json().then(function (body) {
        if (!res.ok || !body || !body.ok) {
          throw new Error((body && body.error) || "갱신 실패 (" + res.status + ")");
        }
        return body;
      });
    });
  }

  function tryRefreshEndpoints(base) {
    const urls = refreshApiCandidates(base);
    let chain = Promise.reject(new Error("no endpoint"));
    urls.forEach(function (url) {
      chain = chain.catch(function () {
        return postRefresh(url);
      });
    });
    return chain;
  }

  function checkServerHealth() {
    return fetch(REFRESH_HOST + "/health", { cache: "no-store" })
      .then(function (res) {
        return res.ok;
      })
      .catch(function () {
        return false;
      });
  }

  function launchLocalServerHelper() {
    try {
      const frame = document.createElement("iframe");
      frame.style.display = "none";
      frame.src = ENSURE_SERVER_HREF + "?t=" + Date.now();
      document.body.appendChild(frame);
      setTimeout(function () {
        if (frame.parentNode) frame.parentNode.removeChild(frame);
      }, 4000);
    } catch (e) {
      /* ignore */
    }
    try {
      const a = document.createElement("a");
      a.href = ENSURE_SERVER_HREF;
      a.target = "_blank";
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e2) {
      /* ignore */
    }
  }

  function waitForServer(timeoutMs) {
    const started = Date.now();
    function loop() {
      return checkServerHealth().then(function (ok) {
        if (ok) return true;
        if (Date.now() - started >= timeoutMs) return false;
        return new Promise(function (resolve) {
          setTimeout(resolve, 700);
        }).then(loop);
      });
    }
    return loop();
  }

  function afterAmendmentsUpdated(baseDate) {
    renderAmendmentList(baseDate);
    renderLawLinks(baseDate);
    renderUpcoming(baseDate);
    updateOverviewPreviews(baseDate);
  }

  function isLocalRefreshHost() {
    const host = (location.hostname || "").toLowerCase();
    return (
      host === "127.0.0.1" ||
      host === "localhost" ||
      location.protocol === "file:"
    );
  }

  function getRefreshConfig() {
    return window.LAW_REFRESH || {};
  }

  function dispatchGithubRefresh(baseYmd) {
    const cfg = getRefreshConfig();
    const payload = {
      owner: cfg.owner || "Todayand-cloud",
      repo: cfg.repo || "TomorrowHR",
      workflowFile: cfg.workflowFile || "refresh-laws.yml",
      ref: cfg.ref || "main",
      base: baseYmd || "",
    };

    if (cfg.proxyUrl) {
      return fetch(cfg.proxyUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (res) {
        return res.json().then(function (body) {
          if (!res.ok || !body || !body.ok) {
            throw new Error((body && body.error) || "갱신 요청 실패 (" + res.status + ")");
          }
          return body;
        });
      });
    }

    if (cfg.githubToken) {
      const url =
        "https://api.github.com/repos/" +
        encodeURIComponent(payload.owner) +
        "/" +
        encodeURIComponent(payload.repo) +
        "/actions/workflows/" +
        encodeURIComponent(payload.workflowFile) +
        "/dispatches";
      return fetch(url, {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: "Bearer " + cfg.githubToken,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ref: payload.ref,
          inputs: payload.base ? { base: payload.base } : {},
        }),
      }).then(function (res) {
        if (res.status === 204 || res.ok) return { ok: true };
        return res.text().then(function (t) {
          throw new Error("GitHub " + res.status + ": " + String(t || "").slice(0, 180));
        });
      });
    }

    return Promise.reject(
      new Error(
        "갱신 연결이 없습니다. js/refresh-config.js 에 proxyUrl(권장) 또는 githubToken 을 설정한 뒤 다시 업로드하세요."
      )
    );
  }

  function sleepMs(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, ms);
    });
  }

  function pollUpdatedAmendmentsCache(prevFetchedAt, maxWaitMs) {
    const started = Date.now();
    const maxWait = maxWaitMs || 180000;

    function once() {
      const url = AMENDMENTS_CACHE_URL + "?t=" + Date.now();
      return fetch(url, { cache: "no-store" })
        .then(function (res) {
          if (!res.ok) throw new Error("캐시 확인 실패 (" + res.status + ")");
          return res.json();
        })
        .then(function (payload) {
          const next = payload && payload.fetchedAt;
          const ok = isSuccessfulRefreshPayload(payload);
          // 실패 캐시(시각만 바뀌거나 commitBlocked)는 성공으로 보지 않음
          if (ok && next && next !== prevFetchedAt) {
            return payload;
          }
          if (Date.now() - started > maxWait) {
            throw new Error(
              "갱신 작업이 아직 끝나지 않았습니다. 1~2분 뒤 새로고침 해 주세요."
            );
          }
          const elapsed = Math.round((Date.now() - started) / 1000);
          setRefreshStatus(
            ok
              ? "법제처 수집·배포 중… (" + elapsed + "초)"
              : "법제처 수집·배포 중… (" + elapsed + "초) · 성공 캐시 대기"
          );
          return sleepMs(5000).then(once);
        });
    }
    return once();
  }

  function refreshAmendmentsViaGithub(baseDate) {
    const btn = document.getElementById("amendmentRefresh");
    const base = toInputValue(baseDate);
    const prevFetched =
      (liveAmendmentsMeta && liveAmendmentsMeta.fetchedAt) ||
      (window.__lastFetchedAt || "");

    if (btn) btn.disabled = true;
    setRefreshStatus("갱신 요청 중…");

    return dispatchGithubRefresh(base)
      .then(function () {
        setRefreshStatus("법제처 수집·배포 중… (보통 1~3분)");
        return pollUpdatedAmendmentsCache(prevFetched, 210000);
      })
      .then(function (payload) {
        if (!isSuccessfulRefreshPayload(payload)) {
          throw new Error(
            "갱신은 끝났지만 검증에 실패해 성공 시각을 반영하지 않았습니다."
          );
        }
        applyLiveAmendments(payload);
        loadNoticesCache();
        afterAmendmentsUpdated(baseDate);
        // 조문 JS·예고 캐시도 최신으로 다시 받으려면 새로고침이 확실함
        setRefreshStatus(
          "갱신 완료 · " +
            (payload.count != null ? payload.count + "건 · " : "") +
            (formatRefreshAt(payload.fetchedAt)
              ? "시각 " + formatRefreshAt(payload.fetchedAt) + " · "
              : "") +
            "페이지를 다시 불러오는 중…"
        );
        setTimeout(function () {
          location.reload();
        }, 600);
      })
      .catch(function (err) {
        var msg = err && err.message ? String(err.message) : String(err);
        if (
          /Resource not accessible by personal access token/i.test(msg) ||
          /토큰 권한 부족/i.test(msg) ||
          (/GitHub 403/.test(msg) && /workflow_dispatch/i.test(msg))
        ) {
          msg =
            "GitHub 토큰 권한 부족. Classic PAT(repo+workflow)를 만들고 Cloudflare Worker Secret「GITHUB_TOKEN」을 교체한 뒤 Worker 코드를 다시 Deploy 하세요. " +
            "임시로 Actions에서 Refresh law data → Run workflow 도 가능합니다.";
        }
        setRefreshStatus("갱신 실패: " + msg, true);
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  function refreshAmendmentsFromServer(baseDate) {
    const btn = document.getElementById("amendmentRefresh");
    const base = toInputValue(baseDate);

    // GitHub Pages 등: Actions로 수집·커밋 후 캐시 반영
    if (!isLocalRefreshHost()) {
      return refreshAmendmentsViaGithub(baseDate);
    }

    if (btn) btn.disabled = true;
    setRefreshStatus("국가법령정보센터에서 기준일 ±6개월 이력을 가져오는 중…");

    function finishOk(body) {
      if (!body || body.ok === false || !isSuccessfulRefreshPayload(body)) {
        throw new Error(
          (body && body.error) ||
            "갱신 검증 실패 — 마지막 성공 갱신 시각을 유지합니다."
        );
      }
      applyLiveAmendments(body);
      loadNoticesCache();
      afterAmendmentsUpdated(baseDate);
      const audit = body.audit || {};
      const check = body.selfCheck || {};
      const matched = audit.matchedHighlights != null ? audit.matchedHighlights : 0;
      const checkOk = check.ok !== false;
      const at = formatRefreshAt(body.fetchedAt);
      setRefreshStatus(
        "법제처 신규 수집 완료 · " +
          body.count +
          "건 (" +
          body.from +
          " ~ " +
          body.to +
          ") · 조문연혁 일치 하이라이트 " +
          matched +
          "건" +
          (checkOk ? " · 자체검증 통과" : " · 자체검증 경고 있음") +
          (at ? " · 갱신 " + at : "")
      );
      if (location.protocol === "file:") {
        setTimeout(function () {
          setRefreshStatus(
            "법제처 신규 수집 완료 · " +
              body.count +
              "건 · 하이라이트 " +
              matched +
              "건" +
              (at ? " · 갱신 " + at : "") +
              ". 이후에도 버튼만으로 갱신하려면 " +
              REFRESH_HOST +
              " 로 이용하세요."
          );
        }, 1400);
      }
    }

    return tryRefreshEndpoints(base)
      .catch(function () {
        setRefreshStatus("로컬 갱신 서버를 자동으로 켜는 중…");
        launchLocalServerHelper();
        return waitForServer(16000).then(function (ready) {
          if (!ready) {
            throw new Error(
              "로컬 서버(127.0.0.1:8787)에 연결되지 않았습니다. 「사이트실행.bat」을 실행한 뒤 http://127.0.0.1:8787 에서 열어 「지금 갱신」을 다시 눌러 주세요."
            );
          }
          setRefreshStatus("서버 연결됨 · 개정 이력 수집 중…");
          return tryRefreshEndpoints(base);
        });
      })
      .then(finishOk)
      .catch(function (err) {
        setRefreshStatus(
          "갱신 실패: " + (err && err.message ? err.message : err),
          true
        );
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  function initAmendments() {
    const input = document.getElementById("baseDateInput");
    const resetBtn = document.getElementById("baseDateReset");
    const trigger = document.getElementById("baseDateTrigger");
    const calendar = document.getElementById("baseDateCalendar");
    const valueEl = document.getElementById("baseDateValue");
    const calTitle = document.getElementById("calTitle");
    const calGrid = document.getElementById("calGrid");
    const calPrev = document.getElementById("calPrev");
    const calNext = document.getElementById("calNext");
    const picker = document.getElementById("baseDatePicker");

    if (!document.getElementById("amendmentsRoot")) return;

    const bounds = getBaseDateBounds();
    let baseDate = bounds.today;
    let viewYear = baseDate.getFullYear();
    let viewMonth = baseDate.getMonth();
    let open = false;

    function syncDisplay() {
      if (input) input.value = toInputValue(baseDate);
      if (valueEl) valueEl.textContent = formatDate(baseDate);
    }

    function setBaseDate(date, closeCalendar) {
      baseDate = clampBaseDate(date);
      currentBaseDate = baseDate;
      viewYear = baseDate.getFullYear();
      viewMonth = baseDate.getMonth();
      syncDisplay();
      renderFaqs();
      renderCompilations();
      renderUpcoming(baseDate);
      renderNotices();
      renderAmendmentList(baseDate);
      renderLawLinks(baseDate);
      updateOverviewPreviews(baseDate);
      renderCalendar();
      if (closeCalendar) setCalendarOpen(false);
    }

    function sameDay(a, b) {
      return (
        a.getFullYear() === b.getFullYear() &&
        a.getMonth() === b.getMonth() &&
        a.getDate() === b.getDate()
      );
    }

    function monthStart(y, m) {
      return new Date(y, m, 1);
    }

    function canGoPrev() {
      const prev = new Date(viewYear, viewMonth, 1);
      prev.setMonth(prev.getMonth() - 1);
      return prev >= monthStart(bounds.minDate.getFullYear(), bounds.minDate.getMonth());
    }

    function canGoNext() {
      const next = new Date(viewYear, viewMonth, 1);
      next.setMonth(next.getMonth() + 1);
      return next <= monthStart(bounds.maxDate.getFullYear(), bounds.maxDate.getMonth());
    }

    function renderCalendar() {
      if (!calGrid || !calTitle) return;

      calTitle.textContent = viewYear + "년 " + (viewMonth + 1) + "월";
      if (calPrev) calPrev.disabled = !canGoPrev();
      if (calNext) calNext.disabled = !canGoNext();

      const firstDay = new Date(viewYear, viewMonth, 1).getDay();
      const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      let html = "";

      for (let i = 0; i < firstDay; i++) {
        html += '<button type="button" class="cal-day is-outside" tabindex="-1" disabled></button>';
      }

      for (let day = 1; day <= daysInMonth; day++) {
        const date = new Date(viewYear, viewMonth, day);
        const disabled = date < bounds.minDate || date > bounds.maxDate;
        const selected = sameDay(date, baseDate);
        const today = sameDay(date, bounds.today);
        const classes = [
          "cal-day",
          date.getDay() === 0 ? "is-sun" : "",
          selected ? "is-selected" : "",
          today ? "is-today" : "",
        ]
          .filter(Boolean)
          .join(" ");

        html +=
          '<button type="button" class="' +
          classes +
          '" data-ymd="' +
          toInputValue(date) +
          '"' +
          (disabled ? " disabled" : "") +
          ' aria-label="' +
          formatDate(date) +
          '"' +
          (selected ? ' aria-current="date"' : "") +
          ">" +
          day +
          "</button>";
      }

      calGrid.innerHTML = html;
      calGrid.querySelectorAll(".cal-day:not(:disabled):not(.is-outside)").forEach(function (btn) {
        btn.addEventListener("click", function () {
          setBaseDate(parseYMD(btn.getAttribute("data-ymd")), true);
        });
      });
    }

    function placeCalendar() {
      if (!calendar || !trigger) return;
      const rect = trigger.getBoundingClientRect();
      const gap = 6;
      const width = 280;
      let left = rect.left;
      let top = rect.bottom + gap;

      if (left + width > window.innerWidth - 8) {
        left = Math.max(8, window.innerWidth - width - 8);
      }
      if (top + 320 > window.innerHeight && rect.top > 320) {
        top = rect.top - gap - 300;
      }

      calendar.style.top = Math.round(top) + "px";
      calendar.style.left = Math.round(left) + "px";
    }

    function setCalendarOpen(nextOpen) {
      open = nextOpen;
      if (!calendar || !trigger) return;

      trigger.setAttribute("aria-expanded", open ? "true" : "false");

      if (open) {
        document.body.appendChild(calendar);
        calendar.hidden = false;
        calendar.classList.add("is-open");
        placeCalendar();
        renderCalendar();
      } else {
        calendar.hidden = true;
        calendar.classList.remove("is-open");
        calendar.style.top = "";
        calendar.style.left = "";
        if (picker) picker.appendChild(calendar);
      }
    }

    if (trigger) {
      trigger.addEventListener("click", function (e) {
        e.stopPropagation();
        setCalendarOpen(!open);
      });
    }

    if (calPrev) {
      calPrev.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!canGoPrev()) return;
        const d = new Date(viewYear, viewMonth, 1);
        d.setMonth(d.getMonth() - 1);
        viewYear = d.getFullYear();
        viewMonth = d.getMonth();
        renderCalendar();
      });
    }

    if (calNext) {
      calNext.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!canGoNext()) return;
        const d = new Date(viewYear, viewMonth, 1);
        d.setMonth(d.getMonth() + 1);
        viewYear = d.getFullYear();
        viewMonth = d.getMonth();
        renderCalendar();
      });
    }

    if (calendar) {
      calendar.addEventListener("click", function (e) {
        e.stopPropagation();
      });
    }

    document.addEventListener("click", function (e) {
      if (!open) return;
      if (trigger && trigger.contains(e.target)) return;
      if (calendar && calendar.contains(e.target)) return;
      setCalendarOpen(false);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && open) setCalendarOpen(false);
    });

    window.addEventListener(
      "scroll",
      function () {
        if (open) placeCalendar();
      },
      true
    );

    window.addEventListener("resize", function () {
      if (open) placeCalendar();
    });

    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        setBaseDate(bounds.today, true);
      });
    }

    const refreshBtn = document.getElementById("amendmentRefresh");
    if (refreshBtn) {
      refreshBtn.textContent = "지금 갱신";
      refreshBtn.title = "법제처 데이터를 다시 받아 사이트를 갱신합니다.";
      refreshBtn.addEventListener("click", function () {
        refreshAmendmentsFromServer(baseDate);
      });
    }

    currentBaseDate = baseDate;
    syncDisplay();
    renderFaqs();
    renderCompilations();
    renderUpcoming(baseDate);
    renderNotices();
    loadNoticesCache();
    loadAmendmentsCache().then(function () {
      afterAmendmentsUpdated(baseDate);
    });
    afterAmendmentsUpdated(baseDate);
  }

  /* ---------- home: law shortcuts (recent amendment driven) ---------- */
  function renderLawLinks(baseDate) {
    const root = document.getElementById("lawsRoot");
    if (!root) return;

    const base = baseDate || currentBaseDate || getBaseDateBounds().today;

    const ranked = (DATA.laws || [])
      .map(function (law) {
        const related = getDetailAmendmentsForLaw(law.id, base);
        const counts = countDisplayedArticlesByTier(law.id, base);
        const total =
          counts["법률"] + counts["시행령"] + counts["시행규칙"];
        const latest = related[0] || null;
        return {
          law: law,
          related: related,
          latest: latest,
          counts: counts,
          total: total,
        };
      })
      .sort(function (a, b) {
        if (b.total !== a.total) return b.total - a.total;
        if (a.latest && b.latest) {
          return parseYMD(b.latest.amendedDate) - parseYMD(a.latest.amendedDate);
        }
        if (a.latest) return -1;
        if (b.latest) return 1;
        return 0;
      });

    root.innerHTML = ranked
      .map(function (entry) {
        const law = entry.law;
        const counts = entry.counts;
        const meta = entry.total
          ? "개정 조문 " +
            entry.total +
            "건 · 법률 " +
            counts["법률"] +
            " · 시행령 " +
            counts["시행령"] +
            " · 시행규칙 " +
            counts["시행규칙"] +
            (entry.latest
              ? " · 최신 공포 " + entry.latest.amendedDate.replace(/-/g, ".")
              : "")
          : "개정 조문 없음 · 최근 개정 목록에서 이력 확인";
        return `
      <a class="law-link" href="law.html?id=${encodeURIComponent(law.id)}">
        <h3 class="law-link__name">${escapeHtml(law.shortName)}</h3>
        <p class="law-link__summary">${escapeHtml(meta)}</p>
        <p class="law-link__note">${escapeHtml(law.summary)}</p>
        <span class="law-link__cta">3단 조문 대조</span>
      </a>`;
      })
      .join("");
  }

  /* ---------- detail: 3-tier articles with amendment highlights ---------- */
  function articleButton(article, highlightInfo, startOpen) {
    const isAmended = Boolean(highlightInfo);
    const displayBody = resolveDisplayBody(article, highlightInfo);
    const bodyHtml = highlightBody(
      displayBody,
      highlightInfo ? highlightInfo.phrases : []
    );
    const amendedClass = isAmended ? " article-item--amended" : "";
    const openClass = startOpen && isAmended ? " is-open" : "";
    let badge = "";
    if (isAmended) {
      const amds = (highlightInfo.amendments || []).slice().sort(function (a, b) {
        const de = parseYMD(a.effectiveDate) - parseYMD(b.effectiveDate);
        if (de !== 0) return de;
        return parseYMD(a.amendedDate) - parseYMD(b.amendedDate);
      });
      const first = amds[0];
      const last = amds[amds.length - 1];
      let dateLabel = "";
      let dateTitle = "";
      if (first && amds.length === 1) {
        dateLabel =
          "개정 " +
          formatDotDate(first.amendedDate) +
          " · 시행 " +
          formatDotDate(first.effectiveDate);
        dateTitle =
          "개정일 " +
          formatDotDate(first.amendedDate) +
          " / 시행일 " +
          formatDotDate(first.effectiveDate);
      } else if (first && last) {
        dateLabel =
          "개정 " +
          amds.length +
          "건 · 시행 " +
          formatDotDate(first.effectiveDate) +
          "~" +
          formatDotDate(last.effectiveDate);
        dateTitle = amds
          .map(function (a) {
            return (
              "개정 " +
              formatDotDate(a.amendedDate) +
              " / 시행 " +
              formatDotDate(a.effectiveDate)
            );
          })
          .join(" · ");
      }
      badge =
        '<span class="amend-badge">개정</span>' +
        (dateLabel
          ? '<span class="amend-badge amend-badge--date" title="' +
            escapeHtml(dateTitle) +
            '">' +
            escapeHtml(dateLabel) +
            "</span>"
          : "");
    }

    return `
      <li class="article-item${amendedClass}${openClass}" data-article-id="${escapeHtml(article.id)}" id="article-${escapeHtml(article.id)}">
        <button type="button" class="article-item__btn" aria-expanded="${startOpen && isAmended ? "true" : "false"}">
          <span class="article-item__no">${escapeHtml(article.no)}</span>
          <span class="article-item__title">${escapeHtml(article.title || "")}</span>
          ${badge}
          <svg class="article-item__icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="M5 8l5 5 5-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </button>
        <div class="article-item__body">
          ${isAmended ? renderAmendmentMeta(highlightInfo) : ""}
          <pre>${bodyHtml || '<span class="article-item__empty">조문 본문을 준비 중입니다.</span>'}</pre>
        </div>
      </li>
    `;
  }

  function renderVerifiedRevisionCard(item) {
    const badgeClass = item.status === "시행예정" ? "badge--soon" : "badge--live";
    const mentions = (item.mentionedArticles || []).join(", ");
    return `
      <li class="tier-rev article-item article-item--amended is-open" data-amend-id="${escapeHtml(item.id)}">
        <div class="tier-rev__head">
          <span class="badge badge--tier">${escapeHtml(item.tier || "")}</span>
          <span class="badge ${badgeClass}">${escapeHtml(item.status || "")}</span>
          <span class="badge">법제처 검증</span>
        </div>
        <h3 class="tier-rev__title">
          <a href="${escapeHtml(item.sourceUrl || "#")}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
        </h3>
        <p class="tier-rev__meta">
          공포 ${escapeHtml(formatDotDate(item.amendedDate))}
          · 시행 ${escapeHtml(formatDotDate(item.effectiveDate))}
          ${item.revisionType ? " · " + escapeHtml(item.revisionType) : ""}
          ${mentions ? " · 언급 조문 " + escapeHtml(mentions) : ""}
        </p>
        <p class="tier-rev__summary">${escapeHtml(item.summary || "")}</p>
        <p class="tier-rev__note">로컬 조문 연혁 태그와 공포일이 일치하는 항·호가 없어 조문 음영 없이 법제처 이력만 표시합니다.</p>
      </li>
    `;
  }

  function renderArticleLevelCard(item) {
    const pair = getComparePair(item);
    const compareHtml = renderCompareBlock(item);
    return (
      '<li class="tier-rev article-item article-item--amended is-open" data-amend-id="' +
      escapeHtml(item.id) +
      '">' +
      '<div class="tier-rev__head">' +
      '<span class="badge badge--tier">' +
      escapeHtml(item.tier || "") +
      "</span>" +
      '<span class="amend-badge">개정</span>' +
      "</div>" +
      '<h3 class="tier-rev__title">' +
      escapeHtml(item.title) +
      "</h3>" +
      '<p class="tier-rev__meta">개정 ' +
      escapeHtml(formatDotDate(item.amendedDate)) +
      " · 시행 " +
      escapeHtml(formatDotDate(item.effectiveDate)) +
      "</p>" +
      '<p class="tier-rev__summary">' +
      escapeHtml(item.summary || makeChangeBrief(item)) +
      "</p>" +
      (compareHtml ||
        (pair.before || pair.after
          ? ""
          : '<p class="tier-rev__note">3단 본문 조문이 로컬에 없어 변경 요약만 표시합니다.</p>')) +
      "</li>"
    );
  }

  function articleSortKey(no) {
    const m = String(no || "").match(/제\s*(\d+)\s*조(?:의\s*(\d+))?/);
    if (!m) return [99999, 0];
    return [parseInt(m[1], 10), parseInt(m[2] || "0", 10)];
  }

  function renderTier(label, name, articles, cite, highlightMap, tierItems, articleCountHint) {
    // 법제처식 3단: 조회기간 내 조문 단위 개정을 모두 나열
    const shownIds = {};
    const amendedOnly = (articles || [])
      .filter(function (article) {
        return Boolean(highlightMap[article.id]);
      })
      .slice()
      .sort(function (a, b) {
        const ka = articleSortKey(a.no);
        const kb = articleSortKey(b.no);
        return ka[0] - kb[0] || ka[1] - kb[1];
      });

    let list = "";
    if (amendedOnly.length) {
      list += amendedOnly
        .map(function (article) {
          shownIds[article.id] = true;
          return articleButton(article, highlightMap[article.id], true);
        })
        .join("");
    }
    const extraCards = (tierItems || [])
      .filter(function (item) {
        const aid = firstArticleId(item);
        if (aid && shownIds[aid]) return false;
        return item.articleLevel || hasPhraseHighlights(item);
      })
      .slice()
      .sort(function (a, b) {
        const ka = articleSortKey(a.articleNo || a.title || "");
        const kb = articleSortKey(b.articleNo || b.title || "");
        return ka[0] - kb[0] || ka[1] - kb[1];
      });
    if (extraCards.length) {
      list += extraCards.map(renderArticleLevelCard).join("");
    }
    const shownCount =
      articleCountHint != null
        ? articleCountHint
        : amendedOnly.length + extraCards.length;
    if (!list) {
      list =
        '<li class="empty-state" style="margin:16px;border:none">이 단에 표시할 조문 단위 개정이 없습니다.</li>';
    }

    return `
      <aside class="tier">
        <div class="tier__head">
          <div class="tier__title-row">
            <h2 class="tier__name">${escapeHtml(name)}</h2>
            <span class="tier__badge">기준</span>
          </div>
          <p class="tier__label">${escapeHtml(label)}</p>
          ${cite ? `<p class="tier__cite">${escapeHtml(cite)}</p>` : ""}
          <p class="tier__count">개정 조문 ${shownCount}건</p>
        </div>
        <ul class="tier__list">${list}</ul>
      </aside>
    `;
  }

  function bindArticleToggles(scope) {
    scope.querySelectorAll(".article-item__btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const item = btn.closest(".article-item");
        const open = item.classList.toggle("is-open");
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
    });
  }

  function bindAmendMemos(scope) {
    let floatEl = null;

    function hideMemo() {
      if (floatEl && floatEl.parentNode) floatEl.parentNode.removeChild(floatEl);
      floatEl = null;
    }

    function showMemo(mark) {
      const source = mark.querySelector(".amend-mark__memo");
      if (!source) return;
      hideMemo();

      floatEl = document.createElement("div");
      floatEl.className = "amend-memo-float";
      floatEl.setAttribute("role", "tooltip");
      floatEl.innerHTML = source.innerHTML;
      document.body.appendChild(floatEl);

      const rect = mark.getBoundingClientRect();
      const tipW = floatEl.offsetWidth;
      const tipH = floatEl.offsetHeight;
      let left = rect.left;
      let top = rect.bottom + 10;

      if (left + tipW > window.innerWidth - 12) {
        left = Math.max(12, window.innerWidth - tipW - 12);
      }
      if (top + tipH > window.innerHeight - 12) {
        top = Math.max(12, rect.top - tipH - 10);
      }

      floatEl.style.left = Math.round(left) + "px";
      floatEl.style.top = Math.round(top) + "px";
    }

    scope.querySelectorAll(".amend-mark").forEach(function (mark) {
      mark.addEventListener("mouseenter", function () {
        showMemo(mark);
      });
      mark.addEventListener("mouseleave", function () {
        hideMemo();
      });
      mark.addEventListener("focus", function () {
        showMemo(mark);
      });
      mark.addEventListener("blur", function () {
        hideMemo();
      });
    });

    window.addEventListener("scroll", hideMemo, true);
  }

  function setAllArticles(open, amendedOnly) {
    document.querySelectorAll(".article-item").forEach(function (item) {
      if (amendedOnly && !item.classList.contains("article-item--amended")) {
        item.classList.remove("is-open");
        const btn = item.querySelector(".article-item__btn");
        if (btn) btn.setAttribute("aria-expanded", "false");
        return;
      }
      item.classList.toggle("is-open", open);
      const btn = item.querySelector(".article-item__btn");
      if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  function openTargetArticle(articleId) {
    if (!articleId) return;
    const el = document.getElementById("article-" + articleId);
    if (!el) return;
    el.classList.add("is-open");
    const btn = el.querySelector(".article-item__btn");
    if (btn) btn.setAttribute("aria-expanded", "true");
    setTimeout(function () {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
  }

  function openTargetAmend(amendId) {
    if (!amendId) return;
    const el = document.querySelector('[data-amend-id="' + amendId + '"]');
    if (!el) return;
    el.classList.add("is-open", "is-focus-amend");
    setTimeout(function () {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 80);
  }

  function renderLawDetail() {
    const root = document.getElementById("tiersRoot");
    if (!root) return;

    const base = currentBaseDate || getBaseDateBounds().today;
    const id = getQueryParam("id") || DATA.laws[0].id;
    const focusAmendId = getQueryParam("amend") || "";
    const law = DATA.laws.find((l) => l.id === id) || DATA.laws[0];
    const pack = ARTICLES[law.id] || { statute: [], decree: [], rule: [], meta: {} };
    const meta = pack.meta || {};
    const highlightMap = buildHighlightMap(law.id, base);
    const detailItems = getDetailAmendmentsForLaw(law.id, base);
    const focusAmend = focusAmendId
      ? detailItems.find(function (item) {
          return item.id === focusAmendId;
        }) ||
        getAmendmentSource().find(function (item) {
          return item.id === focusAmendId;
        })
      : null;
    // 홈 카드·단별 건수와 동일: 고유 조문 수(동일 조 복수 공포 = 1건)
    const articleCount = countDisplayedArticlesForLaw(law.id, base);
    const tierCounts = countDisplayedArticlesByTier(law.id, base);

    document.title = `${law.name} — 인사 관련 법령문 개정 현황`;

    const titleEl = document.getElementById("lawTitle");
    const summaryEl = document.getElementById("lawSummary");
    const crumbEl = document.getElementById("crumbCurrent");
    const sourceEl = document.getElementById("lawSource");
    if (titleEl) titleEl.textContent = law.name;
    if (summaryEl) {
      if (focusAmend) {
        const locs = (focusAmend.locators || [])
          .concat(focusAmend.mentionedArticles || [])
          .filter(function (v, i, arr) {
            return v && arr.indexOf(v) === i;
          });
        summaryEl.textContent =
          "선택 개정: " +
          focusAmend.title +
          " · 공포 " +
          formatDotDate(focusAmend.amendedDate) +
          " · 시행 " +
          formatDotDate(focusAmend.effectiveDate) +
          (locs.length ? " · " + locs.join(" · ") : "") +
          " · 아래 법률·시행령·시행규칙 3단에서 조·항·호를 확인하세요.";
      } else {
        // articleCount = 3단에 펼쳐지는 고유 조문 수(동일 조 복수 개정은 1건)
        summaryEl.textContent = articleCount
          ? "개정 조문 " +
            articleCount +
            "건을 법률·시행령·시행규칙 3단으로 대조합니다. 조문 전문을 펼친 뒤 노란 음영(개정·신설)에 마우스를 올리면 개정 전 내용이 표시됩니다."
          : law.summary;
      }
    }
    if (crumbEl) crumbEl.textContent = law.shortName;
    if (sourceEl) {
      sourceEl.innerHTML =
        '원문: <a href="https://www.law.go.kr/" target="_blank" rel="noopener">국가법령정보센터</a>' +
        (law.sourceUrl
          ? ` · <a href="${escapeHtml(law.sourceUrl)}" target="_blank" rel="noopener">해당 법령 보기</a>`
          : "") +
        (articleCount
          ? `<br><span class="page-hero__note">개정 조문 ${articleCount}건 · 노란 음영에 마우스를 올리면 개정 전 조항이 나타납니다.</span>`
          : "") +
        (DATA.sourceNote ? `<br><span class="page-hero__note">${escapeHtml(DATA.sourceNote)}</span>` : "");
    }

    const byTier = function (tier) {
      return detailItems.filter(function (item) {
        return item.tier === tier;
      });
    };

    root.innerHTML =
      renderTier(
        "법률",
        law.name,
        pack.statute,
        meta.statuteCite,
        highlightMap,
        byTier("법률"),
        tierCounts["법률"]
      ) +
      renderTier(
        "시행령",
        law.decreeName,
        pack.decree,
        meta.decreeCite,
        highlightMap,
        byTier("시행령"),
        tierCounts["시행령"]
      ) +
      renderTier(
        "시행규칙",
        law.ruleName,
        pack.rule,
        meta.ruleCite,
        highlightMap,
        byTier("시행규칙"),
        tierCounts["시행규칙"]
      );

    bindArticleToggles(root);
    bindAmendMemos(root);

    const expandBtn = document.getElementById("expandAll");
    const collapseBtn = document.getElementById("collapseAll");
    if (expandBtn) {
      expandBtn.addEventListener("click", function () {
        setAllArticles(true, false);
      });
    }
    if (collapseBtn) {
      collapseBtn.addEventListener("click", function () {
        setAllArticles(false, false);
      });
    }

    const targetArticle = getQueryParam("article");
    if (targetArticle) {
      openTargetArticle(targetArticle);
    } else if (focusAmend && focusAmend.articleIds && focusAmend.articleIds[0]) {
      openTargetArticle(focusAmend.articleIds[0]);
    } else if (focusAmendId) {
      openTargetAmend(focusAmendId);
    }
  }

  /* ---------- boot ---------- */
  document.addEventListener("DOMContentLoaded", function () {
    initMenu();

    if (document.getElementById("consultDetailRoot")) {
      renderConsultDetail();
    } else if (document.getElementById("tiersRoot")) {
      currentBaseDate = getBaseDateBounds().today;
      loadAmendmentsCache().finally(function () {
        renderLawDetail();
      });
    } else {
      initAmendments();
      initHomeViews();
    }
  });
})();
