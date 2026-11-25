"""E3 캡처: 설치된 Chrome의 화면 없는 모드로 preview.html을 2배 해상도 PNG로 찍고, 아래 빈 여백을 잘라 낸다.

  python -X utf8 30_analysis/시제품_예시/E3/화면/capture.py            # 제안서용 캡처(960px 보기)
  python -X utf8 30_analysis/시제품_예시/E3/화면/capture.py --check    # 점검용: 일반 보기 데스크톱·휴대폰 폭
출력: ../캡처/<이름>.png
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "캡처"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CAPS = {"그림_393_판정근거": ("c393-why", 720), "그림_393_비교대상": ("c393-cmp", 720), "그림_S3_중복조건": ("cS3-why", 720)}
CHECKS = {"점검_393_데스크톱": ("c393", 1280), "점검_397_휴대폰": ("c397", 390)}


def shot(name, frag, width, height=4200, scale=2):
    url = (HERE / "preview.html").as_uri() + "#" + frag
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.png"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                        f"--window-size={width},{height}", "--virtual-time-budget=4000", f"--screenshot={raw}", url],
                       check=True, capture_output=True, timeout=120)
        im = Image.open(raw).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((im.width - 2, im.height - 2)))
    box = ImageChops.difference(im, bg).getbbox()
    if box:
        im = im.crop((0, 0, im.width, min(im.height, box[3] + 8 * scale)))  # 아래 여백 8px(쪽 높이 절약)
    OUT.mkdir(exist_ok=True)
    p = OUT / f"{name}.png"
    im.save(p)
    print(f"{p.name}: {im.width}x{im.height}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    for n, (frag, w) in (CHECKS if a.check else CAPS).items():
        shot(n, frag, w, scale=1 if a.check else 2)
