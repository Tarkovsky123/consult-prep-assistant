"""시제품 v3 한 사례를 캐시 없이 다시 돌려 LLM 호출마다 토큰 사용량을 잰다(비용 산정용, 11/5).

  python -X utf8 scripts/measure_tokens.py 393 474 434
입력: 30_analysis/시제품_예시/E3/<사례>.json 의 input(E3 시연과 같은 인자)
출력: data/processed/token_usage.json (사례별·호출별 input/cached/output 토큰, 모델)
Codex CLI에 --json을 붙여 이벤트의 usage를 읽는다. 결과 캐시는 임시 폴더에 두고 지운다(기존 캐시를 건드리지 않음).
"""
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import llm  # noqa: E402
import consult_prep  # noqa: E402

CALLS = []
_run = subprocess.run


def run_with_usage(cmd, *a, **kw):
    if isinstance(cmd, list) and cmd and cmd[0] == llm.CODEX and "exec" in cmd and "--json" not in cmd:
        cmd = cmd[:2] + ["--json"] + cmd[2:]
        r = _run(cmd, *a, **kw)
        usage = {}
        for line in (r.stdout or "").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            u = ev.get("usage") or (ev.get("msg") or {}).get("usage")
            if isinstance(u, dict):
                usage = u  # 마지막 turn의 누적값
        CALLS.append({"prompt_chars": len(kw.get("input") or ""), "usage": usage})
        return r
    return _run(cmd, *a, **kw)


def flags(inp):
    out = []
    for k, v in inp.items():
        if k in ("out", "json") or v in (None, "", False):
            continue
        f = "--" + k.replace("_", "-")
        out += [f] if v is True else [f, str(v)]
    return out


def main(ids):
    llm.subprocess.run = run_with_usage
    prev = ROOT / "data/processed/token_usage.json"
    res = [r for r in (json.loads(prev.read_text(encoding="utf-8"))["사례"] if prev.exists() else []) if r["case"] not in ids]
    for cid in ids:
        inp = json.loads((ROOT / f"30_analysis/시제품_예시/E3/{cid}.json").read_text(encoding="utf-8"))["input"]
        with tempfile.TemporaryDirectory() as tmp:
            consult_prep.PROPOSAL_CACHE = Path(tmp) / "cache"
            start = len(CALLS)
            sys.argv = ["consult_prep.py", *flags(inp), "--out", str(Path(tmp) / "o.md"), "--json", str(Path(tmp) / "o.json")]
            consult_prep.main()
            calls = CALLS[start:]
        res.append({"case": cid, "calls": calls})
        print(cid, [(c["prompt_chars"], c["usage"]) for c in calls])
    out = {"설명": "시제품 v3(E3 시연과 같은 인자)를 캐시 없이 다시 돌려 Codex CLI --json 이벤트의 usage를 모은 값. 비용 산정용(11/5 측정)",
           "모델": llm.CODEX_MODEL, "추론_노력": "medium", "사례": res}
    tot = [sum(c["usage"].get(k, 0) for c in r["calls"]) for r in res for k in ("input_tokens",)]
    out["사례별_input_tokens"] = tot
    out["사례별_output_tokens"] = [sum(c["usage"].get("output_tokens", 0) for c in r["calls"]) for r in res]
    out["사례별_cached_input_tokens"] = [sum(c["usage"].get("cached_input_tokens", 0) for c in r["calls"]) for r in res]
    out["사례별_호출수"] = [len(r["calls"]) for r in res]
    (ROOT / "data/processed/token_usage.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k.startswith("사례별")}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:] or ["393"])
