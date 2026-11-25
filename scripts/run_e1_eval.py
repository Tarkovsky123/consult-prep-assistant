"""E1 유사사업 찾기 측정: B1 TF-IDF · B2 태그+키워드 · A1 AI 판정을 고정 정답표로 채점한다.

규칙은 30_analysis/E1_측정_사전등록.md 를 따른다(실행 전 고정).
  python -X utf8 scripts/run_e1_eval.py            # AI 판정(이미 있으면 캐시) + 채점
  python -X utf8 scripts/run_e1_eval.py --score    # 채점만
  python -X utf8 scripts/run_e1_eval.py --v3       # v3 지시문(같은 지자체 보완)으로 다시 판정 → 결과_E1_v3.md (개발 점수, 정답을 이미 본 뒤)
  python -X utf8 scripts/run_e1_eval.py --v4       # v4 C3: 목적·대상·형태를 따로 답하고 판정은 코드가(similar.decide) → 결과_E1_v4.md (개발 점수)
출력: data/processed/e1_runs/llm/<협의ID>.json, data/processed/e1_eval.json, 30_analysis/결과_E1.md,
      data/processed/e1_topup_candidates.csv ((C) 풀 밖 발견용, AI 판정 열은 판정판에 보여 주지 않는다)
"""
import argparse
import csv
import difflib
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from consult_prep import Tfidf, grams, load_csv, LOCAL  # noqa: E402
from similar import norm, region, b2_rank, judge_similar  # noqa: E402

GOLD = ROOT / "data/labels/E1_정답표_고정_20261103.csv"
E2_SHEET = ROOT / "data/labels/E2_요건대조_라벨시트.csv"
E2_GOLD = ROOT / "data/labels/E2_정답표_고정_20261103.csv"
HIST = ROOT / "data/raw/협의완료_2025_부록1.csv"
RUNS = ROOT / "data/processed/e1_runs/llm"
CLARIFY = False  # --v3 이면 True(similar.E1_CLARIFY)
DECOMPOSE = False  # --v4 이면 True(similar.E1_DECOMPOSE)
SEED, TOPK, TOPUP_MAX = 20261103, 30, 60
POS = ("동일", "유사")


def load_cases():
    gold = list(csv.DictReader(GOLD.open(encoding="utf-8-sig")))
    kind = {h["연번"]: h["신설변경"] for h in csv.DictReader(HIST.open(encoding="utf-8-sig"))}
    e2g = {r["협의ID"]: r["동일"] for r in csv.DictReader(E2_GOLD.open(encoding="utf-8-sig"))}
    refs = {r["협의ID"]: r for r in csv.DictReader(E2_SHEET.open(encoding="utf-8-sig")) if e2g.get(r["협의ID"]) == "예"}
    cases, labels, selfs = {}, {}, set()
    for g in gold:
        cid = g["협의ID"]
        cases.setdefault(cid, {"id": cid, "org": g["협의요청기관"], "name": g["협의 사업명"], "kind": kind.get(cid, ""), "ref": refs.get(cid)})
        labels[(cid, g["복지로 servId"])] = g["판정"]
        if ((g["시도"], g["시군구"]) == region(g["협의요청기관"]) and g["판정"] == "동일"
                and difflib.SequenceMatcher(None, norm(g["협의 사업명"]), norm(g["복지로 사업명"])).ratio() >= 0.6):
            selfs.add((cid, g["복지로 servId"]))
    return list(cases.values()), labels, selfs


def judge(case, cands, loc_by_id):
    proj = {"기관": case["org"], "사업명": case["name"], "신설변경": case["kind"] or "미상"}
    if case["ref"]:
        proj.update({"지원대상": case["ref"]["원문 지원대상"], "선정기준": case["ref"]["원문 선정기준"], "지원내용": case["ref"]["원문 지원내용"]})
    return judge_similar(proj, cands, loc_by_id, RUNS / f"{case['id']}.json", f"{SEED}-{case['id']}", clarify=CLARIFY, decompose=DECOMPOSE)


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0
    r = tp / (tp + fn) if tp + fn else 0
    return p, r, (2 * p * r / (p + r) if p + r else 0)


def kappa(pairs, cats=("동일", "유사", "무관")):
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[c] * cb[c] for c in cats) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--v3", action="store_true")
    ap.add_argument("--v4", action="store_true")
    a = ap.parse_args()
    global RUNS, CLARIFY, DECOMPOSE
    tag = "v4" if a.v4 else ("v3" if a.v3 else "")
    if a.v3:
        RUNS, CLARIFY = ROOT / "data/processed/e1_runs/llm_v3", True
    if a.v4:
        RUNS, CLARIFY, DECOMPOSE = ROOT / "data/processed/e1_runs/llm_v4", True, True
    out_md = ROOT / (f"30_analysis/결과_E1_{tag}.md" if tag else "30_analysis/결과_E1.md")
    out_json = ROOT / (f"data/processed/e1_eval_{tag}.json" if tag else "data/processed/e1_eval.json")
    topup_out = RUNS / "_topup_unused.csv" if tag else ROOT / "data/processed/e1_topup_candidates.csv"  # v3·v4는 (C) 표본을 다시 뽑지 않는다
    cases, labels, selfs = load_cases()
    loc = load_csv(LOCAL)
    loc_by_id = {l["servId"]: l for l in loc}
    idx_by_id = {l["servId"]: i for i, l in enumerate(loc)}
    tf = Tfidf([l["servNm"] + " " + l["servDgst"] for l in loc])
    pool = defaultdict(list)
    for (cid, sid) in labels:
        if (cid, sid) not in selfs:
            pool[cid].append(sid)
    b1, b2 = {}, {}
    for c in cases:
        drop = {sid for (cid, sid) in selfs if cid == c["id"]}
        b1[c["id"]] = [loc[i]["servId"] for _, i in tf.query(c["name"], TOPK + len(drop)) if loc[i]["servId"] not in drop][:TOPK]
        b2[c["id"]] = [loc[i]["servId"] for i in b2_rank(c["org"], c["name"], loc) if loc[i]["servId"] not in drop][:TOPK]
    RUNS.mkdir(parents=True, exist_ok=True)
    if not a.score:
        def work(c):
            cands = list(dict.fromkeys(pool[c["id"]] + b1[c["id"]] + b2[c["id"]]))
            try:
                judge(c, cands, loc_by_id)
            except Exception as e:  # noqa: BLE001
                print(f"  {c['id']} 실패: {e}", flush=True)
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(work, cases))
        print("AI 판정 완료", flush=True)
    ai = {c["id"]: json.loads((RUNS / f"{c['id']}.json").read_text(encoding="utf-8")) for c in cases if (RUNS / f"{c['id']}.json").exists()}
    ai_label = lambda cid, sid: ((ai.get(cid) or {}).get("labels", {}).get(sid) or {}).get("판정")
    gold_pos = {(cid, sid) for (cid, sid), v in labels.items() if v in POS and (cid, sid) not in selfs}
    n_pos = len(gold_pos)
    pos_cases = {cid for cid, _ in gold_pos}

    # (A) 판정 일치 — 판정된 풀 후보(자기 자신 제외)
    pairs = [(cid, sid) for (cid, sid) in labels if (cid, sid) not in selfs]
    human = {k: labels[k] for k in pairs}
    name_of = {c["id"]: c["name"] for c in cases}
    qv = {cid: tf._vec(set(grams(n))) for cid, n in name_of.items()}
    tfs = {(cid, sid): sum(w * tf.V[idx_by_id[sid]].get(g, 0) for g, w in qv[cid].items()) for cid, sid in pairs}
    top3 = set()
    for cid in pool:
        top3 |= {(cid, s) for s in sorted(pool[cid], key=lambda s: -tfs[(cid, s)])[:3]}
    preds = {
        "A1 AI 판정": {k: ai_label(*k) in POS for k in pairs},
        "기준선: 모두 필수 비교": {k: True for k in pairs},
        "기준선: 사례 안 TF-IDF 상위 3": {k: k in top3 for k in pairs},
        "기준선: 사업명 유사도 0.5 이상": {k: difflib.SequenceMatcher(None, norm(name_of[k[0]]), norm(loc_by_id[k[1]]["servNm"])).ratio() >= 0.5 for k in pairs},
    }
    A = {}
    for m, pr in preds.items():
        tp = sum(pr[k] and human[k] in POS for k in pairs)
        fp = sum(pr[k] and human[k] not in POS for k in pairs)
        fn = sum((not pr[k]) and human[k] in POS for k in pairs)
        p, r, f = prf(tp, fp, fn)
        A[m] = {"tp": tp, "fp": fp, "fn": fn, "볼 후보": tp + fp, "정밀도": p, "재현율": r, "F1": f}
    def rel_a(cid, s):
        sido, sgg = region(next(c["org"] for c in cases if c["id"] == cid))
        l = loc_by_id[s]
        return "다른 시도" if l["ctpvNm"] != sido else ("같은 지자체·광역" if (l["sggNm"] or "") in (sgg, "") else "같은 시도")
    A_rel = {}
    for r in ("같은 지자체·광역", "같은 시도", "다른 시도"):
        ks = [k for k in pairs if rel_a(*k) == r]
        pr = preds["A1 AI 판정"]
        tp = sum(pr[k] and human[k] in POS for k in ks)
        fp = sum(pr[k] and human[k] not in POS for k in ks)
        fn = sum((not pr[k]) and human[k] in POS for k in ks)
        A_rel[r] = {"쌍": len(ks), "tp": tp, "fp": fp, "fn": fn}
    answered = [k for k in pairs if ai_label(*k)]
    A["세 갈래"] = {"일치": sum(ai_label(*k) == human[k] for k in answered), "분모": len(answered),
                  "kappa": kappa([(human[k], ai_label(*k)) for k in answered]),
                  "혼동": Counter(f"{human[k]}→{ai_label(*k)}" for k in answered)}

    # (B) 검색 재현율 — 풀 기준, 판정 없는 후보는 무관
    B = {}
    for m, lists in (("B1 TF-IDF", b1), ("B2 태그+키워드", b2)):
        for k in (5, 10):
            hit = sum((cid, s) in gold_pos for cid in lists for s in lists[cid][:k])
            unj = sum((cid, s) not in labels for cid in lists for s in lists[cid][:k])
            per = [sum((cid, s) in gold_pos for s in lists[cid][:k]) / sum(1 for p in gold_pos if p[0] == cid) for cid in pos_cases]
            B[f"{m} 상위{k}"] = {"찾음": hit, "재현율": hit / n_pos, "사례평균": sum(per) / len(per), "판정없음": unj, "목록길이": k}
    a1 = {}
    for c in cases:
        cid = c["id"]
        src = list(dict.fromkeys(b1[cid] + b2[cid]))
        lst = [s for s in src if ai_label(cid, s) in POS]
        lst.sort(key=lambda s: (ai_label(cid, s) != "동일", b1[cid].index(s) if s in b1[cid] else TOPK))
        a1[cid] = lst
    for name, cut in (("A1 AI 목록 전체", None), ("A1 AI 목록 상위10", 10)):
        lists = {cid: (l if cut is None else l[:cut]) for cid, l in a1.items()}
        hit = sum((cid, s) in gold_pos for cid in lists for s in lists[cid])
        judged = sum((cid, s) in labels for cid in lists for s in lists[cid])
        unj = sum((cid, s) not in labels for cid in lists for s in lists[cid])
        per = [sum((cid, s) in gold_pos for s in lists[cid]) / sum(1 for p in gold_pos if p[0] == cid) for cid in pos_cases]
        B[name] = {"찾음": hit, "재현율": hit / n_pos, "사례평균": sum(per) / len(per), "판정된 것 중 정밀도": hit / judged if judged else 0,
                   "판정없음": unj, "목록길이": sum(len(l) for l in lists.values()) / len(lists)}
    reach = sum(1 for (cid, s) in gold_pos if s in set(b1[cid] + b2[cid]))

    # (C) 풀 밖 발견 후보: 지역 층화(사전등록 §5, 11/3 변경). 가까운 지역 AI 양성 40 + 다른 시도 10, 같은 구성의 AI 무관 미끼 50
    def rel(cid, s):
        sido, sgg = region(next(c["org"] for c in cases if c["id"] == cid))
        l = loc_by_id[s]
        if l["ctpvNm"] != sido:
            return "다른 시도"
        return "같은 지자체·광역" if (l["sggNm"] or "") in (sgg, "") else "같은 시도"
    rng = random.Random(SEED)
    unj_pos = [(cid, s) for cid in a1 for s in a1[cid] if (cid, s) not in labels]
    unj_neg = [(cid, s) for cid in a1 for s in dict.fromkeys(b1[cid] + b2[cid]) if (cid, s) not in labels and ai_label(cid, s) == "무관"]
    by_rel = lambda xs: {r: [k for k in xs if rel(*k) == r] for r in ("같은 지자체·광역", "같은 시도", "다른 시도")}
    P, N = by_rel(unj_pos), by_rel(unj_neg)
    quota = {"같은 지자체·광역": len(P["같은 지자체·광역"]), "같은 시도": 40 - len(P["같은 지자체·광역"]), "다른 시도": 10}
    pick_pos, pick_neg = [], []
    for r, q in quota.items():
        pick_pos += rng.sample(P[r], min(q, len(P[r])))
        pick_neg += rng.sample(N[r], min(q, len(N[r])))
    topup = [(k, "AI양성") for k in pick_pos] + [(k, "AI무관") for k in pick_neg]
    rng.shuffle(topup)
    with topup_out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["협의ID", "협의 사업명", "복지로 servId", "복지로 사업명", "시도", "시군구", "지역관계", "AI판정(판정판에 보이지 않음)", "묶음"])
        for (cid, s), grp in topup:
            l = loc_by_id[s]
            w.writerow([cid, name_of[cid], s, l["servNm"], l["ctpvNm"], l["sggNm"], rel(cid, s), ai_label(cid, s), grp])
    rel_pos = Counter(rel(*k) for k in unj_pos)

    secs = [r["sec"] for r in ai.values()]
    missing = sum(len(r.get("missing") or []) for r in ai.values())
    meta = {"정답표": GOLD.name, "sha256_16": hashlib.sha256(GOLD.read_bytes()).hexdigest()[:16], "자기자신": len(selfs), "필수비교": n_pos,
            "AI 사례": len(ai), "AI 미응답 후보": missing, "AI 호출 초 중앙값": sorted(secs)[len(secs) // 2] if secs else None,
            "B1·B2 상위30에 든 필수비교": reach, "풀 밖 AI양성": len(unj_pos), "실행": datetime.now().isoformat(timespec="minutes")}
    out_json.write_text(json.dumps({"A": A, "B": B, "meta": meta}, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")

    f = lambda x: f"{x:.0%}"
    title = {"v3": " — v3 지시문(개발 점수: 정답을 본 뒤 고친 지시문)", "v4": " — v4 세 요소 나눠 답하기(개발 점수: 정답을 본 뒤 고친 방법)"}.get(tag, "")
    L = [f"# 결과: E1 유사사업 찾기{title} ({datetime.now():%Y-%m-%d %H:%M})", "",
         f"> 규칙: `30_analysis/E1_측정_사전등록.md`(실행 전 고정). 정답표: `data/labels/{GOLD.name}`(sha256 {meta['sha256_16']}).",
         f"> 자기 자신 {len(selfs)}건을 뺀 필수 비교사업 {n_pos}개(사례 {len(pos_cases)}개). AI = Codex medium, 사례 {len(ai)}건 판정, 미응답 후보 {missing}개, 호출 시간 중앙값 {meta['AI 호출 초 중앙값']}초.", "",
         "## (A) 판정 일치 — 판정된 후보 쌍(주 지표, 풀 편향 없음)", "",
         "| 방법 | 필수 비교로 고른 수(볼 후보) | 정밀도 | 재현율 | F1 | 놓친 필수 비교 |", "|---|---:|---:|---:|---:|---:|"]
    for m in preds:
        d = A[m]
        L.append(f"| {m} | {d['볼 후보']} / {len(pairs)} | {f(d['정밀도'])} | {f(d['재현율'])} | {d['F1']:.2f} | {d['fn']} |")
    L += ["", "A1 지역 관계별(판정된 쌍): " + " · ".join(f"{r} {d['쌍']}쌍 정밀도 {d['tp']}/{d['tp'] + d['fp']} 재현율 {d['tp']}/{d['tp'] + d['fn']}" for r, d in A_rel.items())]
    t = A["세 갈래"]
    L += ["", f"세 갈래(동일·유사·무관) 일치 {t['일치']}/{t['분모']} ({t['일치'] / t['분모']:.0%}), Cohen κ {t['kappa']:.2f}.", "",
          "| 사람→AI | 건수 |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in sorted(t["혼동"].items())]
    L += ["", "## (B) 검색 재현율 — 풀 기준(판정 없는 후보는 무관으로 셈)", "",
          "> B1·B2는 정답 풀을 만든 방식이라 유리하다. A1은 B1·B2 상위 30에서 AI가 고른 목록이다.",
          f"> B1·B2 상위 30을 합친 후보에 든 필수 비교사업은 {reach}/{n_pos}개라, A1 재현율의 상한이 {reach / n_pos:.0%}다.", "",
          "| 방법 | 찾은 필수 비교 | 재현율 | 사례 평균 재현율 | 목록 길이(사례 평균) | 판정된 것 중 정밀도 | 판정 없는 후보 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for m, d in B.items():
        L.append(f"| {m} | {d['찾음']} | {f(d['재현율'])} | {f(d['사례평균'])} | {d['목록길이']:.1f} | {f(d['판정된 것 중 정밀도']) if '판정된 것 중 정밀도' in d else '-'} | {d['판정없음']} |")
    L += ["", "## (C) 풀 밖 발견 후보", "",
          f"AI가 동일·유사로 봤지만 판정이 없는 후보는 {len(unj_pos)}개다. 지역 관계로 나누면 {dict(rel_pos)}이다.",
          f"확인용으로 AI 양성 {len(pick_pos)}개와 AI 무관 미끼 {len(pick_neg)}개를 지역 층화로 섞어 `data/processed/e1_topup_candidates.csv`에 두었다(사전등록 §5 변경 기록). 판정판에는 AI 판정 열을 보여 주지 않는다."]
    keys = sorted((ROOT / "data/labels").glob("E1추가_정답표_고정_*.csv"))
    if keys:  # (C) 채점: 추가 판정 정답표가 고정된 뒤
        tk = keys[-1]
        hum = {(r["협의ID"], r["복지로 servId"]): r["판정"] for r in csv.DictReader(tk.open(encoding="utf-8-sig"))}
        cand = list(csv.DictReader((ROOT / "data/processed/e1_topup_candidates.csv").open(encoding="utf-8-sig")))
        cell = defaultdict(lambda: [0, 0])
        for r in cand:
            c = cell[(r["지역관계"], r["묶음"])]
            c[0] += 1
            c[1] += hum[(r["협의ID"], r["복지로 servId"])] in POS
        rels = ("같은 지자체·광역", "같은 시도", "다른 시도")
        L += ["", f"### (C) 채점 — 정답표 `data/labels/{tk.name}`(sha256 {hashlib.sha256(tk.read_bytes()).hexdigest()[:16]})", "",
              "| 지역 관계 | AI가 필수 비교로 본 후보 → 사람도 필수 비교 | AI가 무관으로 본 미끼 → 사람은 필수 비교 | 판정 없는 AI 양성 전체 |", "|---|---:|---:|---:|"]
        for r in rels:
            ps, ng = cell[(r, "AI양성")], cell[(r, "AI무관")]
            L.append(f"| {r} | {ps[1]}/{ps[0]} | {ng[1]}/{ng[0]} | {rel_pos.get(r, 0)} |")
        tp, npos = sum(cell[(r, "AI양성")][1] for r in rels), sum(cell[(r, "AI양성")][0] for r in rels)
        fn, nneg = sum(cell[(r, "AI무관")][1] for r in rels), sum(cell[(r, "AI무관")][0] for r in rels)
        L += ["", f"합계: AI 양성 {tp}/{npos}가 사람도 필수 비교, 미끼 {fn}/{nneg}가 사람은 필수 비교였다."]
        if tag:  # 같은 100후보를 v3·v4 판정으로 본다(개발 점수)
            L += ["", f"**{tag} 판정으로 본 같은 100후보**", "", f"| 지역 관계 | {tag} AI 양성 → 사람도 필수 비교 | {tag} AI 무관 → 사람은 필수 비교 |", "|---|---:|---:|"]
            for r in rels:
                sub = [x for x in cand if x["지역관계"] == r]
                pos_ = [x for x in sub if ai_label(x["협의ID"], x["복지로 servId"]) in POS]
                neg_ = [x for x in sub if ai_label(x["협의ID"], x["복지로 servId"]) not in POS]
                hp = lambda xs: sum(hum[(x["협의ID"], x["복지로 servId"])] in POS for x in xs)
                L.append(f"| {r} | {hp(pos_)}/{len(pos_)} | {hp(neg_)}/{len(neg_)} |")
        found = [r for r in cand if r["묶음"] == "AI양성" and r["지역관계"] == "같은 지자체·광역" and hum[(r["협의ID"], r["복지로 servId"])] in POS]
        L += ["", f"**풀 밖에서 새로 확인된 같은 지자체·광역 필수 비교사업 {len(found)}건**", ""]
        L += [f"- {r['협의ID']} {r['협의 사업명']} ↔ {r['시도']} {r['시군구'] or '(본청)'} {r['복지로 사업명']} ({hum[(r['협의ID'], r['복지로 servId'])]})" for r in found]
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
