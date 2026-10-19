import json

import pytest

from app.services.analyzer import parse_analysis, to_llm_analysis
from app.services.errors import PipelineError

PAYLOAD = {
    "paper_essence": "提出动态 KV Cache 剪枝",
    "concept_bridging": {
        "source_concept": "KV Cache",
        "target_concept": "DiT 时间步缓存",
        "mechanism_transfer": "按注意力头重要性裁剪",
    },
    "visual_verification": "Figure 3 支持其加速结论",
    "relevance_score": 8,
    "relevance_reason": "迁移路径清晰",
    "heuristic_suggestion": "1. 在前 50% 去噪步应用",
}


def test_bare_json():
    result = parse_analysis(json.dumps(PAYLOAD, ensure_ascii=False))
    assert result.paper_essence == "提出动态 KV Cache 剪枝"
    assert result.concept_bridging.target_concept == "DiT 时间步缓存"
    assert result.relevance_score == 8.0


def test_fenced_json_with_prose():
    answer = "好的，分析如下：\n```json\n" + json.dumps(PAYLOAD) + "\n```\n以上。"
    assert parse_analysis(answer).relevance_reason == "迁移路径清晰"


def test_json_embedded_in_text_without_fence():
    answer = "结果：" + json.dumps(PAYLOAD) + " 完"
    assert parse_analysis(answer).visual_verification.startswith("Figure 3")


def test_think_prefix_is_split_into_thought():
    answer = "<think>先看摘要</think>" + json.dumps(PAYLOAD)
    result = parse_analysis(answer)
    assert result.thought_process == "先看摘要"
    assert result.paper_essence


def test_only_closing_think_tag():
    answer = "推理过程……</think>\n" + json.dumps(PAYLOAD)
    result = parse_analysis(answer)
    assert result.thought_process == "推理过程……"


@pytest.mark.parametrize("raw, expected", [("8.5", 8.5), ("8/10", 8.0), ("评分：9", 9.0), (15, 10.0), (-1, 0.0)])
def test_score_coercion(raw, expected):
    assert parse_analysis(json.dumps({**PAYLOAD, "relevance_score": raw})).relevance_score == expected


def test_list_and_string_fields_are_flattened():
    data = {**PAYLOAD, "heuristic_suggestion": ["1. A", "2. B"], "concept_bridging": "直接迁移"}
    result = parse_analysis(json.dumps(data))
    assert result.heuristic_suggestion == "1. A\n2. B"
    assert result.concept_bridging.mechanism_transfer == "直接迁移"


@pytest.mark.parametrize("answer", ["", "not json at all", "[1, 2, 3]", '{"unrelated": 1}'])
def test_garbage_raises_llm_error(answer):
    with pytest.raises(PipelineError) as info:
        parse_analysis(answer)
    assert info.value.code == "llm_error"


def test_to_llm_analysis_flattens_concept_bridging():
    analysis = to_llm_analysis(parse_analysis(json.dumps(PAYLOAD)))
    assert analysis.concept_bridging_str == (
        "源概念: KV Cache\n目标概念: DiT 时间步缓存\n迁移机制: 按注意力头重要性裁剪"
    )
