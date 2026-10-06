"""Opt-in real-model reading trial; stores inputs and outputs in .tmp-tests only.

Run from the repository root in research_tools. This calls the configured model.
Uses an existing parsed PDF to isolate reading quality from parser performance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.models.domain import ParsedDocument
from backend.app.llm.client import LLMClient
from backend.app.main import create_app


QUESTIONS = [
    "请用一个具体的小例子解释这篇论文的方法：训练分几个阶段，每一步输入什么、学会什么？我熟悉普通 SFT，但不熟悉 midtraining。",
    "我还是没懂：为什么同样的奶酪偏好训练，最后会得到不同价值观？请沿用刚才的例子解释，不要重新总结整篇论文。",
    "如果我想复现 MSM，合成训练文档具体怎么生成？请解释生成步骤、文档形式和训练目标，并区分 midtraining 与后面的 alignment fine-tuning。",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--model", help="Explicit trial-only model override; leaves .env unchanged")
    parser.add_argument("--resume", type=Path, help="Resume failed questions in an existing isolated trial")
    parser.add_argument("--questions", type=int, choices=range(4), default=3)
    parser.add_argument("--recorded-parser-settings", action="store_true",
        help="Use the source cache's recorded parser settings for a controlled reading-only comparison")
    args = parser.parse_args()
    # Same .env settings as the desktop launcher, without printing credentials.
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")
    output = ROOT / ".tmp-tests" / "reading-live" / f"{args.label}-{time.strftime('%Y%m%d-%H%M%S')}"
    if args.resume:
        output = args.resume.resolve()
        if not output.is_relative_to((ROOT / ".tmp-tests" / "reading-live").resolve()):
            raise ValueError("Resume must stay under .tmp-tests/reading-live")
    else:
        output.mkdir(parents=True)
    os.environ["PAPERREADER_TEST_MODE"] = "1"
    os.environ["SESSION_DATA_ROOT"] = str(output / "sessions")
    app = create_app()
    engine, store = app.state.run_engine, app.state.store
    settings = app.state.settings
    if args.model:
        settings.llm_model = args.model
    lock = threading.Lock()

    class RecordedLLM(LLMClient):
        def generate(self, prompt: str, **kwargs) -> str:
            started = time.perf_counter()
            record = {"prompt": prompt, "system": kwargs.get("system", ""), "max_tokens": kwargs.get("max_tokens")}
            try:
                result = super().generate(prompt, **kwargs)
                record["response"] = result
                return result
            except Exception as exc:
                record["error_type"] = type(exc).__name__
                raise
            finally:
                record["seconds"] = round(time.perf_counter() - started, 2)
                with lock:
                    with (output / "model_calls.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"Model call: {record['seconds']}s; response chars={len(record.get('response', ''))}", flush=True)

    client = RecordedLLM(provider=settings.llm_provider, mode=settings.llm_mode,
        api_key=settings.openai_api_key if settings.llm_provider == "openai" else settings.claude_api_key,
        model=settings.llm_model, base_url=settings.llm_proxy_url)
    if not client.is_configured:
        raise RuntimeError("Real model must be configured for this trial")
    engine.llm_client = client
    engine.task_engine.llm_client = client
    if args.resume:
        metadata = json.loads((output / "trial.json").read_text(encoding="utf-8"))
        if metadata["model"] != client.resolved_model:
            raise ValueError("A resumed comparison must use the same model")
        session = store.get_session(metadata["session_id"])
        doc = store.load_parsed_documents(session.session_id)[0]
    else:
        session = store.create_session(session_name=f"Reading trial {args.label}", categories=[],
            user_goal="快速理解论文核心想法，能向同学解释，并了解如何复现方法",
            background="熟悉机器学习和普通 SFT，不熟悉 model spec midtraining", external_links=[])
        doc = ParsedDocument.model_validate_json(args.source.read_text(encoding="utf-8"))
        source_pdf = Path(doc.source_path)
        if args.recorded_parser_settings:
            recorded = json.loads(doc.metadata["parser_config"])
            for key, value in recorded.items():
                if hasattr(engine.parser, key) and not callable(getattr(engine.parser, key)):
                    current = getattr(engine.parser, key)
                    setattr(engine.parser, key, value == "True" if isinstance(current, bool) else type(current)(value))
        cache_valid = engine.parser.is_cache_valid(doc, source_pdf)
        paper = store.save_uploaded_paper(session.session_id, filename=source_pdf.name,
            media_type="application/pdf", content=source_pdf.read_bytes())
        if cache_valid:
            doc = doc.model_copy(deep=True)
            doc.paper_id, doc.source_path = paper.paper_id, paper.original_path
            doc.metadata["cache_fingerprint"] = engine.parser.build_cache_fingerprint(Path(paper.original_path), backend="docling")
        else:
            print("Parsing PDF with current settings in isolated session", flush=True)
            doc = engine.parser.parse(paper.paper_id, Path(paper.original_path), parsed_dir=store.session_dir(session.session_id) / "parsed")
        store.save_parsed_document(session.session_id, doc)
        metadata = {"model": client.resolved_model, "source": str(args.source), "title": doc.title,
            "parser": "existing valid cache" if cache_valid else "fresh Docling parse", "session_id": session.session_id, "runs": []}
    print(f"Output: {output}\nModel: {client.resolved_model}\nPaper: {doc.title}", flush=True)
    for index, (mode, question) in enumerate([("analyze", ""), *[("answer", q) for q in QUESTIONS[:args.questions]]]):
        completed = {run.get("question_index", i) for i, run in enumerate(metadata["runs"]) if run["status"] == "completed"}
        if index in completed:
            continue
        started = time.perf_counter()
        print(f"Starting {mode} {index}", flush=True)
        run = engine.run_sync(session.session_id, mode=mode, input_text=question)
        elapsed = round(time.perf_counter() - started, 2)
        metadata["runs"].append({"question_index": index, "mode": mode, "question": question, "seconds": elapsed,
            "status": run.status, "error": run.error_message, "run_id": run.run_id})
        if mode == "analyze" and store.list_analyses(session.session_id):
            artifact = store.list_analyses(session.session_id)[-1]
            text = Path(artifact.markdown_path).read_text(encoding="utf-8")
        elif mode == "answer" and run.status == "completed":
            text = store.list_qa_records(session.session_id)[-1].answer_text
        else:
            text = f"Run {run.status}: {run.error_message}"
        (output / f"{index:02d}-{mode}.md").write_text(text, encoding="utf-8")
        events_path = store.session_dir(session.session_id) / "runs" / f"{run.run_id}.events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        display = "".join(event["payload"].get("delta", "") for event in events if event["event_type"] == "assistant_delta")
        (output / f"{index:02d}-{mode}-display.md").write_text(display, encoding="utf-8")
        (output / "trial.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Finished {mode} {index}: {run.status}, {elapsed}s, {len(text)} chars", flush=True)
        if run.status != "completed":
            break
    for task in store.list_tasks(session.session_id):
        engine.task_engine.wait_for_task(session.session_id, task.task_id, timeout_seconds=60)
    print("Trial complete", flush=True)
    latest = {run.get("question_index", i): run["status"] for i, run in enumerate(metadata["runs"])}
    if any(status != "completed" for status in latest.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
