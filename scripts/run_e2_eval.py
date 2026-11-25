"""E2 요건 대조 측정: 사례를 M0(규칙 기준선)·M1(시제품 v1)·M2(시제품 v2)로 돌리고 고정 정답표로 채점한다.

규칙은 30_analysis/E2_측정_사전등록.md(v1)와 E2_v2_사전등록.md(v2)를 따른다(실행 전 고정).
  (v1 측정 보고서 30_analysis/결과_E2_측정.md 는 11/3 v1 실행본으로 그대로 둔다. 같은 값은 --set dev --methods M0 M1 로 재현된다)
  python -X utf8 scripts/run_e2_eval.py --set dev --methods M0 M1 M2   # 개발 세트 점수 → 결과_E2_dev.md
  python -X utf8 scripts/run_e2_eval.py --set e2b --methods M0 M1 M2   # 시험 A → 결과_E2_e2b.md
  python -X utf8 scripts/run_e2_eval.py --set synth --methods M0 M1 M2 # 시험 B → 결과_E2_synth.md
  python -X utf8 scripts/run_e2_eval.py --set e2c --methods M0 M3 M4   # 시험 C(v4, 30_analysis/v4_개선_사전등록.md) → 결과_E2_e2c.md
  ... --score                                                   # 채점만(이미 있는 출력)
출력: data/processed/<세트 runs>/<M>/<사례>.json, data/processed/e2_eval_<세트>.json, 30_analysis/결과_E2_<세트>.md
"""
import argparse
import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LB = ROOT / "data/labels"
SETS = {
    "dev": {"cases": LB / "E2_요건대조_라벨시트.csv", "gold": LB / "E2_정답표_고정_20261103.csv", "runs": ROOT / "data/processed/e2_runs", "title": "개발 세트(E2 30건)"},
    "e2b": {"cases": LB / "E2b_요건대조_사례.csv", "gold": LB / "E2b_정답표_고정_20261103.csv", "runs": ROOT / "data/processed/e2b_runs", "title": "시험 A(E2b 20건)"},
    "synth": {"cases": LB / "합성_정답표_고정_20261103.csv", "gold": LB / "합성_정답표_고정_20261103.csv", "runs": ROOT / "data/processed/synth_runs", "title": "시험 B(합성 11건)"},
    "e2d": {"cases": LB / "E2d_요건대조_사례.csv", "gold": LB / "E2d_정답표_고정_20261111.csv", "runs": ROOT / "data/processed/e2d_runs", "title": "시험 D(E2d 40건, 층 나눔; M5 = v5.3)"},
    "e2c": {"cases": LB / "E2c_요건대조_사례.csv", "gold": LB / "E2c_정답표_고정_20261106.csv", "runs": ROOT / "data/processed/e2c_runs", "title": "시험 C(E2c 40건, 층 나눔)"},
}
FIELDS = ["유형연번", "대상", "상한", "협의제외", "유형판정"]
NAMES = {"M0": "M0 규칙 기준선", "M1": "M1 시제품 v1", "M2": "M2 시제품 v2", "M2n": "M2n v2·새 모델", "M3": "M3 시제품 v3(개발)", "M4": "M4 시제품 v4(개발)", "M5": "M5 시제품 v5(개발)", "M5b": "M5b v5.1(개발)", "M6": "M6 v5.4 + 피드백 선례"}


def as_case(row):
    """세트마다 다른 열을 도구 입력으로 맞춘다(합성은 E2_v2_사전등록 §3)."""
    if "사업안" in row:
        t = row["사업안"]
        return {"id": row["사례"], "org": t.split(":")[0].strip() if ":" in t else "", "name": t, "text": t}
    return {"id": row["협의ID"], "org": row["협의요청기관"], "name": row["협의 사업명"], "target": row["원문 지원대상"],
            "criteria": row["원문 선정기준"], "content": row["원문 지원내용"],
            "text": f"[지원대상] {row['원문 지원대상']}\n[선정기준] {row['원문 선정기준']}\n[지원내용] {row['원문 지원내용']}"}


def run_case(runs, method, c):
    out = runs / method / f"{c['id']}.json"
    if out.exists():
        return
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "scripts/consult_prep.py"), "--name", c["name"], "--org", c["org"], "--text", c["text"],
           "--json", str(out), "--out", str(out.with_suffix(".md"))]
    for k in ("target", "criteria", "content"):
        if c.get(k) is not None:
            cmd += [f"--{k}", c[k]]
    cmd += {"M0": ["--baseline"], "M1": [], "M2": ["--v2"], "M2n": ["--v2"], "M3": ["--v3", "--skip-similar"], "M4": ["--v4", "--skip-similar"], "M5": ["--v5", "--skip-similar"], "M5b": ["--v5", "--skip-similar"],
            "M6": ["--v5", "--skip-similar", "--feedback", str(ROOT / "data/feedback/feedback_store.jsonl"), "--case-id", c["id"]]}[method]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode != 0:
        print(f"  {method} {c['id']} 실패: {r.stderr[-300:]}", flush=True)


def load_tool(runs, method, cid):
    p = runs / method / f"{cid}.json"
    if not p.exists():
        return None
    rep = json.loads(p.read_text(encoding="utf-8"))
    ev = dict(rep["eval"])
    ev["evidence_failed"] = len((rep.get("extraction") or {}).get("evidence_failed") or []) + len((rep.get("v2") or {}).get("evidence_failed") or [])
    return ev


def score(gold, tool):
    ids = [i for i, g in gold.items() if g.get("동일", "예") != "아니오"]
    res = {"n": len(ids), "fields": {}, "holds": {}}
    ok = lambda i, f: (tool[i] or {}).get(f, "") == gold[i][f]
    for f in ("유형연번", "협의제외", "유형판정"):
        res["fields"][f] = {"맞음": sum(ok(i, f) for i in ids), "분모": len(ids)}
    sub = [i for i in ids if gold[i]["유형연번"] not in ("", "해당없음") and tool[i] and tool[i]["유형연번"] == gold[i]["유형연번"]]
    for f in ("대상", "상한"):
        res["fields"][f] = {"맞음": sum(ok(i, f) for i in sub), "분모": len(sub), "조건": "정답 연번이 유형이고 도구 연번이 같은 사례"}
    for f, pool in (("유형판정", ids), ("대상", sub), ("상한", sub)):
        g_hold = lambda i: gold[i][f] == "확인불가"
        t_hold = lambda i: (tool[i] or {}).get(f) == "확인불가"
        res["holds"][f] = {"필요한 보류를 잡음": sum(g_hold(i) and t_hold(i) for i in pool),
                           "필요한 보류를 놓침": sum(g_hold(i) and not t_hold(i) for i in pool),
                           "불필요한 보류": sum((not g_hold(i)) and t_hold(i) for i in pool), "분모": len(pool)}
    res["verdict_confusion"] = Counter(f"{gold[i]['유형판정']}→{(tool[i] or {}).get('유형판정', '실패')}" for i in ids)
    res["evidence_failed_cases"] = sum(1 for i in ids if (tool[i] or {}).get("evidence_failed"))
    res["missing_runs"] = sum(1 for i in ids if not tool[i])
    res["correct_ids"] = [i for i in ids if ok(i, "유형판정")]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=list(SETS), required=True)
    ap.add_argument("--methods", nargs="+", default=None)
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    cfg = SETS[a.set]
    methods = a.methods or ["M0", "M1"]
    rows = list(csv.DictReader(cfg["cases"].open(encoding="utf-8-sig")))
    cases = [as_case(r) for r in rows]
    gold = {(g.get("사례") or g["협의ID"]): g for g in csv.DictReader(cfg["gold"].open(encoding="utf-8-sig"))}
    runs = cfg["runs"]
    if not a.score:
        for m in methods:
            (runs / m).mkdir(parents=True, exist_ok=True)
            if m == "M0":
                for c in cases:
                    run_case(runs, m, c)
            else:
                with ThreadPoolExecutor(max_workers=a.workers) as ex:
                    list(ex.map(lambda c: run_case(runs, m, c), cases))
            print(f"{m} 완료", flush=True)
    tools = {m: {c["id"]: load_tool(runs, m, c["id"]) for c in cases} for m in methods}
    result = {m: score(gold, tools[m]) for m in methods}
    gold_hash = hashlib.sha256(cfg["gold"].read_bytes()).hexdigest()[:16]
    code_hash = hashlib.sha256((ROOT / "scripts/consult_prep.py").read_bytes()).hexdigest()[:16]
    import llm
    result["meta"] = {"모델": f"{llm.CODEX_MODEL}(M2n·M3 실행 시 기본값; M1·M2는 11/3 설정 기본 모델, {llm.LEGACY_MODEL} 추정)", "세트": cfg["title"], "정답표": cfg["gold"].name, "sha256_16": gold_hash, "consult_prep_sha256_16": code_hash,
                      "실행": datetime.now().isoformat(timespec="minutes")}
    out_json = ROOT / f"data/processed/e2_eval_{a.set}.json"
    out_md = ROOT / f"30_analysis/결과_E2_{a.set}.md"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")

    pct = lambda d: f"{d['맞음']}/{d['분모']} ({d['맞음'] / d['분모']:.0%})" if d["분모"] else "0/0"
    head = " | ".join(NAMES[m] for m in methods)
    L = [f"# 결과: E2 요건 대조 — {cfg['title']} ({datetime.now():%Y-%m-%d %H:%M})", "",
         f"> 규칙: `30_analysis/E2_측정_사전등록.md`, `30_analysis/E2_v2_사전등록.md`(실행 전 고정). 정답표: `data/labels/{cfg['gold'].name}`(sha256 {gold_hash}). 도구 코드 `consult_prep.py` sha256 {code_hash}.",
         f"> 채점 대상 {result[methods[0]]['n']}건. 모델: {result['meta']['모델']}. M0 = 규칙 기준선(LLM 없음), M1 = 시제품 v1(LLM 추출 + 키워드 유형 규칙), M2 = 시제품 v2(M1 + LLM 유형 선택·협의제외 대조), M2n = v2 코드를 새 모델로 다시 돌린 것, M3 = v3(M2 + 대상·중복 조건 LLM 대조; 모든 세트를 본 뒤 만든 개발판, 새 모델). M1·M2는 11/3 모델(gpt-6-astra 추정), M2n·M3는 {llm.CODEX_MODEL}.", "",
         "## 항목별 정확도", "", f"| 항목 | {head} | 비고 |", "|---|" + "---:|" * len(methods) + "---|"]
    for f in FIELDS:
        L.append(f"| {f} | " + " | ".join(pct(result[m]["fields"][f]) for m in methods) + f" | {result[methods[-1]]['fields'][f].get('조건', '')} |")
    for x, y in (("M1", "M2"), ("M2", "M2n"), ("M2n", "M3"), ("M3", "M4"), ("M4", "M5"), ("M5", "M5b"), ("M5", "M6")):
        if x in methods and y in methods:
            c1, c2 = set(result[x]["correct_ids"]), set(result[y]["correct_ids"])
            L += ["", f"**유형판정 짝 비교({x} vs {y})**: 둘 다 맞음 {len(c1 & c2)} · {y}만 맞음 {len(c2 - c1)} · {x}만 맞음 {len(c1 - c2)} · 둘 다 틀림 {result[x]['n'] - len(c1 | c2)}"]
    ids = [i for i, g in gold.items() if g.get("동일", "예") != "아니오"]
    always = lambda f, v: f"{sum(gold[i][f] == v for i in ids)}/{len(ids)}"
    L += ["", f"**기준선(정답표에서 셈)**: 유형판정 '항상 일반' {always('유형판정', '일반')} · 유형연번 '항상 해당없음' {always('유형연번', '해당없음')}"]
    layer = {r.get("협의ID"): r.get("층") for r in rows if r.get("층")}
    if layer:
        L += ["", "## 층별 유형판정(T = 사업명에 신속 유형 낱말 있음, O = 없음)", "",
              f"| 층 | 건수 | 정답 분포 | 항상 일반 | {head} |", "|---|---:|---|---:|" + "---:|" * len(methods)]
        for ly in sorted(set(layer.values()), reverse=True):
            sub_ids = [i for i in ids if layer.get(i) == ly]
            dist = Counter(gold[i]["유형판정"] for i in sub_ids)
            cells = [f"{sum(i in set(result[m]['correct_ids']) for i in sub_ids)}/{len(sub_ids)}" for m in methods]
            L.append(f"| {ly} | {len(sub_ids)} | " + " · ".join(f"{k} {v}" for k, v in dist.most_common()) + f" | {sum(gold[i]['유형판정'] == '일반' for i in sub_ids)}/{len(sub_ids)} | " + " | ".join(cells) + " |")
        L += ["", "| 층 | 유형연번 " + " | ".join(methods) + " | 항상 해당없음 |", "|---|" + "---:|" * (len(methods) + 1)]
        for ly in sorted(set(layer.values()), reverse=True):
            sub_ids = [i for i in ids if layer.get(i) == ly]
            cells = [f"{sum((tools[m][i] or {}).get('유형연번', '') == gold[i]['유형연번'] for i in sub_ids)}/{len(sub_ids)}" for m in methods]
            L.append(f"| {ly} | " + " | ".join(cells) + f" | {sum(gold[i]['유형연번'] == '해당없음' for i in sub_ids)}/{len(sub_ids)} |")
        result["layers"] = {ly: {m: sum(i in set(result[m]["correct_ids"]) for i in ids if layer.get(i) == ly) for m in methods} for ly in set(layer.values())}
        out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")
    fast_wrong = {m: [i for i in ids if (tools[m][i] or {}).get("유형판정") == "신속" and gold[i]["유형판정"] != "신속"] for m in methods}
    L += ["", "**신속 오권고(정답이 신속이 아닌데 신속)**: " + " · ".join(f"{m} {len(v)}건{(' (' + ', '.join(v) + ')') if v else ''}" for m, v in fast_wrong.items())]
    L += ["", "## 보류(확인불가) 지표", "", "| 항목 | 방법 | 필요한 보류를 잡음 | 놓침 | 불필요한 보류 | 분모 |", "|---|---|---:|---:|---:|---:|"]
    for f in ("유형판정", "대상", "상한"):
        for m in methods:
            h = result[m]["holds"][f]
            L.append(f"| {f} | {m} | {h['필요한 보류를 잡음']} | {h['필요한 보류를 놓침']} | {h['불필요한 보류']} | {h['분모']} |")
    L += ["", "근거 구절 불일치가 있는 사례: " + " · ".join(f"{m} {result[m]['evidence_failed_cases']}건" for m in methods if m != "M0")
          + " · 실행 실패: " + ", ".join(f"{m} {result[m]['missing_runs']}" for m in methods), "",
          "## 유형판정 혼동(정답→도구)", "", f"| 정답→도구 | {' | '.join(methods)} |", "|---|" + "---:|" * len(methods)]
    keys = sorted(set().union(*(result[m]["verdict_confusion"] for m in methods)))
    L += [f"| {k} | " + " | ".join(str(result[m]["verdict_confusion"].get(k, 0)) for m in methods) + " |" for k in keys]
    L += ["", "## 사례별", "", f"| # | 사례 | 기관 | 사업 | 정답(연번/대상/상한/제외/판정) | {' | '.join(methods)} |", "|---|---|---|---|---|" + "---|" * len(methods)]
    fmt = lambda d: "/".join((d or {}).get(f, "") or "-" for f in FIELDS) if d else "실패"
    for n, c in enumerate(cases, 1):
        g = gold[c["id"]]
        if g.get("동일", "예") == "아니오":
            continue
        L.append(f"| {n} | {c['id']} | {c['org'][:14]} | {c['name'][:24]} | {fmt(g)} | " + " | ".join(fmt(tools[m][c["id"]]) for m in methods) + " |")
    out_md.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:24]))


if __name__ == "__main__":
    main()
