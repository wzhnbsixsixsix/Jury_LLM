import json
import yaml
import os
from typing import Dict, List, TypedDict, Annotated, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage

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
try:
    from langgraph.checkpoint.memory import MemorySaver
    CHECKPOINTER = MemorySaver()
except ImportError:
    from langgraph.checkpoint.sqlite import SqliteSaver
    CHECKPOINTER = SqliteSaver.from_file(os.path.join(os.path.dirname(__file__), "../.langgraph.sqlite"))

# Load Config
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '../config/jury_config.yaml')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = yaml.safe_load(f)

JUDGE_MODEL = CONFIG['judge_model']
JURY_MODELS = CONFIG['jury_models']
DEBATE_THRESHOLD = CONFIG['system_settings']['debate_threshold']
MAX_DEBATE_ROUNDS = CONFIG['system_settings']['max_debate_rounds']

llm = LLMProvider()

class JuryState(TypedDict):
    topic: str
    human_bio: str
    human_score: float
    human_reason: str
    human_weight: float
    
    # Evaluation rubrics/criteria (added for Step 2.5)
    evaluation_rubrics: str
    
    # {model_id: {score, reason, weight, history: []}}
    model_outputs: Dict[str, Any] 
    
    debate_round: int
    debate_logs: List[str]
    
    # {option_id: content}
    anonymized_reasons: Dict[str, str]
    # {option_id: model_id}
    anonymized_mapping: Dict[str, str]
    
    # {voter_id: selected_option_id}
    votes: Dict[str, str]
    
    final_verdict: str

def node_human_authority(state: JuryState) -> Dict:
    """Calculates human weight based on bio."""
    print("--- Node: Human Authority ---")
    prompt = JUDGE_AUTHORITY_PROMPT.format(
        human_bio=state['human_bio'],
        topic=state['topic']
    )
    response = llm.generate(JUDGE_MODEL, [{"role": "user", "content": prompt}])
    data = parse_json_output(response)
    
    return {
        "human_weight": data.get("weight", 1.0)
    }

def node_initial_eval(state: JuryState) -> Dict:
    """Parallel evaluation by all jury models."""
    print("--- Node: Initial Evaluation ---")
    
    # Include rubrics in the evaluation prompt if available
    rubrics = state.get('evaluation_rubrics', '')
    if rubrics:
        prompt = JURY_EVALUATION_PROMPT.format(topic=state['topic']) + f"\n\n# Evaluation Criteria\nPlease use the following criteria to guide your evaluation:\n{rubrics}"
    else:
        prompt = JURY_EVALUATION_PROMPT.format(topic=state['topic'])
    
    outputs = state.get('model_outputs', {})
    
    # Simple sequential loop for demonstration (can be parallelized with ThreadPoolExecutor)
    for model in JURY_MODELS:
        print(f"Querying {model}...")
        response = llm.generate(model, [{"role": "user", "content": prompt}])
        data = parse_json_output(response)
        outputs[model] = {
            "score": data.get("score", 50),
            "reason": data.get("reason", "No reason provided"),
            "weight": 1.0, # Initial weight for models
            "history": []
        }
        
    return {"model_outputs": outputs, "debate_round": 0}

def node_debate_check(state: JuryState) -> str:
    """Conditional edge to check if debate is needed."""
    print("--- Check Debate Condition ---")
    scores = [state['human_score']] + [d['score'] for d in state['model_outputs'].values()]
    
    if state['debate_round'] >= MAX_DEBATE_ROUNDS:
        return "vote"
        
    if check_debate_condition(scores, threshold=DEBATE_THRESHOLD):
        return "debate"
    return "vote"

def node_debate(state: JuryState) -> Dict:
    """Conducts a round of debate."""
    print(f"--- Node: Debate (Round {state['debate_round'] + 1}) ---")
    
    # Identify outliers (simplified: just pick max and min to debate against each other's views)
    # In a full implementation, we might pair them up.
    # Here, we'll just have every model reflect on the "Average" or a specific opposing view.
    # Let's simulate: Find the model furthest from the mean and have them reconsider.
    
    outputs = state['model_outputs']
    scores = [d['score'] for d in outputs.values()]
    avg_score = sum(scores) / len(scores)
    
    debate_logs = state.get('debate_logs', [])
    
    for model, data in outputs.items():
        # If score is far from average, ask to reconsider
        if abs(data['score'] - avg_score) > 10:
            prompt = DEBATE_PROMPT.format(
                topic=state['topic'],
                my_score=data['score'],
                opponent_score=f"Average ({avg_score:.1f})",
                opponent_reason="The consensus seems to differ from your view."
            )
            response = llm.generate(model, [{"role": "user", "content": prompt}])
            new_data = parse_json_output(response)
            
            # Update
            old_score = data['score']
            data['score'] = new_data.get('score', old_score)
            data['reason'] = new_data.get('reason', data['reason'])
            
            log = f"{model}: Adjusted score from {old_score} to {data['score']}. Reason: {new_data.get('response_to_opponent', '')}"
            debate_logs.append(log)
            
    return {
        "model_outputs": outputs, 
        "debate_round": state['debate_round'] + 1,
        "debate_logs": debate_logs
    }

def node_prepare_blind_vote(state: JuryState) -> Dict:
    """Anonymizes options for voting."""
    print("--- Node: Prepare Blind Vote ---")
    options = {}
    
    # Add Human
    options['human'] = f"Score: {state['human_score']}. Reason: {state['human_reason']}"
    
    # Add Models
    for model, data in state['model_outputs'].items():
        options[model] = f"Score: {data['score']}. Reason: {data['reason']}"
        
    anon_options, mapping = anonymize_options(options)
    
    return {
        "anonymized_reasons": anon_options,
        "anonymized_mapping": mapping
    }

def node_model_vote(state: JuryState) -> Dict:
    """Models vote on the best anonymous reason."""
    print("--- Node: Model Vote ---")
    
    options_text = "\n".join([f"{k}: {v}" for k, v in state['anonymized_reasons'].items()])
    prompt = BLIND_VOTE_PROMPT.format(
        topic=state['topic'],
        anonymous_evaluations=options_text
    )
    
    votes = state.get('votes', {})
    
    for model in JURY_MODELS:
        response = llm.generate(model, [{"role": "user", "content": prompt}])
        data = parse_json_output(response)
        votes[model] = data.get("selected_option_id")
        
    return {"votes": votes}

def node_synthesis(state: JuryState) -> Dict:
    """Final synthesis and reporting."""
    print("--- Node: Synthesis ---")
    
    # Calculate votes
    vote_counts = {}
    for voter, choice in state['votes'].items():
        if choice:
            real_author = state['anonymized_mapping'].get(choice, "Unknown")
            vote_counts[real_author] = vote_counts.get(real_author, 0) + 1
            
    # Boost weight of the winner
    winner = max(vote_counts, key=vote_counts.get) if vote_counts else None
    
    if winner and winner in state['model_outputs']:
        state['model_outputs'][winner]['weight'] += 0.5 # Bonus
    elif winner == 'human':
        state['human_weight'] += 0.5
        
    # Prepare summary data
    summary_data = f"Human Score: {state['human_score']} (Weight: {state['human_weight']})\n"
    for model, data in state['model_outputs'].items():
        summary_data += f"{model}: {data['score']} (Weight: {data['weight']})\n"
        
    prompt = SYNTHESIS_PROMPT.format(
        topic=state['topic'],
        summary_data=summary_data
    )
    
    final_verdict = llm.generate(JUDGE_MODEL, [{"role": "user", "content": prompt}])
    
    return {"final_verdict": final_verdict}

# Build Graph
workflow = StateGraph(JuryState)

workflow.add_node("human_authority", node_human_authority)
workflow.add_node("initial_eval", node_initial_eval)
workflow.add_node("debate", node_debate)
workflow.add_node("prepare_vote", node_prepare_blind_vote)
workflow.add_node("model_vote", node_model_vote)
workflow.add_node("synthesis", node_synthesis)

# Define flow
workflow.set_entry_point("human_authority")
workflow.add_edge("human_authority", "initial_eval")

workflow.add_conditional_edges(
    "initial_eval",
    node_debate_check,
    {
        "debate": "debate",
        "vote": "prepare_vote"
    }
)

workflow.add_edge("debate", "initial_eval") # Loop back to check condition again
workflow.add_edge("prepare_vote", "model_vote")
# Note: Human vote happens between prepare_vote and synthesis in the notebook via interrupt
workflow.add_edge("model_vote", "synthesis")
workflow.add_edge("synthesis", END)

# // 始终启用检查点 + 中断点
app = workflow.compile(
    checkpointer=CHECKPOINTER,
    interrupt_before=["model_vote"]
)
