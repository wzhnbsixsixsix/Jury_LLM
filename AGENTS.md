# Agent Guidelines for Jury LLM

Coding standards and workflows for AI agents working on the Jury LLM project.

## Project Overview

**Type:** Multi-agent evaluation system using AgentScope for coordinated judge agents  
**Stack:** Python 3.9+, AgentScope, LiteLLM, Gradio, Pydantic, DashScope (Alibaba Qwen)  
**Architecture:** Specialized judges (Logic, Expression, Utility, Moral) → Debate → Anonymous Voting → Weighted Scoring

## Quick Commands

### Setup & Run
```bash
# Setup environment
python3 -m venv juryenv && source juryenv/bin/activate
pip install -r requirements.txt
echo "DASHSCOPE_API_KEY=your_key" > .env  # Or OPENROUTER_API_KEY

# Run
jupyter notebook notebooks/interactive_lab.ipynb  # Primary UI
python run_cli.py                                  # CLI mode
python examples/mutiagent_debate.py               # Example
```

### Testing (Not configured yet)
```bash
pip install pytest pytest-asyncio pytest-cov
pytest tests/                              # All tests
pytest tests/test_agents.py -v             # Single file
pytest tests/test_agents.py::test_name -v  # Single test
pytest --cov=src --cov-report=html         # With coverage
```

### Linting & Formatting
```bash
pip install ruff black isort mypy
ruff check src/ && ruff format src/  # Lint + format
black src/                            # Alternative formatter
isort src/                            # Sort imports
mypy src/                             # Type check
```

## Code Style Guidelines

### Project Structure
```
src/
├── agentscope_jury.py  # Core evaluation system (1355 lines)
├── agents.py           # Agent prompt templates
├── llm_provider.py     # LLM API wrapper
├── qualification.py    # Human competency assessment
├── rubrics.py          # Evaluation criteria generation
└── utils.py            # Utility functions (scoring, anonymization)
```

### Naming Conventions
- **Files:** `snake_case.py` (e.g., `agentscope_jury.py`)
- **Classes:** `PascalCase` (e.g., `JuryEvaluationSystem`)
- **Functions:** `snake_case` (e.g., `run_initial_evaluation`)
- **Constants:** `UPPER_SNAKE_CASE` (e.g., `SYS_PROMPT_LOGIC`)
- **Private:** `_leading_underscore` (e.g., `_create_judges`)

### Import Order
```python
# 1. Standard library
import json
from typing import Dict, List, Any, Optional

# 2. Third-party
from pydantic import BaseModel, Field
import agentscope
from agentscope.agent import ReActAgent
from agentscope.message import Msg

# 3. Local
from .utils import calculate_weighted_score
```

### Type Hints (Required for public APIs)
```python
def calculate_weighted_score(scores: List[Dict[str, Any]]) -> float:
    """Calculate weighted average score."""
    pass

async def run(self, context: EvaluationContext) -> JuryState:
    pass
```

### Async/Await Pattern (Required for AgentScope)
```python
# Correct ✓
async def evaluate(self, judge: ReActAgent, prompt: str):
    response = await judge(Msg("user", prompt, "user"))
    return response

# Wrong ✗ - Missing await
async def evaluate(self, judge: ReActAgent, prompt: str):
    response = judge(Msg("user", prompt, "user"))
```

### Multi-Agent Communication (MsgHub)
```python
# Two-party debate (MUST use async with in async functions)
async with MsgHub(participants=[judge1, judge2]) as hub:
    await judge1(Msg("user", debate_prompt, "user"))
    await judge2(Msg("user", debate_prompt, "user"))

# Broadcasting to all judges
async with MsgHub(participants=all_judges) as hub:
    for judge in all_judges:
        await judge(Msg("user", evaluation_prompt, "user"))
```

### Pydantic Models (For LLM output validation)
```python
class JudgeOutputModel(BaseModel):
    role: str = Field(description="Judge role name")
    score: int = Field(ge=0, le=100, description="Score 0-100")
    reasoning: str = Field(description="Detailed reasoning")
    dispute_to: Optional[str] = Field(default=None)
```

### Configuration Management (YAML-driven)
```python
import yaml

# Good ✓
config = yaml.safe_load(open("config/jury_config.yaml"))
judge_model = config.get("judge_model", "qwen-max")
debate_threshold = config["system_settings"]["debate_threshold"]

# Bad ✗
judge_model = "qwen-max"  # Don't hardcode
```

### Error Handling (JSON parsing from LLM)
```python
def parse_json_output(output: str) -> Dict[str, Any]:
    """Parse JSON from LLM output, handle markdown code blocks."""
    import re
    cleaned = re.sub(r"```json\n|\n```", "", output).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return {}  # Safe fallback
```

### Documentation Style
```python
# Use Google/NumPy style docstrings for public APIs
def anonymize_options(options: Dict[str, str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Anonymize a dictionary of {model_id: content}.
    
    Returns:
        - anonymized_options: {option_id: content}
        - mapping: {option_id: model_id}
    """
    pass

# Use section headers in long files
# ============================================================================
# SECTION 1: System Prompts
# ============================================================================
```

## Development Workflow

### Before Making Changes
- Read existing code in affected module
- Check `config/jury_config.yaml` and `.env` files
- Understand agent workflow (README.md lines 45-57)

### When Adding Features
- Update prompts in `agents.py` for new judge roles
- Use Pydantic models for structured outputs
- Maintain async patterns throughout
- Test with real LLM calls in Jupyter notebook first

### Code Review Checklist
- [ ] Type hints on public functions
- [ ] Async/await used correctly
- [ ] No hardcoded API keys or model names
- [ ] JSON parsing has error handling
- [ ] Docstrings added/updated
- [ ] Config-driven where possible

## Known Issues & Improvements

From README.md development suggestions:
- **Concurrency:** Initial evaluations are sequential; consider parallel execution
- **JSON parsing:** Implement retry logic when models return invalid JSON
- **Weighted scoring:** Migrate final calculation from prompts to code
- **Debate strategy:** Extend beyond pairwise to group debates

## Additional Resources

See comprehensive Chinese README.md for:
- Detailed architecture (lines 208-624)
- Agent design specifications
- FAQ (lines 59-64)
