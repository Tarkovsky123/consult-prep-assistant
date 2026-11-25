"""E3 시연 화면 만들기: 데이터(prep.py) → Pretendard 부분 글꼴(페이지에 쓰인 글자만) → template에 넣기.

  python -X utf8 30_analysis/시제품_예시/E3/화면/build.py
출력(이 폴더): data.json, 협의준비도우미_시연.html(게시용), preview.html(게시 뼈대를 씌운 로컬 확인용)
글꼴: KRDS 지정 서체 Pretendard GOV 1.3.9(OFL) — C:/Users/USER/Desktop/project/Contest/_공통/fonts/Pretendard GOV
     (11/5 사용자 승인으로 github.com/orioncactus/pretendard 릴리스에서 받음). 페이지에 쓰인 글자만 잘라 WOFF로 넣는다.
"""
import base64
import io
import json
import runpy
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
FONTS = Path(r"C:\Users\USER\Desktop\project\Contest\_공통\fonts\Pretendard GOV")
FAMILY = "Pretendard GOV"
WEIGHTS = {400: "PretendardGOV-Regular.ttf", 700: "PretendardGOV-Bold.ttf"}  # KRDS 굵기: Regular · Bold


def strings(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)
    elif isinstance(x, str):
        yield x


def woff_subset(path, text):
    font = TTFont(path)
    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["*"]
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff"
    font.save(buf)
    return buf.getvalue()


def main():
    runpy.run_path(str(HERE / "prep.py"), run_name="__main__")
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    data = (HERE / "data.json").read_text(encoding="utf-8")
    chars = set(tpl) | set("".join(strings(json.loads(data)))) | set("0123456789…·“”‘’→←()[]%~-—")
    text = "".join(sorted(c for c in chars if c.isprintable()))
    faces = []
    for w, f in WEIGHTS.items():
        b = woff_subset(FONTS / f, text)
        faces.append(f'@font-face {{ font-family: "{FAMILY}"; font-weight: {w}; font-style: normal; font-display: swap; '
                     f'src: url(data:font/woff;base64,{base64.b64encode(b).decode()}) format("woff"); }}')
        print(f"{FAMILY} {w}: {len(b) // 1024} KB (글자 {len(text)}개)")
    assert tpl.count("/*__FONTS__*/") == 1 and tpl.count("/*__DATA__*/null") == 1
    html = tpl.replace("/*__FONTS__*/", "\n".join(faces)).replace("/*__DATA__*/null", data.replace("</", "<\\/"))
    (HERE / "협의준비도우미_시연.html").write_text(html, encoding="utf-8")
    head = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>:root{color-scheme:light}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style></head><body>')
    (HERE / "preview.html").write_text(head + html + "</body></html>", encoding="utf-8")
    (HERE / "_check.js").write_text(html.split("<script>")[1].split("</script>")[0], encoding="utf-8")
    print(f"협의준비도우미_시연.html {len(html.encode('utf-8')) // 1024} KB")


if __name__ == "__main__":
    main()
