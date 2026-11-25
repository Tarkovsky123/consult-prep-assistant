"""복지사업 설명문 → 표준 지원조건(schema.py) 구조화.

실행 예:
  python -X utf8 scripts/structure_services.py --source private --backend codex --limit 5      # 시험
  python -X utf8 scripts/structure_services.py --source private --backend codex --workers 4    # 전체
  python -X utf8 scripts/structure_services.py --source local --sido 대구광역시 경상북도 --backend codex
  python -X utf8 scripts/structure_services.py --source local --detail-only --backend codex   # 전국: 상세를 받은 사업만(C4, 11/6)
출력: data/processed/structured_<source>_<backend>.jsonl (이미 처리한 id는 건너뛰어 이어서 실행할 수 있다)
"""
import argparse
import csv
import io
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from llm import ask  # noqa: E402
from schema import BATCH_SCHEMA, INSTRUCTION, verify_evidence  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
CLIP = 700  # 필드 하나당 최대 글자 수(긴 신청방법·서류 목록이 입력을 키우지 않게)


def clip(s):
    s = "" if pd.isna(s) else str(s).strip()
    return s[:CLIP]


def load_private():
    raw = (RAW / "민간복지서비스_20251105.csv").read_bytes()
    df = pd.read_csv(io.BytesIO(raw), encoding="cp949")
    for i, r in df.iterrows():
        parts = [f"[사업명] {clip(r['사업명'])}", f"[기관] {clip(r['기관명'])}"]
        for col in ("사업목적", "지원대상", "지원내용", "제출서류"):
            if clip(r[col]):
                parts.append(f"[{col}] {clip(r[col])}")
        yield {"id": f"PRV{i:04d}", "name": clip(r["사업명"]), "org": clip(r["기관명"]),
               "tags": {"생애주기": clip(r["생애주기"]), "가구상황": clip(r["가구상황"]), "관심주제": clip(r["관심주제"])},
               "text": "\n".join(parts)}


def load_local(sidos):
    rows = list(csv.DictReader((RAW / "api/local_list.csv").open(encoding="utf-8-sig")))
    detail_dir = RAW / "api/local_detail"
    for r in rows:
        if sidos and r["ctpvNm"] not in sidos:
            continue
        p = detail_dir / f"{r['servId']}.json"
        d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        parts = [f"[사업명] {clip(r['servNm'])}", f"[지역] {r['ctpvNm']} {r['sggNm']}", f"[요약] {clip(r['servDgst'])}"]
        for key, label in (("sprtTrgtCn", "지원대상"), ("slctCritCn", "선정기준"), ("alwServCn", "지원내용")):
            if clip(d.get(key)):
                parts.append(f"[{label}] {clip(d.get(key))}")
        yield {"id": r["servId"], "name": r["servNm"], "org": f"{r['ctpvNm']} {r['sggNm']}",
               "tags": {"생애주기": r["lifeNmArray"], "가구상황": r["trgterIndvdlNmArray"], "관심주제": r["intrsThemaNmArray"]},
               "has_detail": p.exists(), "text": "\n".join(parts)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["private", "local"], required=True)
    ap.add_argument("--sido", nargs="*", default=[])
    ap.add_argument("--backend", choices=["codex", "agy"], default="codex")
    ap.add_argument("--batch", type=int, default=12)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--detail-only", action="store_true", help="지자체: 상세 원문을 받은 사업만(목록 요약만 있는 사업은 건너뜀)")
    a = ap.parse_args()

    items = list(load_private() if a.source == "private" else load_local(a.sido))
    if a.detail_only:
        items = [it for it in items if it.get("has_detail")]
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"structured_{a.source}_{a.backend}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(line)["id"] for line in out_path.open(encoding="utf-8")}
    todo = [it for it in items if it["id"] not in done]
    if a.limit:
        todo = todo[:a.limit]
    batches = [todo[i:i + a.batch] for i in range(0, len(todo), a.batch)]
    print(f"대상 {len(items)}건, 이미 처리 {len(done)}건, 이번 {len(todo)}건 / 배치 {len(batches)}개")

    lock = threading.Lock()

    def run(batch):
        payload = {"사업": [{"id": it["id"], "원문": it["text"]} for it in batch]}
        out, sec = ask(a.backend, INSTRUCTION, payload, BATCH_SCHEMA)
        got = {x["id"]: x for x in out.get("items", [])}
        rows = []
        for it in batch:
            m = got.get(it["id"])
            rows.append({**{k: it[k] for k in ("id", "name", "org", "tags", "text")},
                         "backend": a.backend, "sec_per_item": round(sec / len(batch), 1),
                         "output": m, "missing": m is None,
                         "evidence_failed": verify_evidence(m, it["text"]) if m else []})
        with lock, out_path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return len(rows), sum(r["missing"] for r in rows), sec

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futures = [ex.submit(run, b) for b in batches]
        for n, fut in enumerate(as_completed(futures), 1):
            try:
                k, miss, sec = fut.result()
                print(f"  배치 {n}/{len(batches)}: {k}건, 누락 {miss}, {sec:.0f}초", flush=True)
            except Exception as e:  # 한 배치 실패가 전체를 멈추지 않게 하고, 다음 실행 때 다시 시도된다
                print(f"  배치 {n}/{len(batches)} 실패: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"→ {out_path}")


if __name__ == "__main__":
    main()
