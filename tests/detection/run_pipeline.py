"""Field detection on real documents, end to end, with every step written to a file (LLD topic 7).

    apps/api/.venv/bin/python tests/detection/run_pipeline.py <file.pdf|.docx> [options]
    apps/api/.venv/bin/python tests/detection/run_pipeline.py            # every new document

Runs the product's own detection (``signora.modules.detection``: read, ask with its repair round,
derive) with the real AI from ``.env``, so what it measures is what users get. A Word file is
converted by Gotenberg first, as in the product. Output: ``tests/outputs/<document>/`` (README).
"""

# ruff: noqa: E501 - Markdown table rows read best on one line
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import pymupdf

from signora.kernel.config import load_settings
from signora.modules.detection.ai import OpenAIAssigner
from signora.modules.detection.derive import Result, derive
from signora.modules.detection.prompt import SYSTEM_PROMPT, user_message
from signora.modules.detection.read import read_document
from signora.modules.detection.run import ask
from signora.modules.detection.schema import answer_model
from signora.modules.documents.conversion import docx_to_pdf

TESTS = Path(__file__).resolve().parents[1]
DOCUMENTS = TESTS / "fixtures" / "documents"
OUTPUTS = TESTS / "outputs"


def _write(path: Path, data: Any) -> None:
    text = data if isinstance(data, str) else json.dumps(data, indent=2, ensure_ascii=False)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def report(
    name: str,
    result: Result,
    calls: list[dict[str, Any]],
    instructions: str,
    effort: str,
    read_ms: float,
) -> str:
    total = lambda key: sum(call[key] for call in calls)  # noqa: E731
    who = {role.slug: role.label for role in result.roles}
    lines = [
        f"# {name}: field detection",
        "",
        f"**{(result.document.name if result.document else None) or '(no name written)'}**: "
        f"{(result.document.description if result.document else None) or ''}",
        "",
        f"Uploader instructions: {instructions or '(none)'} · fields from: {result.fields_from}",
        "",
        "## Calls",
        "",
        "| | |",
        "|---|---|",
        f"| model, effort | `{calls[0]['model'] if calls else '—'}`, {effort} |",
        f"| read stage | {read_ms:.0f} ms |",
        f"| AI latency | **{sum(c['latency_s'] for c in calls):.1f} s** over {len(calls)} call(s) |",
        f"| input tokens | {total('input_tokens') if calls else 0} (cached {total('cached_tokens') if calls else 0}) |",
        f"| output tokens | {total('output_tokens') if calls else 0} (reasoning {total('reasoning_tokens') if calls else 0}) |",
        *[f"| problems sent back | {'<br>'.join(c['problems'])} |" for c in calls[:-1]],
        f"| problems left | {'<br>'.join(calls[-1]['problems']) if calls and calls[-1]['problems'] else 'none'} |",
        f"| flags | {', '.join(k for k, v in result.flags.model_dump().items() if v) or 'none'} |",
        "",
        "## Roles (signing order)",
        "",
        *([f"{r.position}. {r.label} (`{r.slug}`), {r.kind}" for r in result.roles] or ["none"]),
        "",
        "## Fields (one per key)",
        "",
        "| key | label | holds | filled by | req | depends on | places | ids | needs review |",
        "|---|---|---|---|---|---|---|---|---|",
        *[
            f"| `{f.key}` | {f.label} | {f.holds} | {who.get(f.role or '', f.filled_by)} | "
            f"{'yes' if f.required else 'no'} | "
            f"{f'{f.depends_on.key} = {f.depends_on.option} ({f.depends_on.source})' if f.depends_on else '—'} | "
            f"{len(f.placements)} | {', '.join(f.ids) or 'extra'} | {f.needs_review or ''} |"
            for f in result.fields
        ],
        "",
        "## Not asked",
        "",
        *(
            [
                f"- {n.id} {n.pdf_field or ''} ({n.kind}): {'; '.join(n.why)}"
                for n in result.not_asked
            ]
            or ["none"]
        ),
        "",
        "## Notes",
        "",
        *([f"- {note}" for note in result.notes] or ["none"]),
        "",
    ]
    return "\n".join(lines)


def run(source: Path, *, instructions: str, effort: str | None, out: Path) -> Path:
    settings = load_settings()
    if settings.ai.api_key is None:
        raise SystemExit("AI_API_KEY is not set")
    ai = settings.ai.model_copy(update={"reasoning_effort": effort}) if effort else settings.ai
    out.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    if source.suffix.lower() == ".docx":
        data = docx_to_pdf(settings.gotenberg.base_url, data)
        (out / "00-converted.pdf").write_bytes(data)
    started = time.perf_counter()
    reading = read_document(data)
    read_ms = 1000 * (time.perf_counter() - started)
    _write(out / "01-reading.json", reading.model_dump(mode="json"))
    _write(out / "02-layout.txt", reading.layout)
    _write(
        out / "03-request.json",
        {
            "model": ai.model,
            "reasoning_effort": ai.reasoning_effort,
            "system": SYSTEM_PROMPT,
            "user": user_message(reading, current_name=source.stem, instructions=instructions),
            "answer_schema": answer_model([field.id for field in reading.asked]).model_json_schema()
            if reading.asked
            else None,
        },
    )
    with pymupdf.open(stream=data, filetype="pdf") as document:
        calls, answer, _ = ask(
            reading,
            document,
            OpenAIAssigner(ai),
            current_name=source.stem,
            instructions=instructions,
        )
        result = derive(
            reading,
            answer,
            document,
            problems=calls[-1]["problems"] if calls else [],
            repaired=len(calls) > 1,
        )
    _write(out / "04-calls.json", calls)
    _write(out / "05-answer.json", answer)
    _write(out / "result.json", result.model_dump(mode="json"))
    _write(
        out / "report.md",
        report(source.name, result, calls, instructions, ai.reasoning_effort, read_ms),
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--instructions", default="")
    parser.add_argument(
        "--effort", choices=["low", "medium", "high"], help="override AI_REASONING_EFFORT"
    )
    parser.add_argument("--variant", help="write to outputs/<document>/variants/<name>/")
    parser.add_argument("--force", action="store_true", help="run again even if the output exists")
    args = parser.parse_args()
    files = args.files or [
        p
        for p in sorted(DOCUMENTS.iterdir())
        if p.suffix.lower() in (".pdf", ".docx") and (args.force or not (OUTPUTS / p.name).exists())
    ]
    if not files:
        print("nothing new to run (use --force to run again)")  # noqa: T201 - a command-line tool
    for source in files:
        # One folder per file (a document may be here as both .pdf and .docx).
        out = (
            OUTPUTS / source.name / "variants" / args.variant
            if args.variant
            else OUTPUTS / source.name
        )
        print(run(source, instructions=args.instructions, effort=args.effort, out=out))  # noqa: T201


if __name__ == "__main__":
    main()
