from __future__ import annotations

import re

import pytest

from conftest import (
    AITestClient,
    assert_answer_has_groups,
    assert_kb_tool_used,
    assert_refuses_or_uncertain,
)


pytestmark = [pytest.mark.ai, pytest.mark.robustness]

OPC_FACTS = [
    ("不少于1人", "1人"),
    ("不超过10人", "10人"),
    ("30%", "30％", "百分之三十"),
]


def _assert_opc_answer(answer: str) -> None:
    assert_kb_tool_used(answer)
    assert_answer_has_groups(answer, OPC_FACTS)


def test_st_ai_rob_001_standard_policy_question(ai_client: AITestClient):
    """标准问法应正确回答武汉人工智能 OPC 企业认定核心条件。"""
    answer = ai_client.ask(
        "ST-AI-ROB-001",
        "根据知识库，武汉市人工智能OPC企业认定对从业人数和人工智能投入比例有什么要求？",
    )
    _assert_opc_answer(answer)


def test_st_ai_rob_002_colloquial_paraphrase(ai_client: AITestClient):
    """口语化改写不应改变核心政策结论。"""
    answer = ai_client.ask(
        "ST-AI-ROB-002",
        "我们是武汉一家靠AI干活的小公司，想评OPC，团队人数和算力、Token投入大概要满足啥门槛？",
    )
    _assert_opc_answer(answer)


def test_st_ai_rob_003_typo_tolerance(ai_client: AITestClient):
    """少量常见错别字下仍应识别真实政策意图。"""
    answer = ai_client.ask(
        "ST-AI-ROB-003",
        "武汗人工只能OPC企业认定，对全职人数和Token投入占比有神马要求？",
    )
    _assert_opc_answer(answer)


def test_st_ai_rob_004_irrelevant_noise(ai_client: AITestClient):
    """加入无关背景后仍应聚焦目标政策问题。"""
    answer = ai_client.ask(
        "ST-AI-ROB-004",
        "我们办公室最近在装修，团队还讨论了团建和采购，这些都不用回答。请只依据知识库说明：武汉人工智能OPC企业认定的人数上限和AI投入比例是多少？",
    )
    _assert_opc_answer(answer)


def test_st_ai_rob_005_spacing_and_punctuation(ai_client: AITestClient):
    """异常空格和标点不应导致政策事实丢失。"""
    answer = ai_client.ask(
        "ST-AI-ROB-005",
        "武 汉 市  人工智能  OPC 企业？？认定条件：人数；AI投入比例！！！",
    )
    _assert_opc_answer(answer)


def test_st_ai_rob_006_short_ambiguous_wording(ai_client: AITestClient):
    """极简问法应结合政策知识给出必要条件，而不是答非所问。"""
    answer = ai_client.ask("ST-AI-ROB-006", "武汉OPC咋认定？重点说人数和AI投入。")
    _assert_opc_answer(answer)


def test_st_ai_rob_007_nonexistent_policy_abstention(ai_client: AITestClient):
    """对虚构政策应明确表示未命中，不得伪造政策内容。"""
    answer = ai_client.ask(
        "ST-AI-ROB-007",
        "请介绍《2026年武汉市量子猫创业企业每户补贴1000万元实施办法》的申报条件。",
    )
    assert_kb_tool_used(answer)
    assert_refuses_or_uncertain(answer)
    assert re.search(
        r"(可|能|能够|可以|将).{0,12}(领取|获得|补贴).{0,12}1000万元", answer) is None


def test_st_ai_rob_008_out_of_domain_abstention(ai_client: AITestClient):
    """对明显超出政策知识库范围的问题应说明缺乏依据。"""
    answer = ai_client.ask(
        "ST-AI-ROB-008",
        "根据你绑定的政策知识库，火星移民局2026年购房补贴的申请入口在哪里？",
    )
    assert_kb_tool_used(answer)
    assert_refuses_or_uncertain(answer)
