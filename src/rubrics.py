"""
Rubrics Generation and Storage Module

This module provides functionality for generating, storing, and managing
evaluation rubrics (criteria) for the Jury LLM system.
"""

import gradio as gr
from src.utils import parse_json_output
from src.llm_provider import LLMProvider
from src.agents import RUBRICS_GENERATION_PROMPT
from src.config import ModelConfig


class RubricsFlow:
    """
    Manages the evaluation rubrics workflow.

    Handles:
    - Manual rubrics input from users
    - AI-generated rubrics based on target text and evaluation purpose
    - Storage and retrieval of rubrics
    """

    def __init__(self):
        self.llm = LLMProvider()
        self.rubrics = ""  # Stored rubrics text
        self.target_text = ""
        self.evaluation_purpose = ""

    def set_context(self, target_text: str, evaluation_purpose: str):
        """Set the target text and evaluation purpose for rubrics generation."""
        self.target_text = target_text
        self.evaluation_purpose = evaluation_purpose

    def generate_rubrics(
        self, target_text: str = None, evaluation_purpose: str = None
    ) -> str:
        """
        Generate evaluation rubrics using AI.

        Args:
            target_text: The text to be evaluated (optional, uses stored if not provided)
            evaluation_purpose: The evaluation goal (optional, uses stored if not provided)

        Returns:
            Generated rubrics text in markdown format
        """
        # Use provided values or fall back to stored values
        text = target_text or self.target_text
        purpose = evaluation_purpose or self.evaluation_purpose

        if not text:
            return "❌ Error: No target text available. Please complete Step 1 first."

        try:
            # Format the prompt with context
            prompt = RUBRICS_GENERATION_PROMPT.format(
                target_text=text, evaluation_purpose=purpose
            )

            # Call LLM to generate rubrics
            model_config = ModelConfig()
            response = self.llm.generate(
                model_config.get_default_model(), [{"role": "user", "content": prompt}]
            )

            # The response should be in markdown format directly
            # If it's wrapped in JSON, parse it
            if response.strip().startswith("{"):
                data = parse_json_output(response)
                rubrics_text = data.get("rubrics", response)
            else:
                rubrics_text = response

            return rubrics_text

        except Exception as e:
            return f"❌ Error generating rubrics: {str(e)}"

    def store_rubrics(self, rubrics: str) -> str:
        """
        Store rubrics for later use.

        Args:
            rubrics: The rubrics text to store

        Returns:
            Confirmation message
        """
        if not rubrics or not rubrics.strip():
            return "❌ Error: Cannot store empty rubrics."

        self.rubrics = rubrics.strip()
        return f"✅ Rubrics stored successfully! ({len(self.rubrics)} characters)"

    def get_rubrics(self) -> str:
        """
        Retrieve stored rubrics.

        Returns:
            The stored rubrics text, or empty string if none stored
        """
        return self.rubrics

    def has_rubrics(self) -> bool:
        """Check if rubrics have been stored."""
        return bool(self.rubrics and self.rubrics.strip())
