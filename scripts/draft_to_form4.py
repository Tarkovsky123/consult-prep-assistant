"""제안서 초안(90_output/draft.md)을 서식 4 채우기 지시(JSON)로 바꾼다. hwp_form4.ps1이 읽는다.

  python -X utf8 scripts/draft_to_form4.py [--out 90_output/hwp/ops_form4.json] [--tag v1.6]

- 아이디어 요약 ◦ 줄 → '(5줄 이내)' 오른쪽 칸
- 【제안서 요약】 표 6행 → 각 행 이름 오른쪽 칸(◦ 3개). 위 행 이름이 아래 행 글에 섞여 잡히지 않게 아래 행부터 채운다.
- 1~7절 → 서식의 '* …' 안내 줄 자리에 문단·표·그림을 넣는다. 참고문헌은 7절 끝에 작은 글자로 붙인다.
- design.md(HWP 서식): 서식 글꼴·기호 유지, 굵게는 ▶ 줄만, 표는 머리글 행만 굵게.
- '## 부록' 아래는 읽지 않는다.
"""
import argparse, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDES = {1: "* 해결하려는 사회보장 분야의 문제", 2: "* 활용 데이터명·제공기관", 3: "* 활용할 AI 기술·도구",
          4: "* 유사 사례와 비교한", 5: "* 추진 절차, 필요한 자원", 6: "* 사회보장 현장 적용의 실현 가능성",
          7: "* 국민 편익, 복지서비스"}
ROW_ANCHORS = {"제안 배경 및 아이디어 소개": "아이디어 소개", "사회보장 데이터 활용 계획": "활용 계획",
               "AI 활용 방법 및 혁신성": "및 혁신성", "아이디어의 차별성 및 실행 방안": "실행 방안",
               "현장 적용 및 발전 가능성": "발전 가능성", "기대효과 및 ESG 가치": "ESG 가치"}
# 표 열 폭(mm). 본문 폭 176mm(용지 216mm, 좌우 여백 20mm) 안에서 조금 남긴다.
COLS = {"자료": [49, 30, 33, 58], "측정": [46, 50, 34, 44], "기존 수단": [50, 56, 68], "지표": [46, 21, 33, 36, 34]}
# 한글은 열 폭에 칸 안쪽 여백(좌우 1.8mm씩)을 더해 그린다(11/5 확인: 174mm 표가 약 189mm로 나와 여백을 넘음).
# 그래서 표 전체가 TABLE_W 안에 들도록 열마다 CELL_PAD를 빼고 비례로 줄인다.
TABLE_W, CELL_PAD = 175.0, 3.6
FIG = {"path": str(ROOT / "30_analysis/시제품_예시/E3/캡처/그림_393_판정근거.png"), "widthMM": 153.0}
REF3 = "[3] 사회보장위원회, 「2026 사회보장제도 신설·변경 협의운용지침」(신속협의 기준, 정기 컨설팅, 유사사업 조회), 2026."
REF10 = "[10] 보건복지부·경상북도·대구광역시·경산시 정보공개청구 회신(협의 통계, 협의요청서 사본 6건), 2026.11."
BODY_PT, TABLE_PT, CAP_PT, REF_PT, SUM_PT = 10.0, 9.0, 9.0, 8.0, 10.0


def unbold(s):
    return s.replace("**", "")


def para(text, kind):
    """kind: lead(▶) / b1(◦) / b2(- 또는 ①) / plain / cap / ref"""
    if kind == "lead":
        return {"t": "p", "text": unbold(text), "pt": BODY_PT, "bold": 1, "left": 0, "hang": 0, "after": 3}
    if kind == "b1":
        s = unbold(text).strip()
        label = not s.endswith(".") and len(s) < 40   # '◦ 필요 자원' 같은 소제목 줄은 다음 줄과 같은 쪽에 둔다
        return {"t": "p", "text": s, "pt": BODY_PT, "bold": 0, "left": 0, "hang": 3.6, "after": 1, "keep": 1 if label else 0}
    if kind == "b2":
        return {"t": "p", "text": unbold(text), "pt": BODY_PT, "bold": 0, "left": 3.6, "hang": 3.6, "after": 1}
    if kind == "cap":
        return {"t": "p", "text": unbold(text), "pt": CAP_PT, "bold": 0, "left": 0, "hang": 0, "after": 4, "align": 3}
    if kind == "ref":
        return {"t": "p", "text": text, "pt": REF_PT, "bold": 0, "left": 0, "hang": 4.5, "after": 0, "align": 1}
    return {"t": "p", "text": unbold(text), "pt": BODY_PT, "bold": 0, "left": 0, "hang": 0, "after": 1}


def table(rows):
    hdr, body = rows[0], rows[1:]
    cols = COLS.get(hdr[0])
    if not cols or len(cols) != len(hdr):
        raise SystemExit(f"열 폭 없음: {hdr}")
    k = (TABLE_W - CELL_PAD * len(cols)) / sum(cols)
    cols = [round(w * k, 1) for w in cols]
    return {"t": "table", "cols": cols, "rows": [[unbold(c) for c in r] for r in [hdr] + body], "pt": TABLE_PT}


def blocks_of(lines):
    out, tbl = [], []
    for ln in lines + [""]:
        s = ln.rstrip()
        if s.startswith("|"):
            row = [c.strip() for c in s.strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in row):
                tbl.append(row)
            continue
        if tbl:
            out.append(table(tbl)); tbl = []
        if not s.strip():
            continue
        t = s.strip()
        if t.startswith("**▶"):
            out.append(para(t, "lead"))
        elif t.startswith("[그림 1]"):
            out.append({"t": "fig", **FIG})
            out.append(para(t, "cap"))
        elif t.startswith("◦"):
            out.append(para(t, "b1"))
        elif s.startswith("  - "):
            out.append(para("- " + t[2:], "b2"))
        elif s.startswith("  ") and re.match(r"[①-⑩]", t):
            out.append(para(t, "b2"))
        else:
            out.append(para(t, "plain"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", default=str(ROOT / "90_output/draft.md"))
    ap.add_argument("--out", default=str(ROOT / "90_output/hwp/ops_form4.json"))
    ap.add_argument("--tag", default="v1.15")
    a = ap.parse_args()
    text = Path(a.draft).read_text(encoding="utf-8").split("\n## 부록")[0]
    title = re.search(r"^# (.+)$", text, re.M).group(1).strip()
    parts = {m.group(1).strip(): m.group(2) for m in re.finditer(r"^## (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S)}
    summary = [unbold(l.strip()) for l in parts["아이디어 요약"].splitlines() if l.strip().startswith("◦")]
    rows = []
    for l in parts["【제안서 요약】"].splitlines():
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] in ROW_ANCHORS:
            items = ["◦ " + x.strip() for x in cells[1].split("◦") if x.strip()]
            rows.append({"anchor": ROW_ANCHORS[cells[0]], "label": cells[0], "lines": [unbold(x) for x in items]})
    sections = []
    for k, body in parts.items():
        m = re.match(r"(\d)\. ", k)
        if m:
            sections.append({"no": int(m.group(1)), "guide": GUIDES[int(m.group(1))], "blocks": blocks_of(body.splitlines())})
    refs = [l.strip() for l in parts["참고문헌"].splitlines() if l.strip().startswith("[")]
    refs = [REF3 if r.startswith("[3]") else REF10 if r.startswith("[10]") else r for r in refs]
    sec7 = next(s for s in sections if s["no"] == 7)
    sec7["blocks"].append({"t": "p", "text": "참고문헌", "pt": REF_PT, "bold": 1, "left": 0, "hang": 0, "after": 0, "before": 6})
    sec7["blocks"] += [para(r, "ref") for r in refs]
    from PIL import Image
    w, h = Image.open(FIG["path"]).size
    for s in sections:
        for b in s["blocks"]:
            if b["t"] == "fig":
                b["heightMM"] = round(FIG["widthMM"] * h / w, 1)
    out_dir = Path(a.out).parent
    ops = {"template": str(ROOT / "00_brief/sources/제출양식.hwp"),
           "outHwp": str(out_dir / f"제안서_{a.tag}.hwp"), "outPdf": str(out_dir / f"제안서_{a.tag}.pdf"),
           "font": "한컴 고딕", "lineSpacing": 130,
           "nonLatinBreak": 0,  # 한글 줄 나눔을 어절 단위로(단어 중간에서 끊기지 않게, 11/6 검수)
           "docinfo": {"title": re.sub(r"\s*\([^)]*\)\s*$", "", title), "author": ""  # 한글 파일 작성자 칸(공개본에서는 비움)},
           # 공고 규정 A4(11/5 사용자 "A4로 해줘"). 서식 원래 용지는 216×303mm. 본문 영역 176×263mm를 그대로 두려고 여백을 줄인다.
           "page": {"w": 210, "h": 297, "left": 17, "right": 17, "top": 7, "bottom": 7, "header": 10, "footer": 10}, "cutAfter": "이미지 형식으로 삽입 가능)",
           "title": {"anchor": "아이디어 주제(팀명 또는 신청인명)", "text": title, "pt": 14.0},
           "summary": {"anchor": "(5줄 이내)", "lines": summary, "pt": SUM_PT},
           "rows": list(reversed(rows)), "rowPt": SUM_PT,
           "headings": [k for k in parts if re.match(r"\d\. ", k)],
           "sections": sorted(sections, key=lambda s: -s["no"]), "maxPages": 5}
    out_dir.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(ops, ensure_ascii=False, indent=1), encoding="utf-8")
    nb = sum(len(s["blocks"]) for s in sections)
    print(f"{a.out}: 요약 {len(summary)}줄, 요약표 {len(rows)}행, 절 {len(sections)}개, 블록 {nb}개, "
          f"표 {sum(b['t'] == 'table' for s in sections for b in s['blocks'])}개, 그림 {sum(b['t'] == 'fig' for s in sections for b in s['blocks'])}개")


if __name__ == "__main__":
    main()
