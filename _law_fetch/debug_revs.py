# -*- coding: utf-8 -*-
from refresh_amendments import fetch_revisions

for ls, name in [
    ("001872", "근로기준법"),
    ("009883", "퇴직급여법"),
    ("000130", "남녀고용평등법"),
    ("010356", "기간제법"),
]:
    revs = fetch_revisions(ls)
    print("====", name, len(revs))
    for r in revs[:8]:
        print(r["amendedDate"], r["effectiveDate"], r["revisionType"], r["noticeNo"])
