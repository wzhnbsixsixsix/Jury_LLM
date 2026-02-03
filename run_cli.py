import os
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Import AgentScope-based jury system
from src.agentscope_jury import JuryEvaluationSystem

def main():
    """
    CLI interface for Jury LLM using AgentScope.
    
    This replaces the old LangGraph-based CLI.
    """
    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), "config/jury_config.yaml")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Initialize jury system
    jury_system = JuryEvaluationSystem(config)
    
    # Sample evaluation data (can be modified or replaced with argparse)
    topic = "Evaluate the impact of AI on software engineering."
    human_bio = "Senior Python Developer, 10 years exp."
    human_score = 70.0
    human_reason = "Strong productivity gains, but risks in maintainability."
    rubrics = """
# Evaluation Criteria

## 1. Accuracy (40 points)
- Factual correctness
- Evidence-based claims

## 2. Depth of Analysis (30 points)
- Comprehensive coverage
- Nuanced understanding

## 3. Clarity (30 points)
- Clear communication
- Well-structured arguments
"""
    
    print("=" * 70)
    print("JURY LLM - CLI MODE (AgentScope)")
    print("=" * 70)
    print(f"\nTopic: {topic}")
    print(f"Human Score: {human_score}")
    print(f"Human Bio: {human_bio}")
    print()
    
    # Run evaluation up to voting point
    print("Running jury evaluation...")
    result = jury_system.run(
        topic=topic,
        human_score=human_score,
        human_reason=human_reason,
        human_bio=human_bio,
        rubrics=rubrics
    )
    
    # Auto-select first option for CLI mode
    anonymized_options = result['anonymized_options']
    selected_option = list(anonymized_options.keys())[0]
    
    print(f"\n[CLI Auto-Vote] Selected: {selected_option}")
    
    # Finalize evaluation
    final_report = jury_system.finalize(
        human_vote=selected_option,
        state=result['state']
    )
    
    print("\n" + "=" * 70)
    print("FINAL EVALUATION REPORT")
    print("=" * 70)
    print()
    print(final_report)
    print()

if __name__ == "__main__":
    main()