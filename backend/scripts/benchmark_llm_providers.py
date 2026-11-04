"""Speed test: Google AI Studio (Gemini) vs. the local OpenAI-compatible box.

Run from backend/:
  python scripts/benchmark_llm_providers.py --rounds 5
  python scripts/benchmark_llm_providers.py --env-file ../../astraphe-fixes2/backend/.env \
      --local-url http://ai-box:8080/v1 --local-model qwen3.8-flash-next-strata

Sends the same workloads to both providers, independent of LLM_PROVIDER:
  short  - one-line coaching question
  long   - ~6k tokens of training log, then a summary request (prompt processing)
  tool   - one coach turn with the real coach tool declarations (first hop only)

Timings are streamed: TTFT is the first *visible* output (text or a tool call),
not hidden reasoning. The local request is built by the same Gemini->OpenAI
translation the app uses (app/services/llm_provider.py). Secrets are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


def _preload_env_file() -> None:
    """--env-file must be applied before app.config builds `settings`."""
    for i, arg in enumerate(sys.argv):
        path = None
        if arg == "--env-file" and i + 1 < len(sys.argv):
            path = sys.argv[i + 1]
        elif arg.startswith("--env-file="):
            path = arg.split("=", 1)[1]
        if path:
            from dotenv import dotenv_values

            for k, v in dotenv_values(path).items():
                if v is not None:
                    os.environ[k] = v


_preload_env_file()

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.coach_tools import TOOLS  # noqa: E402
from app.services.llm_provider import (  # noqa: E402
    _gemini_contents_to_openai_messages,
    _gemini_tools_to_openai,
)

GEMINI_FREE_TIER_GAP_SEC = 13.0  # ~5 RPM on the free tier

SYSTEM_PROMPT = (
    "You are Astraphe, an endurance coach for triathletes. Be concise, specific, "
    "and practical. Use the provided tools when the athlete asks you to take an action."
)


def _training_log(target_chars: int = 24_000) -> str:
    sports = ["Run", "Bike", "Swim", "Strength"]
    lines = ["Date | Sport | Duration | Distance | Avg HR | TSS | RPE | Notes"]
    day = 0
    while sum(len(l) + 1 for l in lines) < target_chars:
        s = sports[day % 4]
        lines.append(
            f"2026-{8 + day // 30:02d}-{day % 30 + 1:02d} | {s} | {40 + (day * 7) % 80} min | "
            f"{(5 + (day * 3) % 40) if s != 'Strength' else 0} km | {128 + (day * 5) % 35} bpm | "
            f"{35 + (day * 11) % 90} | {3 + day % 6} | "
            f"{'legs heavy after poor sleep' if day % 5 == 0 else 'felt smooth, negative split' if day % 3 == 0 else 'steady aerobic'}"
        )
        day += 1
    return "\n".join(lines)


def _workloads() -> dict[str, dict]:
    return {
        "short": {
            "contents": "I have a sprint triathlon in 3 weeks. Should I do a long run this weekend? Answer in 3 sentences.",
            "tools": None,
            "max_tokens": 8192,
        },
        "long": {
            "contents": (
                "Here is my training log for the last few months:\n\n"
                + _training_log()
                + "\n\nSummarize my training load trend, flag any fatigue warning signs, "
                "and give one recommendation for next week. Keep it under 150 words."
            ),
            "tools": None,
            "max_tokens": 8192,
        },
        "tool": {
            "contents": "Schedule a 45 minute easy Zone 2 run for me tomorrow, 2026-11-05.",
            # Function declarations only: google_search has no OpenAI equivalent and
            # no free-tier quota on gemini-3 (see coach_tools.search_grounding_available).
            "tools": [t for t in TOOLS if getattr(t, "function_declarations", None)],
            "max_tokens": 8192,
        },
    }


@dataclass
class Run:
    provider: str
    workload: str
    warmup: bool
    ok: bool = False
    total_s: float = 0.0
    ttft_s: float | None = None
    first_any_s: float | None = None  # includes streamed reasoning (local only)
    out_tokens: int | None = None
    tok_per_s: float | None = None
    tool_called: str | None = None
    error: str | None = None
    preview: str = field(default="", repr=False)


def run_gemini(client, model: str, name: str, wl: dict, warmup: bool) -> Run:
    r = Run("gemini", name, warmup)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        max_output_tokens=wl["max_tokens"],
        tools=wl["tools"],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if wl["tools"] else None,
    )
    text: list[str] = []
    t0 = time.perf_counter()
    try:
        usage = None
        for chunk in client.models.generate_content_stream(model=model, contents=wl["contents"], config=config):
            now = time.perf_counter() - t0
            for cand in chunk.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if getattr(part, "thought", False):
                        r.first_any_s = r.first_any_s or now
                        continue
                    if part.function_call:
                        r.tool_called = part.function_call.name
                    elif not part.text:
                        continue
                    else:
                        text.append(part.text)
                    r.ttft_s = r.ttft_s or now
                    r.first_any_s = r.first_any_s or now
            if chunk.usage_metadata:
                usage = chunk.usage_metadata
        r.total_s = time.perf_counter() - t0
        if usage is not None:
            r.out_tokens = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
        r.ok = True
    except Exception as e:  # noqa: BLE001 - benchmark records failures, keeps going
        r.total_s = time.perf_counter() - t0
        r.error = f"{type(e).__name__}: {str(e)[:160]}"
    r.preview = "".join(text)
    return _finish(r)


def run_local(raw_client, model: str, name: str, wl: dict, warmup: bool) -> Run:
    r = Run("local", name, warmup)
    messages = _gemini_contents_to_openai_messages(wl["contents"], SYSTEM_PROMPT)
    kwargs = {"max_tokens": wl["max_tokens"]}
    tools = _gemini_tools_to_openai(wl["tools"])
    if tools:
        kwargs["tools"] = tools
    text: list[str] = []
    reasoning_chars = 0
    t0 = time.perf_counter()
    try:
        usage = None
        stream = raw_client.chat.completions.create(
            model=model, messages=messages, stream=True,
            stream_options={"include_usage": True}, **kwargs,
        )
        for chunk in stream:
            now = time.perf_counter() - t0
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_chars += len(reasoning)
                r.first_any_s = r.first_any_s or now
            if delta.tool_calls:
                fn = delta.tool_calls[0].function
                if fn is not None and fn.name:
                    r.tool_called = r.tool_called or fn.name
                r.ttft_s = r.ttft_s or now
                r.first_any_s = r.first_any_s or now
            if delta.content:
                text.append(delta.content)
                r.ttft_s = r.ttft_s or now
                r.first_any_s = r.first_any_s or now
        r.total_s = time.perf_counter() - t0
        if usage is not None and usage.completion_tokens:
            r.out_tokens = usage.completion_tokens
        else:
            r.out_tokens = (sum(map(len, text)) + reasoning_chars) // 4 or None
        r.ok = True
    except Exception as e:  # noqa: BLE001
        r.total_s = time.perf_counter() - t0
        r.error = f"{type(e).__name__}: {str(e)[:160]}"
    r.preview = "".join(text)
    return _finish(r)


def _finish(r: Run) -> Run:
    # End-to-end rate (output + reasoning tokens / total time): Gemini doesn't
    # stream its thinking, so a decode-only rate isn't comparable across providers.
    if r.ok and r.out_tokens and r.total_s > 0:
        r.tok_per_s = r.out_tokens / r.total_s
    if r.ok and r.workload == "tool" and not r.tool_called:
        r.error = "no tool call returned"
    status = "ok " if r.ok and not r.error else "ERR"
    tag = " (warmup)" if r.warmup else ""
    ttft = f"{r.ttft_s:6.2f}s" if r.ttft_s is not None else "   n/a"
    tps = f"{r.tok_per_s:6.1f} tok/s" if r.tok_per_s else "      n/a"
    extra = f" tool={r.tool_called}" if r.tool_called else ""
    print(f"  [{status}] {r.provider:6} {r.workload:5} total {r.total_s:6.2f}s  ttft {ttft}  {tps}{extra}{tag}"
          + (f"  -> {r.error}" if r.error else ""), flush=True)
    return r


def _pick_local_model(raw_client, requested: str | None) -> str:
    try:
        ids = [m.id for m in raw_client.models.list().data]
    except Exception as e:  # noqa: BLE001
        ids = []
        print(f"  (could not list local models: {type(e).__name__})")
    if ids:
        print("  local models: " + ", ".join(ids))
    if requested:
        return requested
    matches = [i for i in ids if "qwen" in i.lower() and "3.8" in i]
    if not matches:
        sys.exit("No qwen 3.8 model found on the local box - pass --local-model <id>.")
    strata = [i for i in matches if "strata" in i.lower()]
    return (strata or matches)[0]


def _pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def _report(runs: list[Run], workloads: list[str]) -> None:
    print("\n" + "=" * 88)
    print(f"{'workload':8} {'provider':8} {'ok':>5} {'total p50':>10} {'total p90':>10} "
          f"{'ttft p50':>9} {'ttft p90':>9} {'tok/s p50':>10} {'warmup':>8}")
    print("-" * 88)
    for w in workloads:
        for p in ("gemini", "local"):
            timed = [r for r in runs if r.workload == w and r.provider == p and not r.warmup]
            good = [r for r in timed if r.ok and not r.error]
            warm = next((r for r in runs if r.workload == w and r.provider == p and r.warmup), None)
            totals = [r.total_s for r in good]
            ttfts = [r.ttft_s for r in good if r.ttft_s is not None]
            tps = [r.tok_per_s for r in good if r.tok_per_s]
            fmt = lambda v: f"{v:9.2f}s" if v is not None else f"{'-':>10}"  # noqa: E731
            print(f"{w:8} {p:8} {len(good):>2}/{len(timed):<2} "
                  f"{fmt(statistics.median(totals) if totals else None)} {fmt(_pct(totals, .9) if totals else None)} "
                  f"{fmt(statistics.median(ttfts) if ttfts else None)[1:]} {fmt(_pct(ttfts, .9) if ttfts else None)[1:]} "
                  f"{(f'{statistics.median(tps):10.1f}' if tps else f'{'-':>10}')} "
                  f"{(f'{warm.total_s:7.2f}s' if warm else '-'):>8}")
    print("=" * 88)
    print("ttft = first visible text/tool call; tok/s = (output + reasoning tokens) / total time.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env-file", help="Load settings from this .env (applied before backend/.env)")
    ap.add_argument("--gemini-model", default="gemini-3-flash-preview")
    ap.add_argument("--local-model", help="Exact local model id (default: auto-detect qwen 3.8)")
    ap.add_argument("--local-url", help="OpenAI-compatible base URL (default: OPENAI_API_BASE_URL)")
    ap.add_argument("--local-api-key", help="Bearer key for the local box (default: LOCAL_LLM_API_KEY env, then OPENAI_API_KEY)")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--workloads", default="short,long,tool")
    ap.add_argument("--providers", default="gemini,local")
    ap.add_argument("--json", dest="json_out", help="Write all runs to this JSON file")
    args = ap.parse_args()

    workloads = [w.strip() for w in args.workloads.split(",") if w.strip()]
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    all_wl = _workloads()
    unknown = set(workloads) - set(all_wl)
    if unknown:
        sys.exit(f"Unknown workloads: {', '.join(sorted(unknown))}")

    gemini_client = local_raw = None
    local_model = None
    if "gemini" in providers:
        gemini_client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=300_000),
        )
        print(f"Gemini (AI Studio): {args.gemini_model}  free tier pacing: {settings.GEMINI_FREE_TIER}")
    if "local" in providers:
        base_url = args.local_url or settings.OPENAI_API_BASE_URL
        if not base_url:
            sys.exit("No local box URL - pass --local-url or set OPENAI_API_BASE_URL.")
        import openai

        local_raw = openai.OpenAI(base_url=base_url, api_key=args.local_api_key or os.environ.get("LOCAL_LLM_API_KEY") or settings.OPENAI_API_KEY or "not-needed",
                                  timeout=300.0, max_retries=0)
        print(f"Local box: {base_url}")
        local_model = _pick_local_model(local_raw, args.local_model)
        print(f"Local model: {local_model}")

    last_gemini = [0.0]

    def gemini_call(name: str, warmup: bool) -> Run:
        if settings.GEMINI_FREE_TIER:
            wait = GEMINI_FREE_TIER_GAP_SEC - (time.monotonic() - last_gemini[0])
            if wait > 0:
                time.sleep(wait)
        try:
            return run_gemini(gemini_client, args.gemini_model, name, all_wl[name], warmup)
        finally:
            last_gemini[0] = time.monotonic()

    runs: list[Run] = []
    for rnd in range(args.rounds + 1):
        warmup = rnd == 0
        print(f"\n-- {'warmup' if warmup else f'round {rnd}/{args.rounds}'} --", flush=True)
        for name in workloads:
            # Local first so its run overlaps the Gemini free-tier pacing gap.
            if local_raw is not None:
                runs.append(run_local(local_raw, local_model, name, all_wl[name], warmup))
            if gemini_client is not None:
                runs.append(gemini_call(name, warmup))

    _report(runs, workloads)

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"gemini_model": args.gemini_model, "local_model": local_model,
             "runs": [asdict(r) for r in runs]}, indent=2))
        print(f"wrote {args.json_out}")


if __name__ == "__main__":
    main()
