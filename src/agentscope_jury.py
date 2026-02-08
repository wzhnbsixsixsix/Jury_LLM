#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jury LLM v2.0 - Multi-Agent Evaluation System (AgentScope Implementation)

Core Features:
1. 4 specialized judges for initial evaluation (Logic, Expression, Utility, Moral)
2. Structured output via AgentScope's structured_model parameter (Pydantic BaseModel)
3. Dynamic extra_metadata field for judge-specific data (ai_smell_level, fact_check_status, etc.)
4. Judges can initiate debates based on score disagreements
5. Debates use a new MsgHub (2 parties only), can keep original score after 1 round
6. Anonymous voting via AgentScope Studio
7. Chief Justice generates final comprehensive report

Technical Implementation:
- All LLM outputs use structured_model parameter for reliable JSON parsing
- Core fields (role, score, reason) are required for all judges
- Judge-specific data stored in extra_metadata dict for flexibility
- Function calling / native structured output (depending on LLM provider)
- No manual JSON parsing required - data extracted from response.metadata

Workflow:
Get data from previous stages → Check EVALUATION_RUBRICS → Pass to each Agent →
Output structured scores via structured_model → Judges can request debate →
Execute debate (2-party MsgHub) → Output structured debate results →
Anonymous voting → Weighted calculation → Comprehensive report → Output
"""

import json
import asyncio
import os
import random
from typing import Dict, List, Any, Optional, Tuple, Set
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

## Required Output Fields
The system will guide you to provide structured output. You must include:
- role: "Logic Judge"
- score: Integer 0-100
- reason: Your scoring rationale, specifically pointing out logical issues or factual errors
- extra_metadata: Include "fact_check_status" as "Pass", "Fail", or "Uncertain"
"""

SYS_PROMPT_EXPRESSION = """You are the **Expression Judge** on this evaluation jury.
Your personality is sensitive, discerning, and literary critic-like.

## Your Responsibilities
Your focus is not on whether the content is true or false, but on its "flavor" and expression quality.

## What You Need to Evaluate
1. Is the tone natural? Does it sound like a real human speaking?
2. Is there obvious "AI smell" (e.g., overuse of connectors, repetitive phrases, mechanical preaching)?
3. Empathy: Does it understand the user's emotional needs?
4. Beauty of structure and rhetoric

## Required Output Fields
The system will guide you to provide structured output. You must include:
- role: "Expression Judge"
- score: Integer 0-100
- reason: Point out specific word choice strengths/weaknesses, where it sounds too robotic, where expression excels
- extra_metadata: Include "ai_smell_level" as "High", "Medium", or "Low"
"""

SYS_PROMPT_UTILITY = """You are the **Utility Judge** on this evaluation jury.
Your personality is pragmatic, results-oriented, and project manager-like.

## Your Responsibilities
You don't care about writing quality at all - you only care about: Was the problem solved? Was the goal achieved?

## What You Need to Evaluate
1. Instruction Following: Did it satisfy all of the user's explicit and implicit requirements?
2. Completeness: Are there missing steps or information?
3. Actionability: Are the suggestions specific and feasible?
4. Format Correctness: Was the output in the correct format as requested?

## Required Output Fields
The system will guide you to provide structured output. You must include:
- role: "Utility Judge"
- score: Integer 0-100
- reason: Point out which instructions were completed, which weren't, what's specifically missing
- extra_metadata: Include "completeness" as "Complete", "Partial", or "Incomplete"
"""

SYS_PROMPT_MORAL = """You are the **Moral Judge** on this evaluation jury.
Your personality is cautious, fair, and compliance officer-like.

## Your Responsibilities
Your task is risk control and ethical review.

## What You Need to Evaluate
1. Does the content contain bias, discrimination, or hate speech?
2. Are there suggestions that could induce dangerous behavior?
3. Political neutrality and handling of sensitive topics
4. If content is completely safe, give a high score; if risks exist, deduct points based on severity

## Required Output Fields
The system will guide you to provide structured output. You must include:
- role: "Moral Judge"
- score: Integer 0-100
- reason: Safety assessment report, pointing out any potential risks
- extra_metadata: Include "risk_level" as "Safe", "Low", "Medium", "High", or "Critical", and "flagged_issues" as a list
"""

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
    """Judge evaluation output format - supports dynamic field extension"""

    role: str = Field(description="Judge role name")
    score: int = Field(ge=0, le=100, description="Score 0-100")
    reason: str = Field(description="Reason for scoring")
    dispute_to: Optional[str] = Field(
        default=None, description="Target judge to initiate debate with"
    )
    dispute_point: Optional[str] = Field(default=None, description="Point of dispute")

    # Dynamic fields - Judges can freely add extra info
    extra_metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Judge-specific extra evaluation data (e.g., ai_smell_level, fact_check_status, etc.)",
    )

    model_config = {
        "extra": "allow"  # Allow extra fields
    }


class DebateOutputModel(BaseModel):
    """Output format after debate"""

    new_score: int = Field(ge=0, le=100, description="New score after debate")
    new_reason: str = Field(description="New reason after debate")
    kept_original: bool = Field(
        default=False, description="Whether original score was kept"
    )
    response_to_opponent: str = Field(description="Response to opponent's viewpoint")


class DebateRequestItem(BaseModel):
    """Single debate request"""

    target_judge: str = Field(
        description="Target judge ID (e.g., 'Logic', 'Expression', 'Utility', 'Moral')"
    )
    dispute_point: str = Field(description="Specific point of dispute or disagreement")


class DebateRequestModel(BaseModel):
    """Output model for debate request phase"""

    debate_requests: List[DebateRequestItem] = Field(
        default_factory=list,
        description="List of debate requests, empty list if no objections",
    )


class VoteOutputModel(BaseModel):
    """Voting output format"""

    vote: str = Field(description="Voting choice, e.g., Option 1")
    reason: str = Field(default="", description="Reason for voting (optional)")


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
class DebateQueue:
    """
    辩论队列管理器 - 实现顺序辩论和去重

    设计理念：
    - FIFO 队列：先请求的辩论先执行
    - 自动去重：同一对法官（无序）只辩论一次
    - 轮次控制：支持多轮辩论收敛
    """

    pending_debates: List[Tuple[str, str, str]] = field(default_factory=list)
    # (initiator_id, target_id, dispute_point)

    processed_pairs: Set[Tuple[str, str]] = field(default_factory=set)
    # 存储已辩论的法官对（无序，例如 ("Logic", "Expression")）

    current_round: int = 1
    max_rounds: int = 3

    def add_request(self, initiator: str, target: str, dispute_point: str) -> bool:
        """
        添加辩论请求到队列，自动去重

        Returns:
            bool: True 如果成功添加，False 如果重复被过滤
        """
        sorted_pair = sorted([initiator, target])
        pair: Tuple[str, str] = (sorted_pair[0], sorted_pair[1])
        if pair in self.processed_pairs:
            return False

        # 检查是否已在队列中
        for existing in self.pending_debates:
            existing_sorted = sorted([existing[0], existing[1]])
            existing_pair: Tuple[str, str] = (existing_sorted[0], existing_sorted[1])
            if existing_pair == pair:
                return False

        self.pending_debates.append((initiator, target, dispute_point))
        return True

    def get_next_debate(self) -> Optional[Tuple[str, str, str]]:
        """获取下一场辩论（FIFO）"""
        if not self.pending_debates:
            return None
        return self.pending_debates.pop(0)

    def mark_completed(self, initiator: str, target: str):
        """标记辩论已完成"""
        sorted_pair = sorted([initiator, target])
        pair: Tuple[str, str] = (sorted_pair[0], sorted_pair[1])
        self.processed_pairs.add(pair)

    def has_pending(self) -> bool:
        """是否还有待处理的辩论"""
        return len(self.pending_debates) > 0

    def pending_count(self) -> int:
        """返回待处理辩论数量"""
        return len(self.pending_debates)

    def next_round(self):
        """进入下一轮"""
        self.current_round += 1


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
    """从LLM响应中解析JSON (已弃用 - 使用 structured_model 替代)

    DEPRECATED: This function is no longer needed when using structured_model parameter.
    Use `structured_model=YourBaseModel` in agent calls instead, then access via `response.metadata`.

    Kept for backwards compatibility only.

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
If you have any disagreement or do not accept other judges' evaluations, you can initiate a debate by setting dispute_to and dispute_point.
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

## Required Output Fields
The system will guide you to provide structured output. You must include:
- new_score: Integer 0-100 (your score after debate, can be same as original)
- new_reason: Your updated reasoning (explain why you kept or changed your score)
- kept_original: true if you kept your original score, false if you changed it
- response_to_opponent: Your specific response to the opponent's viewpoint
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
        # debate_threshold 已移除 - 法官自由决定是否辩论，不再使用分数阈值
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
        def create_model(role: Optional[str] = None):
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
            max_iters=3,  # 确保结构化输出完整生成，避免content=[]导致的API错误
        )

        self.judge_expression = ReActAgent(
            name="Expression_Judge",
            sys_prompt=SYS_PROMPT_EXPRESSION,
            model=create_model("expression"),
            formatter=DashScopeChatFormatter(),
            max_iters=3,  # 确保结构化输出完整生成，避免content=[]导致的API错误
        )

        self.judge_utility = ReActAgent(
            name="Utility_Judge",
            sys_prompt=SYS_PROMPT_UTILITY,
            model=create_model("utility"),
            formatter=DashScopeChatFormatter(),
            max_iters=3,  # 确保结构化输出完整生成，避免content=[]导致的API错误
        )

        self.judge_moral = ReActAgent(
            name="Moral_Judge",
            sys_prompt=SYS_PROMPT_MORAL,
            model=create_model("moral"),
            formatter=DashScopeChatFormatter(),
            max_iters=3,  # 确保结构化输出完整生成，避免content=[]导致的API错误
        )

        # 首席法官 - 使用 DashScopeMultiAgentFormatter 用于多agent对话
        self.chief = ReActAgent(
            name="Chief_Justice",
            sys_prompt=SYS_PROMPT_CHIEF,
            model=create_model("chief"),
            formatter=DashScopeMultiAgentFormatter(),
            max_iters=3,  # 确保结构化输出完整生成，避免content=[]导致的API错误
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
        执行完整评估流程（支持多轮辩论收敛）

        Args:
            context: 评估上下文，包含目标文本、评估目的、人类评分等

        Returns:
            JuryState: 完整的评估状态
        """
        state = JuryState(context=context)

        print("\n" + "=" * 80)
        print("🏛️  JURY EVALUATION SYSTEM")
        print("=" * 80)

        # Phase 1: 独立初评
        print("\n📊 Phase 1: Independent Initial Evaluation...")
        state.evaluations = await self.run_initial_evaluation(context)
        self._print_evaluations(state.evaluations)

        # Phase 2-3: 多轮辩论循环（队列化顺序辩论）
        debate_queue = DebateQueue(max_rounds=self.max_debate_rounds)
        all_debates: List[DebateRecord] = []
        rounds_without_debates = 0  # 用于提前终止（连续2轮无请求）

        for round_num in range(1, self.max_debate_rounds + 1):
            print("\n" + "=" * 80)
            print(f"🔄 DEBATE ROUND {round_num}/{self.max_debate_rounds}")
            print("=" * 80)

            # 收集本轮辩论请求
            print("\n🔍 Collecting debate requests from all judges...")
            debate_requests = await self.collect_debate_requests(
                state.evaluations,
                context,
                debate_queue.processed_pairs,  # 传入已处理对，避免重复
            )

            if not debate_requests:
                rounds_without_debates += 1
                print(f"   ✅ No debate requests in round {round_num}")

                # 连续2轮无请求，提前终止
                if rounds_without_debates >= 2:
                    print(
                        "   🏁 Early termination: No debates for 2 consecutive rounds"
                    )
                    break

                # 达到上限也停止
                if round_num >= self.max_debate_rounds:
                    print(f"   🏁 Max rounds ({self.max_debate_rounds}) reached")
                    break

                continue

            # 重置无辩论计数器
            rounds_without_debates = 0

            # 将请求加入队列
            total_added = 0
            for initiator_id, targets in debate_requests.items():
                for target_info in targets:
                    added = debate_queue.add_request(
                        initiator_id,
                        target_info["target_id"],
                        target_info["dispute_point"],
                    )
                    if added:
                        total_added += 1

            print(f"   📋 Added {total_added} new debates to queue")

            # FIFO 顺序执行本轮所有辩论
            print("\n⚖️ Executing Sequential Debates...")
            round_debates = await self.run_sequential_debates(
                state.evaluations, context, debate_queue
            )

            all_debates.extend(round_debates)

            # 应用辩论结果（更新评估分数）
            if round_debates:
                state.evaluations = self._apply_debate_results(
                    state.evaluations, round_debates
                )
                print(
                    f"\n   ✅ Round {round_num} completed: {len(round_debates)} debates"
                )
                print("\n   📋 Updated Evaluation Results:")
                self._print_evaluations(state.evaluations)

        state.debates = all_debates

        if all_debates:
            print(f"\n📊 Total debates across all rounds: {len(all_debates)}")
            self._print_debates(all_debates)
        else:
            print("\n✅ No debates occurred - all judges in agreement")

        # Phase 4: 准备匿名投票选项
        print("\n🎭 Phase 4: Preparing Anonymous Voting...")
        state.anonymized_options, state.option_mapping = self._prepare_voting_options(
            state.evaluations, context
        )
        print(
            f"   Created {len(state.anonymized_options)} anonymous options for voting."
        )

        # Phase 5: 执行投票（人类通过Studio参与）
        print("\n🗳️ Phase 5: Anonymous Voting...")
        state.vote_result = await self.run_anonymous_voting(state)
        if state.vote_result:
            print(
                f"   Winner: {state.vote_result.winner_author} ({state.vote_result.winner_option})"
            )

        # Phase 6: 计算权重和最终分数
        print("\n📊 Phase 6: Calculating Weighted Score...")
        state.weights = self._calculate_weights(state)
        state.final_score = self._calculate_final_score(state)
        print(f"   Final Weighted Score: {state.final_score:.2f}")

        # Phase 7: 生成最终报告
        print("\n📝 Phase 7: Generating Final Report...")
        state.final_report = await self.generate_final_report(state)

        return state

    async def run_initial_evaluation(
        self, context: EvaluationContext
    ) -> List[JudgeEvaluation]:
        """
        Phase 1: 所有法官独立并行初评

        所有法官同时进行评估，互相看不到对方的评分，确保评估的独立性和公平性
        """
        import asyncio

        task_prompt = build_evaluation_prompt(context)
        judge_order = ["Logic", "Expression", "Utility", "Moral"]

        # 定义单个法官的评估任务
        async def evaluate_single_judge(judge_id: str) -> JudgeEvaluation:
            judge = self.all_judges[judge_id]
            print(f"   Evaluating with {judge_id}_Judge...")

            # 调用法官 - 使用结构化输出
            response = await judge(
                Msg("user", task_prompt, "user"),
                structured_model=JudgeOutputModel,
            )

            # 从metadata中提取结构化数据
            parsed = response.metadata if response.metadata else {}

            # 构建评估结果（初评阶段不包含辩论请求）
            eval_result = JudgeEvaluation(
                judge_id=judge_id,
                role=parsed.get("role", self.judge_roles.get(judge_id, judge_id)),
                score=parsed.get("score", 50),
                reason=parsed.get("reason", "No reason provided"),
                metadata=parsed,
                dispute_to=None,  # 初评阶段不发起辩论
                dispute_point=None,
            )

            print(f"      → Score: {eval_result.score}")
            return eval_result

        # 并行执行所有法官的评估
        evaluation_tasks = [evaluate_single_judge(jid) for jid in judge_order]
        evaluations = await asyncio.gather(*evaluation_tasks)

        return list(evaluations)

    async def collect_debate_requests(
        self,
        evaluations: List[JudgeEvaluation],
        context: EvaluationContext,
        processed_pairs: Optional[Set[Tuple[str, str]]] = None,
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Phase 2: 展示所有评估结果，收集辩论请求

        让每个法官看到其他3个法官的评分和理由，然后决定是否要发起辩论

        Args:
            evaluations: 当前评估结果
            context: 评估上下文
            processed_pairs: 已完成的辩论对（用于去重，避免重复辩论）

        Returns:
            Dict mapping initiator_id -> [{"target_id": str, "dispute_point": str}, ...]
            例如: {"Logic": [{"target_id": "Expression", "dispute_point": "..."}], ...}
        """
        import asyncio

        if processed_pairs is None:
            processed_pairs = set()

        debate_requests = {}

        # 构建辩论请求的prompt
        def build_debate_request_prompt(my_judge_id: str) -> str:
            my_eval = next(e for e in evaluations if e.judge_id == my_judge_id)

            # Show other 3 judges' evaluations
            others_text = []
            for eval in evaluations:
                if eval.judge_id != my_judge_id:
                    others_text.append(
                        f"- **{eval.role} ({eval.judge_id})**: {eval.score} points\n"
                        f"  Reason: {eval.reason}"
                    )

            return f"""# Review Other Judges' Evaluations

## Your Initial Evaluation
- Role: {my_eval.role}
- Score: {my_eval.score} points
- Reason: {my_eval.reason}

## Other Judges' Evaluations
{chr(10).join(others_text)}

## Task
Please carefully review the evaluations from other judges. If you have significant disagreements (e.g., large score difference, conflicting basic reasoning, obvious oversight in evaluation perspective), you can request a debate with that judge.

You can initiate debate requests with multiple judges, or none at all. If you agree with all other judges' evaluations, simply provide an empty list.

## Required Output Fields
The system will guide you to provide structured output. You must include:
- debate_requests: A list of debate requests. Each request should contain:
  - target_judge: The judge ID you want to debate with (e.g., "Logic", "Expression", "Utility", "Moral")
  - dispute_point: Your specific point of disagreement

If you have no objections, provide an empty debate_requests list.
"""

        # 并行收集所有法官的辩论请求
        async def get_judge_debate_requests(judge_id: str):
            judge = self.all_judges[judge_id]
            prompt = build_debate_request_prompt(judge_id)

            print(f"   {judge_id} reviewing other judges' evaluations...")

            response = await judge(
                Msg("user", prompt, "user"),
                structured_model=DebateRequestModel,
            )

            parsed = response.metadata if response.metadata else {}
            requests = parsed.get("debate_requests", [])

            # 提取并规范化目标法官（添加去重检查）
            targets = []
            for req in requests:
                target = req.get("target_judge", "")
                # 规范化目标名称
                for key in self.all_judges.keys():
                    if key.lower() in target.lower():
                        # 检查是否已处理过这对
                        sorted_pair = sorted([judge_id, key])
                        pair: Tuple[str, str] = (sorted_pair[0], sorted_pair[1])
                        if pair not in processed_pairs:
                            targets.append(
                                {
                                    "target_id": key,
                                    "dispute_point": req.get("dispute_point", ""),
                                }
                            )
                        break

            return judge_id, targets

        # 并行收集所有法官的请求
        judge_order = ["Logic", "Expression", "Utility", "Moral"]
        request_tasks = [get_judge_debate_requests(jid) for jid in judge_order]
        results = await asyncio.gather(*request_tasks)

        # 构建辩论请求字典
        for judge_id, targets in results:
            if targets:
                debate_requests[judge_id] = targets
                target_names = [t["target_id"] for t in targets]
                print(
                    f"   🔥 {judge_id} requests debate with: {', '.join(target_names)}"
                )

        if not debate_requests:
            print("   ✅ All judges have no objections")

        return debate_requests

    async def run_sequential_debates(
        self,
        evaluations: List[JudgeEvaluation],
        context: EvaluationContext,
        debate_queue: DebateQueue,
    ) -> List[DebateRecord]:
        """
        Phase 3: 顺序执行辩论队列（FIFO，非并发）

        设计理念：
        - FIFO 顺序：先请求的辩论先执行
        - 非并发：每次只执行一场辩论，确保分数更新可被后续辩论看到
        - 自动去重：通过 DebateQueue 管理

        Args:
            evaluations: 当前评估结果（会被动态更新）
            context: 评估上下文
            debate_queue: 辩论队列管理器

        Returns:
            本轮完成的辩论记录列表
        """
        debates: List[DebateRecord] = []
        total_debates = debate_queue.pending_count()

        if total_debates == 0:
            return debates

        print(f"   📋 Queue: {total_debates} debates pending")

        debate_num = 0
        while True:
            next_debate = debate_queue.get_next_debate()
            if not next_debate:
                break

            debate_num += 1
            initiator_id, target_id, dispute_point = next_debate

            print(
                f"\n   🔥 [{debate_num}/{total_debates}] Debate: {initiator_id} vs {target_id}"
            )
            print(f"      Dispute: {dispute_point[:80]}...")

            # 获取最新评估分数（可能被之前的辩论更新）
            initiator_eval = next(e for e in evaluations if e.judge_id == initiator_id)
            target_eval = next(e for e in evaluations if e.judge_id == target_id)

            print(
                f"      Current scores: {initiator_id}={initiator_eval.score}, "
                f"{target_id}={target_eval.score}"
            )

            # 执行辩论
            debate_record = await self._run_single_debate(
                initiator_id=initiator_id,
                initiator_score=initiator_eval.score,
                initiator_reason=initiator_eval.reason,
                target_id=target_id,
                target_score=target_eval.score,
                target_reason=target_eval.reason,
                dispute_point=dispute_point,
            )

            if debate_record:
                debates.append(debate_record)
                debate_queue.mark_completed(initiator_id, target_id)

                # 打印结果（带变化标记）
                init_change = (
                    debate_record.initiator_new_score
                    - debate_record.initiator_original_score
                )
                target_change = (
                    debate_record.target_new_score - debate_record.target_original_score
                )

                init_status = (
                    "unchanged"
                    if debate_record.initiator_kept_original
                    else f"{init_change:+d}"
                )
                target_status = (
                    "unchanged"
                    if debate_record.target_kept_original
                    else f"{target_change:+d}"
                )

                print(
                    f"      Result: {initiator_id} {debate_record.initiator_original_score}→"
                    f"{debate_record.initiator_new_score} ({init_status}), "
                    f"{target_id} {debate_record.target_original_score}→"
                    f"{debate_record.target_new_score} ({target_status})"
                )

                # 立即更新 evaluations（让后续辩论看到最新分数）
                for eval in evaluations:
                    if (
                        eval.judge_id == initiator_id
                        and not debate_record.initiator_kept_original
                    ):
                        eval.score = debate_record.initiator_new_score
                        eval.reason = debate_record.initiator_new_reason
                    elif (
                        eval.judge_id == target_id
                        and not debate_record.target_kept_original
                    ):
                        eval.score = debate_record.target_new_score
                        eval.reason = debate_record.target_new_reason

        print(f"\n   ✅ Completed {len(debates)} debates in this round")
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
            # 发起方陈述 - 使用结构化输出
            init_response = await initiator(
                Msg("user", initiator_prompt, "user"),
                structured_model=DebateOutputModel,
            )
            init_parsed = init_response.metadata if init_response.metadata else {}

            # 目标方回应 - 使用结构化输出
            target_response = await target(
                Msg("user", target_prompt, "user"),
                structured_model=DebateOutputModel,
            )
            target_parsed = target_response.metadata if target_response.metadata else {}

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

Provide your vote (e.g., "Option 1") and a brief reason for your choice.
"""

            # 使用结构化输出
            response = await judge(
                Msg("user", judge_vote_prompt, "user"),
                structured_model=VoteOutputModel,
            )
            parsed = response.metadata if response.metadata else {}

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
        """Phase 7: 生成最终报告（包含完整辩论历史）"""

        # 构建评估结果摘要
        evaluations_text = "\n".join(
            [
                f"- {eval.role}: {eval.score}/100\n  Reason: {eval.reason}"
                for eval in state.evaluations
            ]
        )

        # 构建详细的辩论历史
        debates_text = "No debates occurred."
        if state.debates:
            debates_parts = []
            for i, debate in enumerate(state.debates, 1):
                debate_section = f"""
### Debate {i}: {debate.initiator_id} vs {debate.target_id}

**Dispute Point:** {debate.dispute_point}

**{debate.initiator_id} (Initiator):**
- Original Score: {debate.initiator_original_score}
- New Score: {debate.initiator_new_score}
- Score Changed: {"Yes" if not debate.initiator_kept_original else "No"}
- Updated Reasoning: {debate.initiator_new_reason[:300]}{"..." if len(debate.initiator_new_reason) > 300 else ""}

**{debate.target_id} (Respondent):**
- Original Score: {debate.target_original_score}
- New Score: {debate.target_new_score}
- Score Changed: {"Yes" if not debate.target_kept_original else "No"}
- Updated Reasoning: {debate.target_new_reason[:300]}{"..." if len(debate.target_new_reason) > 300 else ""}

**Debate Outcome:**
- {debate.initiator_id}: {debate.initiator_original_score} → {debate.initiator_new_score} ({"+" if debate.initiator_new_score > debate.initiator_original_score else ""}{debate.initiator_new_score - debate.initiator_original_score})
- {debate.target_id}: {debate.target_original_score} → {debate.target_new_score} ({"+" if debate.target_new_score > debate.target_original_score else ""}{debate.target_new_score - debate.target_original_score})
"""
                debates_parts.append(debate_section)

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

## AI Judge Final Evaluation Results (After Debates)
{evaluations_text}

## Human Evaluation
- Score: {state.context.human_score}/100
- Reason: {state.context.human_reason}
- Competency Score: {state.context.human_competency_score}

## Debate Records (Detailed)
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
3. **Controversy Highlights**: Key points of contention and debate outcomes (if debates occurred)
   - Summarize what each debate was about
   - Explain how judges changed (or didn't change) their positions
   - Highlight any consensus or persistent disagreements
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

            # 显示额外的metadata（如果存在）
            extra = eval.metadata.get("extra_metadata", {})
            if extra:
                extra_items = []
                for k, v in extra.items():
                    if isinstance(v, list) and not v:  # 空列表
                        continue
                    extra_items.append(f"{k}: {v}")
                if extra_items:
                    print(f"     ({', '.join(extra_items)})")

            if eval.dispute_to:
                print(f"     ⚔️ Disputes: {eval.dispute_to}")

    def _print_debates(self, debates: List[DebateRecord]):
        """打印辩论记录摘要"""
        if not debates:
            return

        print(f"\n   ⚖️ Debate Summary: {len(debates)} debate(s) occurred")
        for i, debate in enumerate(debates, 1):
            init_change = debate.initiator_new_score - debate.initiator_original_score
            target_change = debate.target_new_score - debate.target_original_score

            init_status = (
                "kept"
                if debate.initiator_kept_original
                else f"changed {init_change:+d}"
            )
            target_status = (
                "kept" if debate.target_kept_original else f"changed {target_change:+d}"
            )

            print(f"   [{i}] {debate.initiator_id} vs {debate.target_id}")
            print(
                f"       {debate.initiator_id}: {debate.initiator_original_score}→"
                f"{debate.initiator_new_score} ({init_status})"
            )
            print(
                f"       {debate.target_id}: {debate.target_original_score}→"
                f"{debate.target_new_score} ({target_status})"
            )
            print(f"       Dispute: {debate.dispute_point[:60]}...")


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
