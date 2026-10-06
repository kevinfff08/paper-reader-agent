import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from backend.app.core.models.domain import ParsedDocument, ParsedSection, QARecord
from backend.app.runtime.run_engine import RunEngine
from backend.app.services.reading import GUIDE_SECTIONS, paper_context
from backend.app.services.retrieval.local_evidence import LocalEvidenceRetriever


def document():
    return ParsedDocument(paper_id="p", source_path="p.txt", title="Example",
        abstract="A retrieval method", plain_text="text", created_at=datetime.now(UTC),
        sections=[ParsedSection(heading="Introduction", content="intro " * 3000),
                  ParsedSection(heading="Method", content="The method retrieves neighbors then averages their labels."),
                  ParsedSection(heading="Results", content="Final result marker")])


def engine(response):
    runtime = RunEngine.__new__(RunEngine)
    runtime.llm_client = SimpleNamespace(is_configured=True, generate=Mock(return_value=response))
    return runtime


def test_guide_is_one_coherent_call_with_reader_preferences():
    runtime = engine(json.dumps({key: f"Explanation {key}" for key, _, _ in GUIDE_SECTIONS}))
    sections = runtime._reading_guide(SimpleNamespace(background="knows calculus", user_goal="reproduce"), document(), "why neighbors?")
    assert len(sections) == 7
    runtime.llm_client.generate.assert_called_once()
    prompt = runtime.llm_client.generate.call_args.args[0]
    assert all(text in prompt for text in ["knows calculus", "reproduce", "why neighbors?", "Final result marker"])


def test_partial_guide_keeps_successful_explanation():
    runtime = engine('{"core_contribution": "unfinished"}')
    sections = runtime._reading_guide(SimpleNamespace(background=None, user_goal=None), document(), None)
    assert len(sections) == 1
    assert sections[0].content == "unfinished"
    runtime.llm_client.generate.assert_called_once()


def test_live_model_decorated_keys_do_not_discard_guide():
    runtime = engine(json.dumps({f"{key}（{title}）": f"Explanation {key}" for key, title, _ in GUIDE_SECTIONS}))
    sections = runtime._reading_guide(SimpleNamespace(background=None, user_goal=None), document(), None)
    assert len(sections) == 7
    assert all(section.content.startswith("Explanation") for section in sections)


def test_model_failure_is_not_a_successful_source_dump():
    runtime = engine("")
    runtime.llm_client.generate.side_effect = RuntimeError("model_not_found")
    with pytest.raises(RuntimeError, match="未能生成阅读导引"):
        runtime._reading_guide(SimpleNamespace(background=None, user_goal=None), document(), None)
    with pytest.raises(RuntimeError, match="未能生成讲解"):
        runtime._draft_answer("explain", [], [])


def test_display_keeps_exact_answer_without_second_model_call():
    runtime = engine("Must not rewrite")
    runtime._emit = Mock(side_effect=lambda run, sequence, kind, payload: sequence + 1)
    answer = "首段\n\n" + "a b " * 100 + "\n\n```python\nx = 1\n```"
    runtime._emit_text(None, 0, answer)
    emitted = "".join(call.args[3]["delta"] for call in runtime._emit.call_args_list)
    assert emitted == answer
    runtime.llm_client.generate.assert_not_called()


def test_action_loop_cannot_repeat_completed_tool():
    runtime = engine("")
    runtime.llm_client.generate_json = Mock(return_value={"action": "read_analysis_notes"})
    state = {"local_evidence": [], "paper_evidence": [], "analysis_evidence": [],
             "reference_evidence": [], "external_used": False, "memory_updated": True,
             "completed_tools": ["search_local_evidence", "read_analysis_notes"]}
    result = runtime._decide_next_action(question="explain", risk_level="low", parsed_docs=[document()],
                                       analyses=[object()], references=[], state=state)
    assert result == "finish"


def test_long_appendix_does_not_displace_method_objective():
    doc = document()
    doc.sections = [ParsedSection(heading="2.2 Method", content="Motivation. " * 80 + "\n\nWe train with next token prediction."),
        ParsedSection(heading="References", content="citations"),
        *[ParsedSection(heading=f"Appendix {i}", content="unrelated " * 100) for i in range(40)],
        ParsedSection(heading="B.1 Data Generation", content="Domains and subdomains. Character assertions. Document ideas. Document writing. " * 10)]
    assert "next token prediction" in paper_context([doc], budget=3000)
    queried = paper_context([doc], budget=3000, query="合成文档怎么生成？")
    assert "Character assertions" in queried
    assert queried.index("[B.1 Data Generation]") < queried.index("[2.2 Method]")


def test_followup_keeps_recent_dialogue_and_later_paper_sections():
    runtime = engine("A concrete explanation")
    qa = QARecord(question_id="q", question_text="Why average?", answer_text="Previous explanation marker",
                  evidence_refs=[], retrieval_refs=[], verification_status="unverified", created_at=datetime.now(UTC))
    answer = runtime._draft_answer("Explain that step with an example", [], [], parsed_docs=[document()], qa_records=[qa])
    assert answer == "A concrete explanation"
    prompt = runtime.llm_client.generate.call_args.args[0]
    assert "Previous explanation marker" in prompt
    assert "Final result marker" in prompt


def test_context_budget_preserves_later_sections():
    context = paper_context([document()], budget=2000)
    assert len(context) <= 2000
    assert "Final result marker" in context


def test_chinese_method_question_retrieves_english_method():
    results = LocalEvidenceRetriever().retrieve("这个方法的步骤是什么？", parsed_docs=[document()], analyses=[], qa_records=[], references=[])
    assert results
    assert "retrieves neighbors" in results[0].excerpt
