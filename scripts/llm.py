"""같은 지시·JSON 스키마를 백엔드만 바꿔 보낸다.

  codex  OpenAI 모델(Codex CLI --output-schema, 구독 로그인. API 키 불필요)
  agy    Gemini(Antigravity CLI --json-schema). 긴 입력은 작업 폴더의 파일로 넘긴다
환경 변수: CODEX_EXE, CODEX_MODEL(기본 gpt-6.1-sol), CODEX_EFFORT(기본 medium), AGY_EXE, AGY_MODEL(기본 gemini-3.8-flash-high)

모델(11/5): 11/3까지는 -m 없이 Codex 설정 기본 모델로 돌았다(설정값 gpt-6-astra로 추정, 기록 없음).
11/5 그 모델이 이 계정에서 지원되지 않아 모델을 명시한다. 캐시 키에는 cache_tag()를 붙여 모델별로 나눈다(옛 캐시는 태그 없음).
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CODEX = os.environ.get("CODEX_EXE") or shutil.which("codex") or next(
    (str(p) for p in (Path.home() / "AppData/Local/OpenAI/Codex/bin").glob("*/codex.exe")), "codex")
AGY = os.environ.get("AGY_EXE") or shutil.which("agy") or str(Path.home() / "AppData/Local/agy/bin/agy.exe")
AGY_MODEL = os.environ.get("AGY_MODEL", "gemini-3.8-flash-high")
NO_TOOLS = "명령을 실행하거나 웹을 검색하지 마라. 주어진 입력만 보고 답하라."
CODEX_MODEL = os.environ.get("CODEX_MODEL", "gpt-6.1-sol")
LEGACY_MODEL = "gpt-6-astra"  # 11/3 측정 캐시의 모델(추정)


def cache_tag():
    """캐시 키 꼬리표. 옛 모델이면 빈 문자열이라 11/3 캐시를 그대로 쓴다."""
    return "" if CODEX_MODEL == LEGACY_MODEL else f"|{CODEX_MODEL}"


def parse_json(text):
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("JSON을 찾지 못함")
    return json.loads(text[start:end + 1])


RETRIES = int(os.environ.get("LLM_RETRIES", "2"))  # 11/10 안정성 보완: 호출 실패·깨진 JSON이면 다시 부른다(판정 논리 아님)


def ask(backend, instruction, payload, schema, timeout=900):
    """(결과 dict, 걸린 초)를 돌려준다. 실패하면 RETRIES번까지 다시 부르고, 그래도 안 되면 마지막 예외를 낸다(값을 지어내지 않는다)."""
    for attempt in range(RETRIES + 1):
        try:
            return _ask_once(backend, instruction, payload, schema, timeout)
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            if attempt == RETRIES or "알 수 없는 백엔드" in str(e):
                raise
            print(f"  LLM 호출 실패({type(e).__name__}), {attempt + 1}번째 재시도", flush=True)
            time.sleep(5 * (attempt + 1))


def _ask_once(backend, instruction, payload, schema, timeout):
    body = json.dumps(payload, ensure_ascii=False)
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        schema_path = tmp / "schema.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        if backend == "codex":
            out_path = tmp / "out.json"
            prompt = f"{instruction}\n{NO_TOOLS}\n출력은 스키마를 따르는 JSON 하나다.\n입력:\n{body}"
            effort = os.environ.get("CODEX_EFFORT", "medium")
            r = subprocess.run([CODEX, "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
                                "-m", CODEX_MODEL, "-c", f"model_reasoning_effort={effort}",
                                "--output-schema", str(schema_path), "-o", str(out_path), "-"],
                               input=prompt, cwd=tmp, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
            if not out_path.exists():
                raise RuntimeError(f"codex 실패: {r.stderr[-500:]}")
            return parse_json(out_path.read_text(encoding="utf-8")), time.time() - t0
        if backend == "agy":
            (tmp / "input.json").write_text(body, encoding="utf-8")
            (tmp / "instruction.md").write_text(instruction, encoding="utf-8")
            r = subprocess.run([AGY, "-p", "현재 작업 폴더의 instruction.md 지시대로 input.json을 처리하라. "
                                "파일을 쓰거나 고치지 마라. " + NO_TOOLS,
                                "--model", AGY_MODEL, "--sandbox", "--json-schema", str(schema_path),
                                "--print-timeout", f"{timeout}s"],
                               cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout + 60)
            return parse_json(r.stdout), time.time() - t0
    raise ValueError(f"알 수 없는 백엔드: {backend}")
