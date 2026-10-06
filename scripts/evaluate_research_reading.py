"""Opt-in, real-model multi-paper evaluation; HTML import isolates reading from PDF parsing.

Run in research_tools. Outputs, source HTML, prompts and failures stay in .tmp-tests.
BeautifulSoup is required for the evaluation import (not the production parser).
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.models.domain import ParsedDocument, ParsedSection
from backend.app.llm.client import LLMClient
from backend.app.services.reading import paper_context

PAPERS = {
    "dpo": ("2305.18290v3", "Direct Preference Optimization: Your Language Model is Secretly a Reward Model"),
    "ipo": ("2310.12036v2", "A General Theoretical Paradigm to Understand Learning from Human Preferences"),
    "lost_middle": ("2307.03172v3", "Lost in the Middle: How Language Models Use Long Contexts"),
    "lora": ("2106.09685v2", "LoRA: Low-Rank Adaptation of Large Language Models"),
}


def import_html(key: str, version: str, title: str, cache: Path) -> ParsedDocument:
    """Normalize official arXiv HTML without claiming to test Docling PDF parsing."""
    import httpx
    from bs4 import BeautifulSoup

    path = cache / f"{key}.html"
    url = f"https://arxiv.org/html/{version}"
    if not path.exists():
        response = httpx.get(url, timeout=60, follow_redirects=True, trust_env=False)
        response.raise_for_status()
        path.write_text(response.text, encoding="utf-8")
    raw = path.read_text(encoding="utf-8")
    soup = BeautifulSoup(raw, "html.parser")
    for math in soup.select("math"):
        math.replace_with(" $" + (math.get("alttext") or math.get_text(" ", strip=True)) + "$ ")
    abstract = soup.select_one(".ltx_abstract")
    sections = []
    for section in soup.select("section.ltx_section, section.ltx_subsection, section.ltx_subsubsection"):
        heading = section.find(["h2", "h3", "h4", "h5"], recursive=False)
        if heading is None:
            continue
        # Direct children preserve paragraphs/equations/tables without duplicating child sections.
        content = "\n\n".join(child.get_text(" ", strip=True) for child in section.children
            if getattr(child, "name", None) and child is not heading and child.name != "section")
        sections.append(ParsedSection(heading=heading.get_text(" ", strip=True), content=content))
    if not sections or not abstract:
        raise ValueError(f"Incomplete HTML import: {key}")
    return ParsedDocument(paper_id=key, source_path=str(path), title=title,
        abstract=abstract.get_text(" ", strip=True), sections=sections,
        plain_text="\n\n".join(section.heading + "\n" + section.content for section in sections),
        created_at=datetime.now(UTC), metadata={"evaluation_import": "official arXiv HTML; PDF parser bypassed",
        "source_url": url, "source_sha256": hashlib.sha256(raw.encode()).hexdigest()})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--papers", nargs="+", choices=list(PAPERS), default=["dpo", "ipo", "lost_middle"])
    parser.add_argument("--compare", action="store_true", help="Also call production cross-paper synthesis")
    parser.add_argument("--reuse-guides", type=Path, help="Use saved sections when testing synthesis only")
    args = parser.parse_args()
    if not args.label.replace("-", "").replace("_", "").isalnum():
        parser.error("Label must contain only letters, digits, hyphens or underscores")
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")
    output = ROOT / ".tmp-tests" / "research-reading" / args.label
    output.mkdir(parents=True, exist_ok=False)
    cache = ROOT / ".tmp-tests" / "research-corpus"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["PAPERREADER_TEST_MODE"] = "1"
    os.environ["SESSION_DATA_ROOT"] = str(output / "sessions")
    # Import after test isolation is established: main creates a module-level app.
    from backend.app.main import create_app
    from backend.app.core.models.domain import AnalysisArtifact, AnalysisSection
    app = create_app()
    engine, store, settings = app.state.run_engine, app.state.store, app.state.settings

    class RecordedLLM(LLMClient):
        def generate(self, prompt: str, **kwargs) -> str:
            started = time.perf_counter()
            record = {"prompt": prompt, "system": kwargs.get("system", "")}
            try:
                result = super().generate(prompt, **kwargs)
                record["response"] = result
                return result
            except Exception as exc:
                record["error_type"] = type(exc).__name__
                raise
            finally:
                record["seconds"] = round(time.perf_counter() - started, 2)
                with (output / "model_calls.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(f"Call {record['seconds']}s, {len(record.get('response', ''))} chars", flush=True)

    client = RecordedLLM(provider=settings.llm_provider, mode=settings.llm_mode,
        api_key=settings.openai_api_key if settings.llm_provider == "openai" else settings.claude_api_key,
        model=settings.llm_model, base_url=settings.llm_proxy_url)
    if not client.is_configured:
        raise RuntimeError("A real model must be configured")
    engine.llm_client = client
    session = store.create_session(session_name=args.label, categories=[], external_links=[],
        background="机器学习方向博士生，熟悉概率、优化和深度学习，但尚未读过这些论文",
        user_goal="理解研究问题、核心思想和论证，判断相对已有工作的贡献，并形成值得进一步研究的问题")
    docs, analyses, runs = [], [], []
    metadata = {"model": client.resolved_model, "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "scope": "production reading/synthesis functions; official HTML import; no PDF parsing or UI test",
        "papers": [], "runs": runs}
    print(f"Output: {output}", flush=True)
    for key in args.papers:
        doc = import_html(key, *PAPERS[key], cache)
        docs.append(doc)
        metadata["papers"].append({"key": key, **doc.metadata})
        (output / f"{key}-context.txt").write_text(paper_context([doc]), encoding="utf-8")
        started = time.perf_counter()
        print(f"Reading {key}: {len(doc.sections)} sections, {len(doc.plain_text)} chars", flush=True)
        try:
            if args.reuse_guides:
                saved = json.loads((args.reuse_guides / f"{key}-sections.json").read_text(encoding="utf-8"))
                artifact = AnalysisArtifact(analysis_id=key, session_id=session.session_id, paper_ids=[key], title=doc.title,
                    sections=[AnalysisSection.model_validate(item) for item in saved], markdown_path="", created_at=datetime.now(UTC))
            else:
                artifact = engine._analyze_paper(session, doc, None)
            analyses.append(artifact)
            (output / f"{key}.md").write_text(engine._analysis_markdown(doc.title, artifact.sections), encoding="utf-8")
            (output / f"{key}-sections.json").write_text(json.dumps([s.model_dump() for s in artifact.sections], ensure_ascii=False, indent=2), encoding="utf-8")
            runs.append({"paper": key, "status": "completed", "seconds": round(time.perf_counter()-started, 2)})
        except Exception as exc:
            runs.append({"paper": key, "status": "failed", "error_type": type(exc).__name__})
        (output / "trial.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.compare and len(analyses) == len(docs):
        synthesis = engine._build_cross_paper_synthesis(session, docs, analyses,
            "这些论文在研究问题、核心假设和论证上是什么关系？哪些结论可以直接比较？给出一个有根据的后续研究问题。")
        (output / "comparison.md").write_text(engine._analysis_markdown("Comparison", synthesis.sections), encoding="utf-8")
    if any(run["status"] == "failed" for run in runs):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
