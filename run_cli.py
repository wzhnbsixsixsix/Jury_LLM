import asyncio
import os
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Import AgentScope-based jury system
from src.agentscope_jury import JuryEvaluationSystem, EvaluationContext


def main():
    """
    CLI interface for Jury LLM using AgentScope.

    This replaces the old LangGraph-based CLI.
    """
    # Load configuration
    config_path = os.path.join(os.path.dirname(__file__), "config/jury_config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Initialize jury system
    jury_system = JuryEvaluationSystem(config)

    # Sample evaluation data (can be modified or replaced with argparse)
    target_text = "AI is transforming software engineering by automating repetitive tasks, enhancing code quality through intelligent suggestions, and accelerating development cycles. However, it also introduces challenges in maintainability, over-reliance on AI-generated code, and potential security vulnerabilities."
    evaluation_purpose = "Evaluate the impact of AI on software engineering."
    human_competency_score = 85.0  # Senior developer with high competency
    human_score = 70
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

    # Create EvaluationContext
    context = EvaluationContext(
        target_text=target_text,
        evaluation_purpose=evaluation_purpose,
        human_competency_score=human_competency_score,
        evaluation_rubrics=rubrics,
        human_score=human_score,
        human_reason=human_reason,
    )

    print("=" * 70)
    print("JURY LLM - CLI MODE (AgentScope)")
    print("=" * 70)
    print(f"\nPurpose: {evaluation_purpose}")
    print(f"Human Score: {human_score}")
    print(f"Human Competency: {human_competency_score}")
    print()

    # Run evaluation (async)
    print("Running jury evaluation...")
    state = asyncio.run(jury_system.run(context))

    print("\n" + "=" * 70)
    print("FINAL EVALUATION REPORT")
    print("=" * 70)
    print()
    print(state.final_report if state.final_report else "No report generated.")
    print()
    print(
        f"Final Score: {state.final_score:.2f}"
        if state.final_score
        else "No score calculated."
    )


if __name__ == "__main__":
    main()
