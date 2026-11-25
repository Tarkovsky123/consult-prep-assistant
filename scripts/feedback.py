"""담당자 결재·피드백 저장소(30_analysis/v4_개선_사전등록.md §11).

도구 출력(잠정 권고)에 담당자가 승인하거나 고친 최종 판정과 이유를 적어 쌓는다. 승인된 기록만 다음 판정의 '확정 선례'로 쓰인다.
  python -X utf8 scripts/feedback.py add <출력.json> --final 유형연번=15 유형판정=신속 --reason "청소년 바우처는 15번" [--by 담당자]
      → data/feedback/feedback_store.jsonl 에 status='제출'로 한 줄 추가(도구 판정과 다르면 '고침', 같으면 '승인 요청')
  python -X utf8 scripts/feedback.py approve <id> [...]        # 검토자가 승인 → 선례로 쓰임
  python -X utf8 scripts/feedback.py reject <id> --why "..."   # 쓰지 않음(기록은 남긴다)
  python -X utf8 scripts/feedback.py list
  python -X utf8 scripts/feedback.py seed                      # 실험용: 고정 정답표(E2·E2b·E2c)를 승인된 기록으로 넣는다
한 줄: {id, date, by, org, name, text, tool{…}, final{유형연번, 대상, 상한, 협의제외, 유형판정}, reason, kind(승인|고침), status(제출|승인|반려), source}
"""
import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data/feedback/feedback_store.jsonl"
FIELDS = ["유형연번", "대상", "상한", "협의제외", "유형판정"]


def read():
    return [json.loads(l) for l in STORE.read_text(encoding="utf-8").splitlines() if l.strip()] if STORE.exists() else []


def write(rows):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def store_hash():
    return hashlib.sha256(STORE.read_bytes()).hexdigest()[:16] if STORE.exists() else ""


def cmd_add(a):
    rep = json.loads(Path(a.output).read_text(encoding="utf-8"))
    tool = rep["eval"]
    final = dict(tool)
    for kv in a.final or []:
        k, v = kv.split("=", 1)
        assert k in FIELDS, f"고칠 수 있는 칸: {FIELDS}"
        final[k] = v
    inp = rep["input"]
    text = inp.get("text") or "\n".join(x for x in (inp.get("target"), inp.get("criteria"), inp.get("content")) if x)
    rid = a.id or "F" + hashlib.sha1((inp["name"] + text).encode("utf-8")).hexdigest()[:8]
    row = {"id": rid, "date": datetime.now().isoformat(timespec="minutes"), "by": a.by, "org": inp.get("org", ""), "name": inp["name"], "text": text,
           "tool": tool, "tentative": (rep.get("tentative") or {}).get("권고"), "final": final, "reason": a.reason or "",
           "kind": "승인" if final == tool else "고침", "status": "제출", "source": "담당자 결재"}
    rows = [r for r in read() if r["id"] != rid] + [row]
    write(rows)
    print(f"{rid} 저장({row['kind']}, 상태 제출). 승인 전에는 선례로 쓰이지 않는다. 저장소 {len(rows)}줄")


def cmd_status(a, status):
    rows = read()
    for r in rows:
        if r["id"] in a.ids:
            r["status"] = status
            if status == "반려":
                r["reject_why"] = a.why or ""
    write(rows)
    print(f"{a.ids} → {status}. 저장소 sha256 {store_hash()}")


def cmd_list(a):
    for r in read():
        print(f"{r['id']:>10} {r['status']} {r['kind']} | {r['name'][:28]} | 도구 {r['tool'].get('유형판정') if r.get('tool') else '-'} → 확정 {r['final'].get('유형연번')}/{r['final'].get('유형판정')} | {r['reason'][:40]}")
    print(f"{len(read())}줄, sha256 {store_hash()}")


def cmd_seed(a):
    """실험용 저장소: 고정 정답표를 '승인된 담당자 결재'로 본다. E2d(시험)는 넣지 않는다."""
    rows = []
    lb = ROOT / "data/labels"
    for cases, gold, src in (("E2_요건대조_라벨시트.csv", "E2_정답표_고정_20261103.csv", "E2"), ("E2b_요건대조_사례.csv", "E2b_정답표_고정_20261103.csv", "E2b"),
                             ("E2c_요건대조_사례.csv", "E2c_정답표_고정_20261106.csv", "E2c")):
        cs = {r["협의ID"]: r for r in csv.DictReader((lb / cases).open(encoding="utf-8-sig"))}
        for g in csv.DictReader((lb / gold).open(encoding="utf-8-sig")):
            if g["동일"] != "예":
                continue
            c = cs[g["협의ID"]]
            rows.append({"id": g["협의ID"], "date": g["저장시각"], "by": "제안자(정답표)", "org": g["협의요청기관"], "name": g["협의 사업명"],
                         "text": f"[지원대상] {c['원문 지원대상']}\n[선정기준] {c['원문 선정기준']}\n[지원내용] {c['원문 지원내용']}",
                         "tool": None, "final": {f: g[f] for f in FIELDS}, "reason": g["메모"], "kind": "정답표", "status": "승인", "source": src})
    write(rows)
    print(f"{len(rows)}줄 → {STORE} (sha256 {store_hash()})")


def cmd_import(a):
    """도입 준비 키트: 기관이 미리 판정해 둔 사례 CSV를 선례로 넣는다. 열: id, 기관, 사업명, 원문, 유형연번, 대상, 상한, 협의제외, 유형판정, 메모.
    기본 상태는 '제출'이고 --approved 를 줘야 바로 선례로 쓰인다(검토자가 확인한 묶음일 때만)."""
    rows = read()
    have = {r["id"] for r in rows}
    n = 0
    for r in csv.DictReader(Path(a.csv).open(encoding="utf-8-sig")):
        if r["id"] in have:
            continue
        assert r["유형판정"] in ("협의제외", "신속", "일반", "확인불가"), f"{r['id']}: 유형판정 값 확인"
        rows.append({"id": r["id"], "date": datetime.now().isoformat(timespec="minutes"), "by": a.by, "org": r.get("기관", ""), "name": r["사업명"], "text": r.get("원문", ""),
                     "tool": None, "final": {f: r.get(f, "") for f in FIELDS}, "reason": r.get("메모", ""), "kind": "사전 판정",
                     "status": "승인" if a.approved else "제출", "source": a.source or Path(a.csv).name})
        n += 1
    write(rows)
    print(f"{n}줄 가져옴(상태 {'승인' if a.approved else '제출'}). 저장소 {len(rows)}줄, sha256 {store_hash()}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    x = sp.add_parser("import"); x.add_argument("csv"); x.add_argument("--by", default="기관 담당자"); x.add_argument("--source"); x.add_argument("--approved", action="store_true")
    x = sp.add_parser("add"); x.add_argument("output"); x.add_argument("--final", nargs="*"); x.add_argument("--reason"); x.add_argument("--by", default="담당자"); x.add_argument("--id")
    x = sp.add_parser("approve"); x.add_argument("ids", nargs="+")
    x = sp.add_parser("reject"); x.add_argument("ids", nargs="+"); x.add_argument("--why")
    sp.add_parser("list"); sp.add_parser("seed")
    a = ap.parse_args()
    {"add": cmd_add, "approve": lambda a: cmd_status(a, "승인"), "reject": lambda a: cmd_status(a, "반려"), "list": cmd_list, "seed": cmd_seed, "import": cmd_import}[a.cmd](a)
