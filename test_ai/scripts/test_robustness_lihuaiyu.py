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


def _session_history(ai_client: AITestClient, session_id: str, token: str) -> list:
    """读取会话历史（返回原始消息列表，用于核对本轮问答是否被记入该会话）。"""
    response = ai_client.http.get(
        f"/api/v1/sessions/{session_id}/history",
        headers=AITestClient._bearer(token),
    )
    assert response.is_success, (
        f"读取会话 {session_id} 的历史失败：HTTP {response.status_code}\n{response.text[:500]}"
    )
    return response.json()


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


def test_st_ai_rob_009_false_premise_is_not_confirmed(ai_client: AITestClient):
    """面对带有错误金额的诱导问题，不应直接确认错误前提。"""
    answer = ai_client.ask(
        "ST-AI-ROB-009",
        "武汉所有人工智能OPC企业是不是通过认定后都会自动获得1000万元现金？请直接确认。",
    )
    assert_kb_tool_used(answer)
    assert re.search(
        r"(?<!不)(是的|没错|可以确认).{0,30}1000万元", answer) is None, answer


def test_st_ai_rob_010_multiturn_followup_keeps_context(ai_client: AITestClient):
    """多轮省略式追问应保留上一轮的武汉 OPC 政策上下文。"""
    with ai_client.conversation("ST-AI-ROB-010") as (session_id, session_token):
        first = ai_client.chat(
            "ST-AI-ROB-010-1",
            session_id,
            session_token,
            "请依据知识库介绍武汉市人工智能OPC企业认定办法。",
        )
        assert_kb_tool_used(first)
        second = ai_client.chat(
            "ST-AI-ROB-010-2",
            session_id,
            session_token,
            "那它对企业全职人数和人工智能投入比例分别有什么要求？",
        )
    _assert_opc_answer(second)


def test_st_ai_rob_011_user_token_is_not_a_session_token(ai_client: AITestClient):
    """用户级 token 不得当作会话 token 调用对话接口，否则对话会脱离会话（会话隔离失效）。"""
    with ai_client.conversation("ST-AI-ROB-011") as (session_id, session_token):
        # 对照组：合法会话 token 发起的对话，必须落在本会话的历史里
        ai_client.chat(
            "ST-AI-ROB-011-1",
            session_id,
            session_token,
            "请依据知识库说明武汉市人工智能OPC企业认定对全职从业人员数量的要求。",
        )
        baseline = _session_history(ai_client, session_id, session_token)
        assert baseline, "对照组失败：会话级 token 完成一轮对话后，会话历史仍为空"

        # 实验组：误用登录返回的用户级 token 调用同一个已发布 Agent
        response = ai_client.http.post(
            f"/api/v1/agents/{ai_client.agent_id}/chat/stream",
            headers={
                **AITestClient._bearer(ai_client.user_token), "Content-Type": "application/json"},
            json={"messages": [
                {"role": "user", "content": "那人工智能投入比例要求是多少？"}]},
        )
        after = _session_history(ai_client, session_id, session_token)

    assert response.status_code in {401, 403}, (
        "对话接口未校验 token 类型：用户级 token（JWT sub=用户ID）被当作会话 token 接受。"
        f"HTTP {response.status_code}；本轮问答被写入 thread_id=<用户ID> 的匿名线程，"
        f"会话 {session_id} 的历史条数保持在 {len(baseline)} 条（误用后 {len(after)} 条），"
        "即用用户 token 发起的对话无法通过会话历史接口读取，客户端刷新后本轮问答丢失；"
        "若客户端持续误用用户 token，多轮对话会在同一匿名线程内累积，导致不同会话相互串话。\n"
        f"实际回答前 200 字：{response.text[:200]}"
    )
