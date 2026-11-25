"""지자체복지서비스 API(한국사회보장정보원, 공공데이터포털)에서 서비스 목록과 상세를 받는다.

준비: 공공데이터포털에서 '한국사회보장정보원_지자체복지서비스' 활용신청(자동승인) 후
      프로젝트 루트 .env 에 DATA_GO_KR_KEY=<일반 인증키(Decoding)> 한 줄을 넣는다.
실행:
  python -X utf8 scripts/fetch_local_services.py list                 # 전국 목록 → data/raw/api/local_list.csv
  python -X utf8 scripts/fetch_local_services.py detail --sido 대구광역시 경상북도 --limit 900
      # 해당 시도 서비스 상세를 data/raw/api/local_detail/<servId>.json 으로 캐시(이미 받은 것은 건너뜀)
개발계정 트래픽은 하루 1,000건이라 상세는 --limit 으로 나눠 받는다.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.client
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "data/raw/api"
BASE = "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations"
LIST_FIELDS = ["servId", "servNm", "ctpvNm", "sggNm", "bizChrDeptNm", "servDgst", "lifeNmArray",
               "trgterIndvdlNmArray", "intrsThemaNmArray", "sprtCycNm", "srvPvsnNm", "aplyMtdNm",
               "inqNum", "lastModYmd", "servDtlLink"]


def service_key():
    key = os.environ.get("DATA_GO_KR_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATA_GO_KR_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        sys.exit("DATA_GO_KR_KEY 가 없습니다. 프로젝트 루트 .env 에 넣어 주세요.")
    return key


def call(op, **params):
    query = urllib.parse.urlencode({"serviceKey": service_key(), **params})
    for attempt in range(6):  # 11/10: 연결 끊김(RemoteDisconnected·시간 초과)도 잡고 더 오래 기다린다
        try:
            with urllib.request.urlopen(f"{BASE}/{op}?{query}", timeout=30) as r:
                root = ET.fromstring(r.read())
            break
        except (OSError, http.client.HTTPException, ET.ParseError) as e:
            if attempt == 5:
                raise
            time.sleep(5 * (attempt + 1))
    code = root.findtext(".//resultCode")
    if code not in (None, "0", "00"):
        raise RuntimeError(f"{op} 실패: {code} {root.findtext('.//resultMessage')}")
    return root


def fetch_list(rows=500):
    first = call("LcgvWelfarelist", pageNo=1, numOfRows=rows)
    total = int(first.findtext(".//totalCount") or 0)
    items, page, root = [], 1, first
    while True:
        items += [{f: (s.findtext(f) or "").strip() for f in LIST_FIELDS} for s in root.iter("servList")]
        if len(items) >= total or page * rows >= total:
            break
        page += 1
        time.sleep(0.2)
        root = call("LcgvWelfarelist", pageNo=page, numOfRows=rows)
    API_DIR.mkdir(parents=True, exist_ok=True)
    out = API_DIR / "local_list.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LIST_FIELDS)
        w.writeheader()
        w.writerows(items)
    print(f"목록 {len(items)}건 / totalCount {total} → {out}")


def element_to_dict(el):
    """상세 응답의 단일 값과 반복 목록(inqplCtadrList 등)을 그대로 보존한다."""
    out = {}
    for child in el:
        if len(child):
            out.setdefault(child.tag, []).append({c.tag: (c.text or "").strip() for c in child})
        else:
            out[child.tag] = (child.text or "").strip()
    return out


def fetch_detail(sidos, limit):
    rows = list(csv.DictReader((API_DIR / "local_list.csv").open(encoding="utf-8-sig")))
    targets = [r["servId"] for r in rows if not sidos or r["ctpvNm"] in sidos]
    cache = API_DIR / "local_detail"
    cache.mkdir(parents=True, exist_ok=True)
    todo = [s for s in targets if not (cache / f"{s}.json").exists()][:limit]
    for i, serv_id in enumerate(todo, 1):
        root = call("LcgvWelfaredetailed", servId=serv_id)
        body = root.find(".//body")
        data = element_to_dict(body if body is not None else root)
        (cache / f"{serv_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        if i % 50 == 0:
            print(f"  상세 {i}/{len(todo)}")
        time.sleep(0.1)
    done = sum((cache / f"{s}.json").exists() for s in targets)
    print(f"상세 {len(todo)}건 받음 / 대상 {len(targets)}건 중 {done}건 캐시됨")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    d = sub.add_parser("detail")
    d.add_argument("--sido", nargs="*", default=[])
    d.add_argument("--limit", type=int, default=900)
    a = ap.parse_args()
    fetch_list() if a.cmd == "list" else fetch_detail(a.sido, a.limit)
