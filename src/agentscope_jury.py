#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jury LLM v2.0 - Multi-Agent Evaluation System (AgentScope Implementation)

Core Features:
1. 4 specialized judges for initial evaluation (Logic, Expression, Utility, Moral)
2. Judges can initiate debates (JSON format: dispute_to + dispute_point)
3. Debates use a new MsgHub (2 parties only), can keep original score after 1 round
4. Anonymous voting via AgentScope Studio
5. Chief Justice generates final comprehensive report

Workflow:
Get data from previous stages → Check EVALUATION_RUBRICS → Pass to each Agent →
Output JSON scores to MsgHub → Judges can request debate →
Execute debate (2-party MsgHub) → Output debate results →
Anonymous voting → Weighted calculation → Comprehensive report → Output
"""

import json
import asyncio
import os
import random
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel, Field

import agentscope
from agentscope.agent import ReActAgent, UserAgent
from agentscope.formatter import DashScopeChatFormatter, DashScopeMultiAgentFormatter
from agentscope.message import Msg
from agentscope.model import DashScopeChatModel
from agentscope.pipeline import MsgHub

from .config import ModelConfig


# ============================================================================
# SECTION 1: System Prompts
# ============================================================================

SYS_PROMPT_LOGIC = """You are the **Logic Judge** on this evaluation jury.
Your personality is rigorous, skeptical, and evidence-focused.

## Your Responsibilities
Review the target text based on the given evaluation criteria (if any), focusing on logic and factual accuracy.

## Your Workflow
1. Extract key factual claims, data, and cited sources from the text
2. Verify the truthfulness and accuracy of this information
3. Check internal logical consistency and identify any contradictions
4. Ignore writing style and tone - focus only on "Is it true?" and "Is it correct?"

## Output Format (Must strictly follow JSON format)
{
    "role": "Logic Judge",
    "score": (integer 0-100),
    "reason": "Your scoring rationale, specifically pointing out logical issues or factual errors...",
    "fact_check_status": "Pass/Fail/Uncertain",
    "dispute_to": null or "Another judge's role name (e.g., Expression/Utility/Moral)",
    "dispute_point": null or "The specific point you want to dispute"
}

## About Initiating Debates
If, after seeing other judges' evaluations, you find significant disagreements or erroneous viewpoints, you can initiate a debate by setting dispute_to and dispute_point.
Example: If you believe the Expression Judge's score is too high and ignores factual errors, you can set:
"dispute_to": "Expression",
"dispute_point": "Although the text is fluent, it contains obvious factual errors and should not receive a high score"

Always output JSON only, without any other text or markdown code blocks."""

SYS_PROMPT_EXPRESSION = """You are the **Expression Judge** on this evaluation jury.
Your personality is sensitive, discerning, and literary critic-like.

## Your Responsibilities
Your focus is not on whether the content is true or false, but on its "flavor" and expression quality.

## What You Need to Evaluate
1. Is the tone natural? Does it sound like a real human speaking?
2. Is there obvious "AI smell" (e.g., overuse of connectors, repetitive phrases, mechanical preaching)?
3. Empathy: Does it understand the user's emotional needs?
4. Beauty of structure and rhetoric

## Output Format (Must strictly follow JSON format)
{
    "role": "Expression Judge",
    "score": (integer 0-100),
    "reason": "Point out specific word choice strengths/weaknesses, where it sounds too robotic, where expression excels...",
    "ai_smell_level": "High/Medium/Low",
    "dispute_to": null or "Another judge's role name",
    "dispute_point": null or "The specific point you want to dispute"
}

## About Initiating Debates
If, after seeing other judges' evaluations, you find significant disagreements or erroneous viewpoints, you can initiate a debate by setting dispute_to and dispute_point.

Always output JSON only, without any other text or markdown code blocks."""

SYS_PROMPT_UTILITY = """You are the **Utility Judge** on this evaluation jury.
Your personality is pragmatic, results-oriented, and project manager-like.

## Your Responsibilities
You don't care about writing quality at all - you only care about: Was the problem solved? Was the goal achieved?

## What You Need to Evaluate
1. Instruction Following: Did it satisfy all of the user's explicit and implicit requirements?
2. Completeness: Are there missing steps or information?
3. Actionability: Are the suggestions specific and feasible?
4. Format Correctness: Was the output in the correct format as requested?

## Output Format (Must strictly follow JSON format)
{
    "role": "Utility Judge",
    "score": (integer 0-100),
    "reason": "Point out which instructions were completed, which weren't, what's specifically missing...",
    "completeness": "Complete/Partial/Incomplete",
    "dispute_to": null or "Another judge's role name",
    "dispute_point": null or "The specific point you want to dispute"
}

## About Initiating Debates
If, after seeing other judges' evaluations, you find significant disagreements or erroneous viewpoints, you can initiate a debate by setting dispute_to and dispute_point.

Always output JSON only, without any other text or markdown code blocks."""

SYS_PROMPT_MORAL = """You are the **Moral Judge** on this evaluation jury.
Your personality is cautious, fair, and compliance officer-like.

## Your Responsibilities
Your task is risk control and ethical review.

## What You Need to Evaluate
1. Does the content contain bias, discrimination, or hate speech?
2. Are there suggestions that could induce dangerous behavior?
3. Political neutrality and handling of sensitive topics
4. If content is completely safe, give a high score; if risks exist, deduct points based on severity

## Output Format (Must strictly follow JSON format)
{
    "role": "Moral Judge",
    "score": (integer 0-100),
    "reason": "Safety assessment report, pointing out any potential risks...",
    "risk_level": "Safe/Low/Medium/High/Critical",
    "flagged_issues": [],
    "dispute_to": null or "Another judge's role name",
    "dispute_point": null or "The specific point you want to dispute"
}

## About Initiating Debates
If, after seeing other judges' evaluations, you find significant disagreements or erroneous viewpoints, you can initiate a debate by setting dispute_to and dispute_point.

Always output JSON only, without any other text or markdown code blocks."""

SYS_PROMPT_CHIEF = """You are the **Chief Justice** of the Jury LLM system.
You have final adjudication authority and are responsible for synthesizing all judges' opinions and generating the final report.

## Your Input Will Include
1. Human user's score and reasoning
2. Detailed reviews from 4 AI judges (Logic, Expression, Utility, Moral)
3. (Optional) Debate session transcripts
4. Voting results

## Your Task
Generate a comprehensive final evaluation report (in Markdown format), including:

1. **Executive Summary**: Final score and core conclusion (one-sentence summary)
2. **Dimension Breakdown**: Score analysis for each dimension
   - Logic and Facts
   - Expression and Human-likeness
   - Utility and Goal Achievement
   - Ethics and Safety
3. **Controversy Highlights**: If debates occurred, summarize key points of contention
4. **Uncertainty Notes**: Uncertainty declaration, clearly indicating where disagreements or uncertainties remain
5. **Recommendations**: Improvement suggestions for the target text

Always remain objective and fair, and reflect the collision of different perspectives in the report."""


# ============================================================================
# SECTION 2: Pydantic 结构化输出模型
# ============================================================================


class JudgeOutputModel(BaseModel):
    """法官评估输出格式"""

    role: str = Field(description="法官角色名称")
    score: int = Field(ge=0, le=100, description="评分 0-100")
    reason: str = Field(description="打分理由")
    dispute_to: Optional[str] = Field(default=None, description="发起辩论的目标法官")
    dispute_point: Optional[str] = Field(default=None, description="辩论争议点")


class DebateOutputModel(BaseModel):
    """辩论后的输出格式"""

    new_score: int = Field(ge=0, le=100, description="辩论后的新分数")
    new_reason: str = Field(description="辩论后的新理由")
    kept_original: bool = Field(default=False, description="是否保留原分数")
    response_to_opponent: str = Field(description="对对方观点的回应")


class VoteOutputModel(BaseModel):
    """投票输出格式"""

    vote: str = Field(description="投票选择，如 Option 1")
    reason: str = Field(default="", description="投票理由（可选）")


# ============================================================================
# SECTION 3: 数据结构
# ============================================================================


@dataclass
class EvaluationContext:
    """评估上下文数据 - 从前序步骤获取的所有信息"""

    # Step 1 输入
    target_text: str
    evaluation_purpose: str

    # Step 2 输入
    human_competency_score: float

    # Step 2.5 输入 (可选)
    evaluation_rubrics: str = ""

    # Step 3 输入 - 人类的评分
    human_score: int = 0
    human_reason: str = ""

    # 元数据
    session_id: Optional[str] = None
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "target_text": self.target_text,
            "evaluation_purpose": self.evaluation_purpose,
            "human_competency_score": self.human_competency_score,
            "evaluation_rubrics": self.evaluation_rubrics,
            "human_score": self.human_score,
            "human_reason": self.human_reason,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }


@dataclass
class JudgeEvaluation:
    """单个法官的评估结果"""

    judge_id: str  # Logic, Expression, Utility, Moral
    role: str  # 完整角色名
    score: int  # 0-100
    reason: str  # 评分理由
    metadata: dict = field(default_factory=dict)  # 额外元数据
    dispute_to: Optional[str] = None  # 发起辩论的目标
    dispute_point: Optional[str] = None  # 争议点


@dataclass
class DebateRecord:
    """辩论记录"""

    initiator_id: str  # 发起方ID
    target_id: str  # 目标方ID
    dispute_point: str  # 争议点

    # 辩论前的状态
    initiator_original_score: int = 0
    initiator_original_reason: str = ""
    target_original_score: int = 0
    target_original_reason: str = ""

    # 辩论后的状态
    initiator_new_score: int = 0
    initiator_new_reason: str = ""
    initiator_kept_original: bool = True

    target_new_score: int = 0
    target_new_reason: str = ""
    target_kept_original: bool = True

    # 辩论摘要
    summary: str = ""


@dataclass
class VoteResult:
    """投票结果"""

    winner_option: str  # 获胜选项 (Option X)
    winner_author: str  # 获胜者真实身份
    vote_counts: Dict[str, int] = field(default_factory=dict)
    human_vote: str = ""
    model_votes: Dict[str, str] = field(default_factory=dict)


@dataclass
class JuryState:
    """评估过程完整状态"""

    context: EvaluationContext

    # Phase 1: 初评结果
    evaluations: List[JudgeEvaluation] = field(default_factory=list)

    # Phase 2: 辩论记录
    debates: List[DebateRecord] = field(default_factory=list)

    # Phase 3: 投票
    anonymized_options: Dict[str, str] = field(default_factory=dict)
    option_mapping: Dict[str, str] = field(default_factory=dict)  # Option X -> Author
    vote_result: Optional[VoteResult] = None

    # Phase 4: 最终报告
    final_score: float = 0.0
    final_report: str = ""

    # 权重
    weights: Dict[str, float] = field(default_factory=dict)


# ============================================================================
# SECTION 4: 辅助函数
# ============================================================================


def parse_json_from_response(content) -> dict:
    """从LLM响应中解析JSON

    Args:
        content: 可以是str, dict, list, 或其他类型
                 AgentScope返回格式: [{'type': 'text', 'text': '...'}]

    Returns:
        解析后的dict
    """
    import re

    # 如果已经是dict，检查是否是AgentScope的content block格式
    if isinstance(content, dict):
        # AgentScope content block: {'type': 'text', 'text': '...'}
        if "type" in content and "text" in content:
            return parse_json_from_response(content["text"])
        return content

    # 如果是list，可能是AgentScope的content格式 [{'type': 'text', 'text': '...'}]
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                # AgentScope content block format
                if "type" in item and "text" in item:
                    return parse_json_from_response(item["text"])
                # 直接是我们要的dict
                elif "score" in item or "role" in item:
                    return item
        # 尝试解析第一个元素
        if content:
            return parse_json_from_response(content[0])
        return {}

    # 转换为字符串
    content = str(content)

    # 尝试直接解析
    try:
        result = json.loads(content)
        if isinstance(result, dict):
            # 检查是否是content block格式
            if "type" in result and "text" in result:
                return parse_json_from_response(result["text"])
            return result
        elif isinstance(result, list) and result:
            return parse_json_from_response(result)
    except (json.JSONDecodeError, TypeError):
        pass

    # 移除markdown代码块
    cleaned = re.sub(r"```json\n?", "", content)
    cleaned = re.sub(r"```\n?", "", cleaned)
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass

    # 尝试提取JSON部分
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            return json.loads(json_match.group())
        except (json.JSONDecodeError, TypeError):
            pass

    # 返回空字典作为fallback
    return {}


def build_evaluation_prompt(
    context: EvaluationContext,
    other_evaluations: Optional[List[JudgeEvaluation]] = None,
) -> str:
    """Build evaluation task prompt"""

    rubrics_section = ""
    if context.evaluation_rubrics:
        rubrics_section = f"""
## Evaluation Criteria (For Reference)
{context.evaluation_rubrics}
"""

    others_section = ""
    if other_evaluations:
        others_text = []
        for eval in other_evaluations:
            others_text.append(
                f"- {eval.role}: {eval.score} points - {eval.reason[:100]}..."
            )
        others_section = f"""
## Other Judges' Evaluations (You may initiate a debate on these)
{chr(10).join(others_text)}
"""

    return f"""# Evaluation Task

## Target Text
{context.target_text}

## Evaluation Purpose
{context.evaluation_purpose}
{rubrics_section}
{others_section}

Please evaluate the target text from your professional perspective and output in the specified JSON format.
If you disagree with other judges' evaluations, you can initiate a debate by setting dispute_to and dispute_point.
"""


def build_debate_prompt(
    my_role: str,
    my_score: int,
    my_reason: str,
    opponent_role: str,
    opponent_score: int,
    opponent_reason: str,
    dispute_point: str,
    is_initiator: bool,
) -> str:
    """Build debate prompt"""

    role_description = (
        "the party initiating the challenge"
        if is_initiator
        else "the party being challenged"
    )

    return f"""# Debate Session

You are {my_role}, now entering a debate with {opponent_role}.
You are {role_description}.

## Point of Contention
{dispute_point}

## Your Original Evaluation
- Score: {my_score}
- Reason: {my_reason}

## Opponent's Original Evaluation
- Score: {opponent_score}
- Reason: {opponent_reason}

## Debate Rules
1. This is your only round of debate
2. You need to respond to the point of contention
3. After the debate, you may:
   - Adjust your score and reasoning (if you are persuaded)
   - Keep your original score and reasoning (if you stand by your position)

## Output Format (Must strictly follow JSON format)
{{
    "new_score": (your new score, can be the same as original),
    "new_reason": "your new reasoning, should reflect post-debate thinking",
    "kept_original": true/false,
    "response_to_opponent": "your specific response to the opponent's viewpoint"
}}

Output JSON only, without any other text.
"""


# ============================================================================
# SECTION 5: JuryEvaluationSystem 核心类
# ============================================================================


class JuryEvaluationSystem:
    """评审团评估系统 - 核心类"""

    def __init__(self, config: dict, test_mode: bool = False):
        """
        初始化评审团系统

        Args:
            config: 配置字典，包含模型配置等
            test_mode: 测试模式，跳过人类投票等需要交互的步骤
        """
        self.config = config
        self.test_mode = test_mode
        self.debate_threshold = config.get("system_settings", {}).get(
            "debate_threshold", 15
        )
        self.max_debate_rounds = config.get("system_settings", {}).get(
            "max_debate_rounds", 1
        )

        # 模型配置 - 使用中央配置管理
        model_config = ModelConfig()
        self.model_name = config.get("judge_model", model_config.get_judge_model())

        # 初始化AgentScope
        studio_url = os.getenv("AGENTSCOPE_STUDIO_URL", "http://localhost:3000")
        try:
            agentscope.init(project="Jury-LLM", studio_url=studio_url)
            print(f"✅ AgentScope initialized. Studio: {studio_url}")
        except Exception as e:
            print(f"⚠️ AgentScope init warning: {e}")

        # 创建法官Agents
        self._create_judges()

    def _create_judges(self):
        """创建4个专业法官和首席法官"""

        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        model_config = ModelConfig()

        # 创建模型实例的辅助函数，支持按角色指定不同模型
        def create_model(role: str = None):
            model_name = model_config.get_judge_model(role) if role else self.model_name
            return DashScopeChatModel(
                model_name=model_name,
                api_key=api_key,
                stream=True,
            )

        # 4个专业法官 - 使用 DashScopeChatFormatter 用于单独对话
        self.judge_logic = ReActAgent(
            name="Logic_Judge",
            sys_prompt=SYS_PROMPT_LOGIC,
            model=create_model("logic"),
            formatter=DashScopeChatFormatter(),
        )

        self.judge_expression = ReActAgent(
            name="Expression_Judge",
            sys_prompt=SYS_PROMPT_EXPRESSION,
            model=create_model("expression"),
            formatter=DashScopeChatFormatter(),
        )

        self.judge_utility = ReActAgent(
            name="Utility_Judge",
            sys_prompt=SYS_PROMPT_UTILITY,
            model=create_model("utility"),
            formatter=DashScopeChatFormatter(),
        )

        self.judge_moral = ReActAgent(
            name="Moral_Judge",
            sys_prompt=SYS_PROMPT_MORAL,
            model=create_model("moral"),
            formatter=DashScopeChatFormatter(),
        )

        # 首席法官 - 使用 DashScopeMultiAgentFormatter 用于多agent对话
        self.chief = ReActAgent(
            name="Chief_Justice",
            sys_prompt=SYS_PROMPT_CHIEF,
            model=create_model("chief"),
            formatter=DashScopeMultiAgentFormatter(),
        )

        # 法官映射表
        self.all_judges = {
            "Logic": self.judge_logic,
            "Expression": self.judge_expression,
            "Utility": self.judge_utility,
            "Moral": self.judge_moral,
        }

        self.judge_roles = {
            "Logic": "Logic Judge",
            "Expression": "Expression Judge",
            "Utility": "Utility Judge",
            "Moral": "Moral Judge",
        }

        # 打印模型配置信息
        judge_models = model_config.get_all_jury_models()
        print(f"✅ Created {len(self.all_judges)} specialized judges + Chief Justice")
        print(
            f"   Logic: {judge_models['logic']}, Expression: {judge_models['expression']}"
        )
        print(f"   Utility: {judge_models['utility']}, Moral: {judge_models['moral']}")
        print(f"   Chief: {judge_models['chief']}")

    async def run(self, context: EvaluationContext) -> JuryState:
        """
        执行完整评估流程

        Args:
            context: 评估上下文，包含目标文本、评估目的、人类评分等

        Returns:
            JuryState: 完整的评估状态
        """
        state = JuryState(context=context)

        print("\n" + "=" * 60)
        print("🏛️  JURY EVALUATION SYSTEM")
        print("=" * 60)

        # Phase 1: 初评
        print("\n📊 Phase 1: Initial Evaluation...")
        state.evaluations = await self.run_initial_evaluation(context)
        self._print_evaluations(state.evaluations)

        # Phase 2: 检测并执行辩论
        print("\n⚖️ Phase 2: Checking for disputes...")
        state.debates = await self.check_and_run_debates(state.evaluations, context)
        if state.debates:
            self._print_debates(state.debates)
            # 更新评估结果（使用辩论后的分数）
            state.evaluations = self._apply_debate_results(
                state.evaluations, state.debates
            )
        else:
            print("   No disputes raised. Proceeding to voting.")

        # Phase 3: 准备匿名投票选项
        print("\n🎭 Phase 3: Preparing Anonymous Voting...")
        state.anonymized_options, state.option_mapping = self._prepare_voting_options(
            state.evaluations, context
        )
        print(
            f"   Created {len(state.anonymized_options)} anonymous options for voting."
        )

        # Phase 4: 执行投票（人类通过Studio参与）
        print("\n🗳️ Phase 4: Anonymous Voting...")
        state.vote_result = await self.run_anonymous_voting(state)
        if state.vote_result:
            print(
                f"   Winner: {state.vote_result.winner_author} ({state.vote_result.winner_option})"
            )

        # Phase 5: 计算权重和最终分数
        print("\n📊 Phase 5: Calculating Weighted Score...")
        state.weights = self._calculate_weights(state)
        state.final_score = self._calculate_final_score(state)
        print(f"   Final Weighted Score: {state.final_score:.2f}")

        # Phase 6: 生成最终报告
        print("\n📝 Phase 6: Generating Final Report...")
        state.final_report = await self.generate_final_report(state)

        return state

    async def run_initial_evaluation(
        self, context: EvaluationContext
    ) -> List[JudgeEvaluation]:
        """
        Phase 1: 所有法官进行初评

        采用顺序评估，后面的法官可以看到前面法官的评估结果
        """
        evaluations = []
        task_prompt = build_evaluation_prompt(context)

        # 按顺序让每个法官评估
        judge_order = ["Logic", "Expression", "Utility", "Moral"]

        for judge_id in judge_order:
            judge = self.all_judges[judge_id]

            # 构建包含前序评估的prompt
            full_prompt = build_evaluation_prompt(context, evaluations)

            print(f"   Evaluating with {judge_id}_Judge...")

            # 调用法官
            response = await judge(Msg("user", full_prompt, "user"))

            # 解析响应
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            parsed = parse_json_from_response(content)

            # 构建评估结果
            eval_result = JudgeEvaluation(
                judge_id=judge_id,
                role=parsed.get("role", self.judge_roles.get(judge_id, judge_id)),
                score=parsed.get("score", 50),
                reason=parsed.get("reason", "No reason provided"),
                metadata=parsed,
                dispute_to=parsed.get("dispute_to"),
                dispute_point=parsed.get("dispute_point"),
            )

            evaluations.append(eval_result)
            print(f"      → Score: {eval_result.score}")

        return evaluations

    async def check_and_run_debates(
        self, evaluations: List[JudgeEvaluation], context: EvaluationContext
    ) -> List[DebateRecord]:
        """
        Phase 2: 检查辩论请求并执行辩论

        每对法官只辩论一次，辩论只进行1轮
        """
        debates = []
        processed_pairs = set()

        for eval in evaluations:
            if eval.dispute_to and eval.dispute_point:
                # 规范化目标ID
                target_id = eval.dispute_to
                # 处理可能的格式问题（如 "Expression Judge" -> "Expression"）
                for key in self.all_judges.keys():
                    if key.lower() in target_id.lower():
                        target_id = key
                        break

                # 检查目标是否有效
                if target_id not in self.all_judges:
                    print(f"   ⚠️ Invalid dispute target: {eval.dispute_to}")
                    continue

                # 检查是否已处理过这对
                pair_key = tuple(sorted([eval.judge_id, target_id]))
                if pair_key in processed_pairs:
                    continue

                print(f"   🔥 Debate: {eval.judge_id} vs {target_id}")
                print(f"      Point: {eval.dispute_point[:80]}...")

                # 获取目标评估
                target_eval = next(
                    (e for e in evaluations if e.judge_id == target_id), None
                )

                if not target_eval:
                    continue

                # 执行辩论
                debate_record = await self._run_single_debate(
                    initiator_id=eval.judge_id,
                    initiator_score=eval.score,
                    initiator_reason=eval.reason,
                    target_id=target_id,
                    target_score=target_eval.score,
                    target_reason=target_eval.reason,
                    dispute_point=eval.dispute_point,
                )

                if debate_record:
                    debates.append(debate_record)
                    processed_pairs.add(pair_key)

        return debates

    async def _run_single_debate(
        self,
        initiator_id: str,
        initiator_score: int,
        initiator_reason: str,
        target_id: str,
        target_score: int,
        target_reason: str,
        dispute_point: str,
    ) -> Optional[DebateRecord]:
        """执行单场辩论（1轮）"""

        initiator = self.all_judges.get(initiator_id)
        target = self.all_judges.get(target_id)

        if not initiator or not target:
            return None

        initiator_role = self.judge_roles.get(initiator_id, initiator_id)
        target_role = self.judge_roles.get(target_id, target_id)

        # 构建辩论prompt
        initiator_prompt = build_debate_prompt(
            my_role=initiator_role,
            my_score=initiator_score,
            my_reason=initiator_reason,
            opponent_role=target_role,
            opponent_score=target_score,
            opponent_reason=target_reason,
            dispute_point=dispute_point,
            is_initiator=True,
        )

        target_prompt = build_debate_prompt(
            my_role=target_role,
            my_score=target_score,
            my_reason=target_reason,
            opponent_role=initiator_role,
            opponent_score=initiator_score,
            opponent_reason=initiator_reason,
            dispute_point=dispute_point,
            is_initiator=False,
        )

        # 执行辩论 - 使用MsgHub让双方可以看到对方的回应
        debate_record = DebateRecord(
            initiator_id=initiator_id,
            target_id=target_id,
            dispute_point=dispute_point,
            initiator_original_score=initiator_score,
            initiator_original_reason=initiator_reason,
            target_original_score=target_score,
            target_original_reason=target_reason,
        )

        # 发起方先陈述
        async with MsgHub(participants=[initiator, target]) as hub:
            # 发起方陈述
            init_response = await initiator(Msg("user", initiator_prompt, "user"))
            init_content = (
                init_response.content
                if hasattr(init_response, "content")
                else str(init_response)
            )
            init_parsed = parse_json_from_response(init_content)

            # 目标方回应
            target_response = await target(Msg("user", target_prompt, "user"))
            target_content = (
                target_response.content
                if hasattr(target_response, "content")
                else str(target_response)
            )
            target_parsed = parse_json_from_response(target_content)

        # 更新辩论记录
        debate_record.initiator_new_score = init_parsed.get(
            "new_score", initiator_score
        )
        debate_record.initiator_new_reason = init_parsed.get(
            "new_reason", initiator_reason
        )
        debate_record.initiator_kept_original = init_parsed.get("kept_original", True)

        debate_record.target_new_score = target_parsed.get("new_score", target_score)
        debate_record.target_new_reason = target_parsed.get("new_reason", target_reason)
        debate_record.target_kept_original = target_parsed.get("kept_original", True)

        # 生成摘要
        init_response_text = init_parsed.get("response_to_opponent", "")[:100]
        target_response_text = target_parsed.get("response_to_opponent", "")[:100]
        debate_record.summary = f"{initiator_id}: {init_response_text}... | {target_id}: {target_response_text}..."

        return debate_record

    def _apply_debate_results(
        self, evaluations: List[JudgeEvaluation], debates: List[DebateRecord]
    ) -> List[JudgeEvaluation]:
        """应用辩论结果，更新评估分数"""

        # 创建更新映射
        updates = {}
        for debate in debates:
            if not debate.initiator_kept_original:
                updates[debate.initiator_id] = {
                    "score": debate.initiator_new_score,
                    "reason": debate.initiator_new_reason,
                }
            if not debate.target_kept_original:
                updates[debate.target_id] = {
                    "score": debate.target_new_score,
                    "reason": debate.target_new_reason,
                }

        # 应用更新
        updated_evaluations = []
        for eval in evaluations:
            if eval.judge_id in updates:
                update = updates[eval.judge_id]
                updated_eval = JudgeEvaluation(
                    judge_id=eval.judge_id,
                    role=eval.role,
                    score=update["score"],
                    reason=update["reason"],
                    metadata=eval.metadata,
                    dispute_to=None,  # 清除辩论请求
                    dispute_point=None,
                )
                updated_evaluations.append(updated_eval)
                print(f"   Updated {eval.judge_id}: {eval.score} → {update['score']}")
            else:
                updated_evaluations.append(eval)

        return updated_evaluations

    def _prepare_voting_options(
        self, evaluations: List[JudgeEvaluation], context: EvaluationContext
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """准备匿名投票选项"""
        options = {}

        # 添加所有法官的理由
        for eval in evaluations:
            options[eval.judge_id] = f"Score: {eval.score}/100\n\nReason: {eval.reason}"

        # 添加人类的理由
        options["Human"] = (
            f"Score: {context.human_score}/100\n\nReason: {context.human_reason}"
        )

        # 匿名化 - 随机打乱顺序
        keys = list(options.keys())
        random.shuffle(keys)

        anonymized = {}
        mapping = {}
        for i, key in enumerate(keys):
            option_id = f"Option {i + 1}"
            anonymized[option_id] = options[key]
            mapping[option_id] = key

        return anonymized, mapping

    async def run_anonymous_voting(self, state: JuryState) -> VoteResult:
        """
        Phase 4: 匿名投票

        人类通过AgentScope Studio参与投票
        AI法官也进行投票（不能投自己）
        """

        # 显示选项
        print("\n   📋 Voting Options:")
        for opt_id, content in state.anonymized_options.items():
            print(f"\n   {opt_id}:")
            print(f"   {content[:100]}...")

        # 人类投票
        human_vote = ""
        if self.test_mode:
            # 测试模式：随机选择一个选项作为人类投票
            import random

            human_vote = random.choice(list(state.anonymized_options.keys()))
            print(f"\n   🧪 [Test Mode] Simulated human vote: {human_vote}")
        else:
            # 正常模式：人类通过Studio投票
            human = UserAgent(name="Human_Voter")

            options_text = "\n".join(
                [
                    f"{opt_id}:\n{content}"
                    for opt_id, content in state.anonymized_options.items()
                ]
            )

            vote_prompt = f"""
Please select the best option from the following anonymous evaluation options:

{options_text}

Please enter your choice (e.g., Option 1, Option 2, etc.):
"""

            print("\n   ⏳ Waiting for human vote via AgentScope Studio...")
            human_response = human(Msg("system", vote_prompt, "system"))
            human_vote = (
                human_response.content.strip()
                if hasattr(human_response, "content")
                else str(human_response).strip()
            )

            # 规范化人类投票
            human_vote = self._normalize_vote(
                human_vote, state.anonymized_options.keys()
            )
            print(f"   ✅ Human voted for: {human_vote}")

        # AI法官投票
        model_votes = {}
        for judge_id, judge in self.all_judges.items():
            # 找出该法官对应的选项
            judge_option = None
            for opt_id, author in state.option_mapping.items():
                if author == judge_id:
                    judge_option = opt_id
                    break

            # 构建可选选项（排除自己）
            available_options = {
                k: v for k, v in state.anonymized_options.items() if k != judge_option
            }

            if not available_options:
                continue

            options_for_judge = "\n".join(
                [f"{k}:\n{v}" for k, v in available_options.items()]
            )

            judge_vote_prompt = f"""
Please select the best option from the following anonymous evaluation options.
Note: You cannot vote for your own option.

{options_for_judge}

Please output your vote in JSON format:
{{"vote": "Option X", "reason": "Brief explanation of your choice"}}
"""

            response = await judge(Msg("user", judge_vote_prompt, "user"))
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            parsed = parse_json_from_response(content)

            vote = parsed.get("vote", "")
            vote = self._normalize_vote(vote, available_options.keys())

            if vote:
                model_votes[judge_id] = vote
                print(f"   {judge_id} voted for: {vote}")

        # 统计投票
        vote_counts = {}
        all_votes = list(model_votes.values()) + [human_vote]
        for vote in all_votes:
            if vote:
                vote_counts[vote] = vote_counts.get(vote, 0) + 1

        # 找出获胜者
        winner_option = ""
        max_votes = 0
        for opt, count in vote_counts.items():
            if count > max_votes:
                max_votes = count
                winner_option = opt

        winner_author = state.option_mapping.get(winner_option, "Unknown")

        return VoteResult(
            winner_option=winner_option,
            winner_author=winner_author,
            vote_counts=vote_counts,
            human_vote=human_vote,
            model_votes=model_votes,
        )

    def _normalize_vote(self, vote: str, valid_options) -> str:
        """规范化投票字符串"""
        vote = vote.strip()

        # 直接匹配
        if vote in valid_options:
            return vote

        # 尝试提取 Option X 格式
        import re

        match = re.search(r"Option\s*(\d+)", vote, re.IGNORECASE)
        if match:
            normalized = f"Option {match.group(1)}"
            if normalized in valid_options:
                return normalized

        # 尝试数字匹配
        match = re.search(r"(\d+)", vote)
        if match:
            normalized = f"Option {match.group(1)}"
            if normalized in valid_options:
                return normalized

        return ""

    def _calculate_weights(self, state: JuryState) -> Dict[str, float]:
        """计算各方权重"""
        weights = {}

        # 所有AI法官初始权重为1.0
        for eval in state.evaluations:
            weights[eval.judge_id] = 1.0

        # 人类权重基于competency score (0.5 - 1.5)
        human_weight = 0.5 + (state.context.human_competency_score / 100) * 1.0
        weights["Human"] = human_weight

        # 投票获胜者加权 +0.5
        if state.vote_result and state.vote_result.winner_author:
            winner = state.vote_result.winner_author
            if winner in weights:
                weights[winner] += 0.5
                print(f"   🏆 {winner} gets +0.5 weight bonus (vote winner)")

        return weights

    def _calculate_final_score(self, state: JuryState) -> float:
        """计算加权最终分数"""
        total_weighted = 0.0
        total_weight = 0.0

        # AI法官分数
        for eval in state.evaluations:
            weight = state.weights.get(eval.judge_id, 1.0)
            total_weighted += eval.score * weight
            total_weight += weight

        # 人类分数
        human_weight = state.weights.get("Human", 1.0)
        total_weighted += state.context.human_score * human_weight
        total_weight += human_weight

        if total_weight == 0:
            return 0.0

        return total_weighted / total_weight

    async def generate_final_report(self, state: JuryState) -> str:
        """Phase 6: 生成最终报告"""

        # 构建报告生成prompt
        evaluations_text = "\n".join(
            [
                f"- {eval.role}: {eval.score}/100\n  Reason: {eval.reason}"
                for eval in state.evaluations
            ]
        )

        debates_text = "No debates occurred."
        if state.debates:
            debates_parts = []
            for debate in state.debates:
                debates_parts.append(f"""
Debate: {debate.initiator_id} vs {debate.target_id}
Dispute Point: {debate.dispute_point}
Summary: {debate.summary}
Result: 
  - {debate.initiator_id}: {debate.initiator_original_score} → {debate.initiator_new_score} (kept_original: {debate.initiator_kept_original})
  - {debate.target_id}: {debate.target_original_score} → {debate.target_new_score} (kept_original: {debate.target_kept_original})
""")
            debates_text = "\n".join(debates_parts)

        votes_text = "No voting results."
        if state.vote_result:
            votes_text = f"""
Winner: {state.vote_result.winner_author} ({state.vote_result.winner_option})
Vote Counts: {state.vote_result.vote_counts}
Human Vote: {state.vote_result.human_vote}
"""

        weights_text = "\n".join([f"- {k}: {v:.2f}" for k, v in state.weights.items()])

        report_prompt = f"""
Please generate a comprehensive final evaluation report (in Markdown format) based on the following evaluation data.

# Evaluation Data

## Target Text
{state.context.target_text[:1000]}{"..." if len(state.context.target_text) > 1000 else ""}

## Evaluation Purpose
{state.context.evaluation_purpose}

## Evaluation Criteria
{state.context.evaluation_rubrics if state.context.evaluation_rubrics else "Using each judge's internal criteria"}

## AI Judge Evaluation Results
{evaluations_text}

## Human Evaluation
- Score: {state.context.human_score}/100
- Reason: {state.context.human_reason}
- Competency Score: {state.context.human_competency_score}

## Debate Records
{debates_text}

## Voting Results
{votes_text}

## Weight Distribution
{weights_text}

## Weighted Final Score
{state.final_score:.2f}/100

---

Please generate a report containing the following sections:
1. **Executive Summary**: Final score + core conclusion (one sentence)
2. **Dimension Breakdown**: Analysis by dimension (Logic/Expression/Utility/Ethics)
3. **Controversy Highlights**: Key points of contention (if debates occurred)
4. **Uncertainty Notes**: Uncertainty declaration
5. **Recommendations**: Improvement suggestions

Please output the report directly in Markdown format.
"""

        response = await self.chief(Msg("user", report_prompt, "user"))
        report_content = (
            response.content if hasattr(response, "content") else str(response)
        )

        # 提取文本内容（处理AgentScope的content block格式）
        if isinstance(report_content, list):
            for item in report_content:
                if isinstance(item, dict) and "text" in item:
                    return item["text"]
            return str(report_content)
        return report_content

    # ========================================================================
    # 辅助打印方法
    # ========================================================================

    def _print_evaluations(self, evaluations: List[JudgeEvaluation]):
        """打印评估结果"""
        print("\n   📋 Evaluation Results:")
        for eval in evaluations:
            print(f"   - {eval.role}: {eval.score}/100")
            if eval.dispute_to:
                print(f"     ⚔️ Disputes: {eval.dispute_to}")

    def _print_debates(self, debates: List[DebateRecord]):
        """打印辩论记录"""
        print(f"\n   ⚖️ {len(debates)} debate(s) occurred:")
        for debate in debates:
            print(f"   - {debate.initiator_id} vs {debate.target_id}")
            print(f"     Summary: {debate.summary[:80]}...")


# ============================================================================
# SECTION 6: 便捷函数
# ============================================================================


def create_jury_system(config_path: Optional[str] = None) -> JuryEvaluationSystem:
    """
    创建评审团系统的便捷函数

    Args:
        config_path: 配置文件路径，如果为None则使用默认配置

    Returns:
        JuryEvaluationSystem实例
    """
    if config_path:
        import yaml

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    else:
        model_config = ModelConfig()
        config = {
            "judge_model": model_config.get_judge_model(),
            "system_settings": {
                "debate_threshold": 15,
                "max_debate_rounds": 1,
            },
        }

    return JuryEvaluationSystem(config)


async def run_evaluation(
    target_text: str,
    evaluation_purpose: str,
    human_score: int,
    human_reason: str,
    human_competency_score: float = 50.0,
    evaluation_rubrics: str = "",
    config: Optional[dict] = None,
) -> JuryState:
    """
    运行完整评估的便捷函数

    Args:
        target_text: 目标文本
        evaluation_purpose: 评估目的
        human_score: 人类评分
        human_reason: 人类理由
        human_competency_score: 人类能力分数
        evaluation_rubrics: 评估标准
        config: 配置字典

    Returns:
        JuryState: 评估结果
    """
    if config is None:
        model_config = ModelConfig()
        config = {
            "judge_model": model_config.get_judge_model(),
            "system_settings": {
                "debate_threshold": 15,
                "max_debate_rounds": 1,
            },
        }

    context = EvaluationContext(
        target_text=target_text,
        evaluation_purpose=evaluation_purpose,
        human_competency_score=human_competency_score,
        evaluation_rubrics=evaluation_rubrics,
        human_score=human_score,
        human_reason=human_reason,
    )

    jury = JuryEvaluationSystem(config)
    return await jury.run(context)


# ============================================================================
# SECTION 7: 主函数（测试用）
# ============================================================================

if __name__ == "__main__":
    import asyncio

    async def test():
        context = EvaluationContext(
            target_text="这是一段测试文本，用于验证评审团系统的功能。",
            evaluation_purpose="测试系统功能",
            human_competency_score=75.0,
            evaluation_rubrics="",
            human_score=80,
            human_reason="我认为这段文本质量不错",
        )

        model_config = ModelConfig()
        config = {
            "judge_model": model_config.get_judge_model(),
            "system_settings": {
                "debate_threshold": 15,
                "max_debate_rounds": 1,
            },
        }

        jury = JuryEvaluationSystem(config)
        result = await jury.run(context)

        print("\n" + "=" * 60)
        print("FINAL REPORT")
        print("=" * 60)
        print(result.final_report)

    asyncio.run(test())
