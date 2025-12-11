import random
import statistics
from typing import List, Dict, Any, Tuple

def calculate_weighted_score(scores: List[Dict[str, Any]]) -> float:
    """
    Calculate the weighted average score.
    Each item in scores should be a dict with 'score' and 'weight'.
    """
    total_weighted_score = 0.0
    total_weight = 0.0

    for item in scores:
        score = float(item.get('score', 0))
        weight = float(item.get('weight', 1.0))
        total_weighted_score += score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0
    
    return total_weighted_score / total_weight

def check_debate_condition(scores: List[float], threshold: float = 15.0) -> bool:
    """
    Check if the standard deviation of scores exceeds the threshold.
    """
    if len(scores) < 2:
        return False
    
    std_dev = statistics.stdev(scores)
    return std_dev > threshold

def anonymize_options(options: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Anonymize a dictionary of {model_id: content}.
    Returns:
        - anonymized_options: {option_id: content}
        - mapping: {option_id: model_id}
    """
    keys = list(options.keys())
    random.shuffle(keys)
    
    anonymized_options = {}
    mapping = {}
    
    for i, key in enumerate(keys):
        option_id = f"Option {i+1}"
        anonymized_options[option_id] = options[key]
        mapping[option_id] = key
        
    return anonymized_options, mapping

def parse_json_output(output: str) -> Dict[str, Any]:
    """
    Helper to parse JSON from LLM output, handling potential markdown code blocks.
    """
    import json
    import re

    # Remove markdown code blocks if present
    cleaned = re.sub(r"```json\n|\n```", "", output).strip()
    cleaned = re.sub(r"```\n|\n```", "", cleaned).strip()
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback or simple extraction could go here
        return {}
