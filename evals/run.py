"""Run an eval suite from the command line (from the repo root).

    python evals/run.py whatsapp                 real model (LLM_MODEL), score printed and saved
    python evals/run.py invoices --record        real model, and write the tape CI replays
    python evals/run.py all --replay             no model: play the tapes back (what CI does)

    LLM_MODEL=ollama_chat/qwen2.5:14b python evals/run.py all --record

Real runs save evals/results/<suite>_<model>.json: the numbers quoted in the README come from
these files. `--record` also writes evals/recordings/<suite>.json (see evals/tape.py). If
Langfuse keys are set, real runs are traced there too.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evals import invoices, whatsapp  # noqa: E402
from evals.common import RECORDINGS, RESULTS, CountingAsk, Report  # noqa: E402
from evals.tape import RecordingCompletion, ReplayCompletion, Tape  # noqa: E402

SUITES: dict[str, ModuleType] = {whatsapp.SUITE: whatsapp, invoices.SUITE: invoices}


async def run_suite(name: str, mode: str) -> Report:
    import litellm

    from app.config import get_settings
    from app.llm.tracing import setup_tracing

    suite, model = SUITES[name], get_settings().llm_model
    tape_path = RECORDINGS / f"{name}.json"
    if mode == "replay":
        replay = ReplayCompletion(Tape.load(tape_path))
        report = await suite.run(CountingAsk(replay))
        if replay.misses:
            sys.exit(
                f"{name}: the tape is out of date, record it again:\n  "
                + "\n  ".join(replay.misses)
            )
        return report

    setup_tracing()
    tape = Tape(
        path=tape_path, model=model, recorded_at=datetime.now().isoformat(timespec="seconds")
    )
    completion = RecordingCompletion(litellm.acompletion, tape)
    print(f"{name}: running with {model} ...", flush=True)
    started = time.perf_counter()
    report = await suite.run(CountingAsk(completion))
    seconds = round(time.perf_counter() - started)
    save_result(name, model, seconds, report)
    if mode == "record":
        tape.expected_summary = report.summary
        tape.save()
        print(
            f"{name}: tape written to {tape_path.relative_to(ROOT)} ({len(tape.entries)} answers)"
        )
    return report


def save_result(name: str, model: str, seconds: int, report: Report) -> None:
    summary = {
        "model": model,
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": seconds,
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{name}_{model.split('/')[-1].replace(':', '-')}.json"
    out.write_text(
        json.dumps({"summary": {**summary, **report.summary}, "details": report.details}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"{name}: result saved to {out.relative_to(ROOT)}")


async def main() -> None:
    from app.llm.tracing import flush_tracing

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("suite", choices=[*SUITES, "all"])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="real model, and write the tape")
    mode.add_argument("--replay", action="store_true", help="no model: play the tape back")
    args = parser.parse_args()
    chosen = "record" if args.record else "replay" if args.replay else "live"
    for name in SUITES if args.suite == "all" else [args.suite]:
        report = await run_suite(name, chosen)
        print(json.dumps(report.summary, indent=2), flush=True)
    if chosen != "replay":
        await flush_tracing()  # send the last traces before the script ends


if __name__ == "__main__":
    asyncio.run(main())
