"""
AgentScope-based Jury Evaluation System

This module replaces the LangGraph-based implementation with AgentScope framework.
It provides multi-model collaborative evaluation with debate and voting mechanisms.
"""

import json
import random
import statistics
import os
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

import agentscope
from agentscope.agent import AgentBase
from agentscope.message import Msg

from src.llm_provider import LLMProvider
from src.agents import (
    JUDGE_AUTHORITY_PROMPT,
    JURY_EVALUATION_PROMPT,
    DEBATE_PROMPT,
    BLIND_VOTE_PROMPT,
    SYNTHESIS_PROMPT
)
from src.utils import (
    calculate_weighted_score,
    check_debate_condition,
    anonymize_options,
    parse_json_output
)

# Initialize AgentScope with optional Studio connection
STUDIO_URL = os.getenv("AGENTSCOPE_STUDIO_URL", None)
if STUDIO_URL:
    agentscope.init(
        project="Jury-LLM",
        studio_url=STUDIO_URL
    )
    print(f"✅ AgentScope Studio connected: {STUDIO_URL}")



# ============================================================================
# Agent Definitions
# ============================================================================

class JudgeAgent(AgentBase):
    """Judge agent for calculating human authority weight and synthesizing final report"""
    
    def __init__(self, name: str, model_name: str, llm_provider: LLMProvider):
        super().__init__()
        self.name = name
        self.model_name = model_name
        self.llm = llm_provider
        
    def calculate_human_weight(self, human_bio: str, topic: str) -> Tuple[float, str]:
        """Calculate human authority weight based on bio"""
        prompt = JUDGE_AUTHORITY_PROMPT.format(
            human_bio=human_bio,
            topic=topic
        )
        
        response = self.llm.generate(self.model_name, [{"role": "user", "content": prompt}])
        data = parse_json_output(response)
        
        weight = data.get("weight", 1.0)
        reasoning = data.get("reasoning", "No reasoning provided")
        
        return float(weight), reasoning
    
    def synthesize_report(self, state: Dict) -> str:
        """Generate final comprehensive report"""
        # Prepare summary data
        summary_data = f"Human Score: {state['human_score']} (Weight: {state['human_weight']:.2f})\n"
        for model_name, data in state['model_outputs'].items():
            summary_data += f"{model_name}: {data['score']} (Weight: {data['weight']:.2f})\n"
        
        summary_data += f"\n--- Voting Results ---\n"
        for voter, choice in state['votes'].items():
            real_author = state['anonymized_mapping'].get(choice, "Unknown")
            summary_data += f"{voter} voted for: {real_author}\n"
        
        prompt = SYNTHESIS_PROMPT.format(
            topic=state['topic'],
            summary_data=summary_data
        )
        
        response = self.llm.generate(self.model_name, [{"role": "user", "content": prompt}])
        return response


class JuryAgent(AgentBase):
    """Jury agent for evaluating the target text"""
    
    def __init__(self, name: str, model_name: str, llm_provider: LLMProvider):
        super().__init__()
        self.name = name
        self.model_name = model_name
        self.llm = llm_provider
        self.score = None
        self.reason = None
        self.weight = 1.0
        self.history = []
        
    def evaluate(self, topic: str, rubrics: str = "") -> Dict:
        """Initial evaluation of the topic"""
        # Include rubrics in prompt if available
        if rubrics:
            prompt = JURY_EVALUATION_PROMPT.format(topic=topic)
            prompt += f"\n\n# Evaluation Criteria\nPlease use the following criteria to guide your evaluation:\n{rubrics}"
        else:
            prompt = JURY_EVALUATION_PROMPT.format(topic=topic)
        
        response = self.llm.generate(self.model_name, [{"role": "user", "content": prompt}])
        data = parse_json_output(response)
        
        self.score = data.get("score", 50)
        self.reason = data.get("reason", "No reason provided")
        self.history.append({"action": "initial_eval", "score": self.score, "reason": self.reason})
        
        return {"score": self.score, "reason": self.reason}
    
    def debate(self, topic: str, opponent_score: float, opponent_reason: str) -> Dict:
        """Reconsider position based on opponent's view"""
        prompt = DEBATE_PROMPT.format(
            topic=topic,
            my_score=self.score,
            opponent_score=opponent_score,
            opponent_reason=opponent_reason
        )
        
        response = self.llm.generate(self.model_name, [{"role": "user", "content": prompt}])
        data = parse_json_output(response)
        
        old_score = self.score
        self.score = data.get("score", old_score)
        self.reason = data.get("reason", self.reason)
        response_to_opponent = data.get("response_to_opponent", "")
        
        self.history.append({
            "action": "debate",
            "old_score": old_score,
            "new_score": self.score,
            "response": response_to_opponent
        })
        
        return {
            "score": self.score,
            "reason": self.reason,
            "response_to_opponent": response_to_opponent
        }
    
    def vote(self, topic: str, anonymized_options: Dict[str, str]) -> str:
        """Vote for the best anonymous evaluation"""
        options_text = "\n".join([f"{k}: {v}" for k, v in anonymized_options.items()])
        prompt = BLIND_VOTE_PROMPT.format(
            topic=topic,
            anonymous_evaluations=options_text
        )
        
        response = self.llm.generate(self.model_name, [{"role": "user", "content": prompt}])
        data = parse_json_output(response)
        
        selected = data.get("selected_option_id", "")
        return selected


# ============================================================================
# Jury Evaluation System
# ============================================================================

@dataclass
class JuryState:
    """State container for the jury evaluation process"""
    topic: str
    human_bio: str
    human_score: float
    human_reason: str
    human_weight: float = 1.0
    
    evaluation_rubrics: str = ""
    
    model_outputs: Dict[str, Dict] = field(default_factory=dict)
    
    debate_round: int = 0
    debate_logs: List[str] = field(default_factory=list)
    
    anonymized_reasons: Dict[str, str] = field(default_factory=dict)
    anonymized_mapping: Dict[str, str] = field(default_factory=dict)
    
    votes: Dict[str, str] = field(default_factory=dict)
    
    final_verdict: str = ""


class JuryEvaluationSystem:
    """
    Main orchestrator for the jury evaluation process using AgentScope.
    
    This replaces the LangGraph-based implementation with a more flexible
    AgentScope-based approach.
    """
    
    def __init__(self, config: Dict):
        """
        Initialize the jury system.
        
        Args:
            config: Configuration dict containing:
                - judge_model: Model name for the judge
                - jury_models: List of model names for jury members
                - system_settings: Dict with debate_threshold and max_debate_rounds
        """
        self.config = config
        self.llm_provider = LLMProvider()
        
        # Extract config
        self.judge_model_name = config['judge_model']
        self.jury_model_names = config['jury_models']
        self.debate_threshold = config['system_settings']['debate_threshold']
        self.max_debate_rounds = config['system_settings']['max_debate_rounds']
        
        # Initialize agents
        self._init_agents()
        
    def _init_agents(self):
        """Initialize all agents"""
        # Initialize judge
        self.judge = JudgeAgent(
            name="Judge",
            model_name=self.judge_model_name,
            llm_provider=self.llm_provider
        )
        
        # Initialize jury agents
        self.jury_agents = []
        for i, model_name in enumerate(self.jury_model_names):
            agent = JuryAgent(
                name=f"Juror_{i+1}_{model_name}",
                model_name=model_name,
                llm_provider=self.llm_provider
            )
            self.jury_agents.append(agent)
    
    def run(self, topic: str, human_score: float, human_reason: str, 
            human_bio: str = "Assessed via Qualification Exam",
            rubrics: str = "") -> Dict:
        """
        Run the jury evaluation up to the point where human voting is needed.
        
        Args:
            topic: The target text to evaluate
            human_score: Human's evaluation score
            human_reason: Human's evaluation reason
            human_bio: Human's bio/credentials
            rubrics: Evaluation criteria/rubrics
            
        Returns:
            Dict containing status, anonymized options, and state for continuation
        """
        # Initialize state
        state = JuryState(
            topic=topic,
            human_bio=human_bio,
            human_score=human_score,
            human_reason=human_reason,
            evaluation_rubrics=rubrics
        )
        
        print("=" * 60)
        print("🏛️  JURY EVALUATION SYSTEM (AgentScope)")
        print("=" * 60)
        
        # Step 1: Calculate human authority weight
        print("\n📊 Step 1: Calculating Human Authority Weight...")
        weight, reasoning = self.judge.calculate_human_weight(human_bio, topic)
        state.human_weight = weight
        print(f"   Human Weight: {weight:.2f}")
        print(f"   Reasoning: {reasoning}")
        
        # Step 2: Initial evaluation by all jury members
        print("\n⚖️  Step 2: Initial Jury Evaluation...")
        for agent in self.jury_agents:
            print(f"   Querying {agent.name}...")
            result = agent.evaluate(topic, rubrics)
            state.model_outputs[agent.name] = {
                "score": result["score"],
                "reason": result["reason"],
                "weight": 1.0,
                "history": agent.history.copy()
            }
            print(f"   → Score: {result['score']}")
        
        # Step 3: Check if debate is needed
        all_scores = [state.human_score] + [agent.score for agent in self.jury_agents]
        
        while state.debate_round < self.max_debate_rounds:
            if not check_debate_condition(all_scores, self.debate_threshold):
                print(f"\n✅ Consensus reached (std dev below {self.debate_threshold}). Skipping debate.")
                break
            
            print(f"\n🗣️  Step 3: Debate Round {state.debate_round + 1}...")
            avg_score = sum(all_scores) / len(all_scores)
            
            for agent in self.jury_agents:
                if abs(agent.score - avg_score) > 10:
                    print(f"   {agent.name} reconsidering (score {agent.score} vs avg {avg_score:.1f})...")
                    result = agent.debate(
                        topic=topic,
                        opponent_score=avg_score,
                        opponent_reason=f"The consensus seems to differ from your view."
                    )
                    
                    old_score = state.model_outputs[agent.name]["score"]
                    state.model_outputs[agent.name]["score"] = result["score"]
                    state.model_outputs[agent.name]["reason"] = result["reason"]
                    
                    log = f"{agent.name}: Adjusted score from {old_score} to {result['score']}. Response: {result['response_to_opponent']}"
                    state.debate_logs.append(log)
                    print(f"   → New score: {result['score']}")
            
            state.debate_round += 1
            all_scores = [state.human_score] + [agent.score for agent in self.jury_agents]
        
        # Step 4: Prepare blind voting
        print("\n🎭 Step 4: Preparing Blind Vote...")
        options = {}
        options['human'] = f"Score: {state.human_score}. Reason: {state.human_reason}"
        for agent in self.jury_agents:
            options[agent.name] = f"Score: {agent.score}. Reason: {agent.reason}"
        
        anon_options, mapping = anonymize_options(options)
        state.anonymized_reasons = anon_options
        state.anonymized_mapping = mapping
        
        print(f"   Created {len(anon_options)} anonymous options for voting.")
        
        # Return state for human voting
        return {
            "status": "waiting_for_human_vote",
            "anonymized_options": anon_options,
            "state": state
        }
    
    def finalize(self, human_vote: str, state: JuryState) -> str:
        """
        Complete the evaluation after human voting.
        
        Args:
            human_vote: The option ID selected by human
            state: The state object from run()
            
        Returns:
            Final evaluation report in markdown format
        """
        print("\n" + "=" * 60)
        print("🎯 FINALIZING JURY EVALUATION")
        print("=" * 60)
        
        # Record human vote
        state.votes['human'] = human_vote
        print(f"\n✅ Human voted for: {human_vote}")
        
        # Step 5: Model voting
        print("\n🗳️  Step 5: Model Voting...")
        for agent in self.jury_agents:
            print(f"   {agent.name} voting...")
            vote = agent.vote(state.topic, state.anonymized_reasons)
            state.votes[agent.name] = vote
            print(f"   → Voted for: {vote}")
        
        # Step 6: Calculate vote results and boost winner
        print("\n📈 Step 6: Calculating Vote Results...")
        vote_counts = {}
        for voter, choice in state.votes.items():
            if choice:
                real_author = state.anonymized_mapping.get(choice, "Unknown")
                vote_counts[real_author] = vote_counts.get(real_author, 0) + 1
        
        if vote_counts:
            winner = max(vote_counts, key=vote_counts.get)
            print(f"   Winner: {winner} with {vote_counts[winner]} votes")
            
            # Boost winner's weight
            if winner == 'human':
                state.human_weight += 0.5
                print(f"   Human weight boosted to {state.human_weight:.2f}")
            else:
                for agent in self.jury_agents:
                    if agent.name == winner:
                        agent.weight += 0.5
                        state.model_outputs[winner]['weight'] += 0.5
                        print(f"   {winner} weight boosted to {agent.weight:.2f}")
        
        # Step 7: Generate final report
        print("\n📝 Step 7: Generating Final Report...")
        final_report = self.judge.synthesize_report(state.__dict__)
        state.final_verdict = final_report
        
        print("\n" + "=" * 60)
        print("✨ EVALUATION COMPLETE")
        print("=" * 60)
        
        return final_report
