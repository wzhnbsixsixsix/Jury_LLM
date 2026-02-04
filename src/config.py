"""
Central Model Configuration Module

This module provides a unified interface for managing AI model names across the Jury LLM system.
It supports:
- YAML configuration file as the base source of truth
- Environment variable overrides for flexibility
- Per-judge model customization
- Safe default fallbacks

Priority order: Environment Variable → YAML Config → Hardcoded Default
"""

import os
import yaml
from typing import Dict, List, Optional
from pathlib import Path


class ModelConfig:
    """
    Centralized model configuration management.

    This class implements a singleton pattern to ensure consistent model configuration
    across the entire application. It loads configuration from YAML files and allows
    environment variable overrides.

    Environment Variables:
        DEFAULT_MODEL: Override the default model name
        CHIEF_MODEL: Override the chief justice model
        LOGIC_JUDGE_MODEL: Override logic judge model
        EXPRESSION_JUDGE_MODEL: Override expression judge model
        UTILITY_JUDGE_MODEL: Override utility judge model
        MORAL_JUDGE_MODEL: Override moral judge model

    Usage:
        config = ModelConfig()
        logic_model = config.get_judge_model("logic")
        chief_model = config.get_chief_model()
    """

    _instance = None
    _initialized = False

    # Default fallback model if all else fails
    DEFAULT_FALLBACK_MODEL = "qwen-max"

    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super(ModelConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the model configuration.

        Args:
            config_path: Path to the YAML configuration file.
                        If None, uses default path: config/jury_config.yaml
        """
        # Only initialize once
        if ModelConfig._initialized:
            return

        self.config_path = config_path or self._get_default_config_path()
        self._config_data = None
        self._load_config()
        ModelConfig._initialized = True

    def _get_default_config_path(self) -> str:
        """Get the default configuration file path."""
        # Assumes the config directory is at the project root
        current_dir = Path(__file__).parent  # src directory
        project_root = current_dir.parent  # project root
        return str(project_root / "config" / "jury_config.yaml")

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._config_data = yaml.safe_load(f)
        except FileNotFoundError:
            print(
                f"Warning: Config file not found at {self.config_path}. Using defaults."
            )
            self._config_data = {}
        except yaml.YAMLError as e:
            print(f"Warning: Error parsing YAML config: {e}. Using defaults.")
            self._config_data = {}

    def reload_config(self) -> None:
        """Reload configuration from file. Useful for testing or runtime updates."""
        self._load_config()

    def get_default_model(self) -> str:
        """
        Get the default model name to use throughout the system.

        Priority:
        1. Environment variable: DEFAULT_MODEL
        2. YAML config: model_settings.default_model
        3. YAML config: judge_model (legacy)
        4. Hardcoded fallback: "qwen-max"

        Returns:
            str: The default model name
        """
        # Check environment variable first
        env_model = os.getenv("DEFAULT_MODEL")
        if env_model:
            return env_model

        # Check model_settings.default_model in config
        if self._config_data:
            model_settings = self._config_data.get("model_settings", {})
            if isinstance(model_settings, dict):
                default_model = model_settings.get("default_model")
                if default_model:
                    return default_model

            # Fallback to judge_model (legacy)
            judge_model = self._config_data.get("judge_model")
            if judge_model:
                return judge_model

        # Final fallback
        return self.DEFAULT_FALLBACK_MODEL

    def get_judge_model(self, role: Optional[str] = None) -> str:
        """
        Get the model name for a specific judge by role.

        Priority:
        1. Environment variable: {ROLE}_JUDGE_MODEL (e.g., LOGIC_JUDGE_MODEL)
        2. YAML config: judge_models.{role} (e.g., judge_models.logic)
        3. YAML config: jury_models[index] (legacy, for backward compatibility)
        4. Environment variable: CHIEF_MODEL (for chief justice)
        5. YAML config: judge_model (legacy)
        6. Default model

        Args:
            role: Judge role name ("logic", "expression", "utility", "moral", "chief")
                  If None, returns the default judge/chief model

        Returns:
            str: The model name for this judge
        """
        # Role mapping for backward compatibility
        role_to_index = {
            "logic": 0,
            "expression": 1,
            "utility": 2,
            "moral": 3,
        }

        # If no role specified, return default judge model (chief justice)
        if role is None or role == "chief":
            # Check environment variable for chief
            env_model = os.getenv("CHIEF_MODEL")
            if env_model:
                return env_model

            # Check YAML config: judge_models.chief
            if self._config_data:
                judge_models = self._config_data.get("judge_models", {})
                if isinstance(judge_models, dict):
                    chief_model = judge_models.get("chief")
                    if chief_model:
                        return chief_model

            # Fallback to legacy judge_model
            if self._config_data:
                judge_model = self._config_data.get("judge_model")
                if judge_model:
                    return judge_model

            return self.get_default_model()

        # Normalize role name
        role_lower = role.lower()

        # Check environment variable: {ROLE}_JUDGE_MODEL
        env_var_name = f"{role_lower.upper()}_JUDGE_MODEL"
        env_model = os.getenv(env_var_name)
        if env_model:
            return env_model

        # Check YAML config: judge_models.{role}
        if self._config_data:
            judge_models = self._config_data.get("judge_models", {})
            if isinstance(judge_models, dict):
                role_model = judge_models.get(role_lower)
                if role_model:
                    return role_model

        # Backward compatibility: check jury_models list by index
        if role_lower in role_to_index:
            index = role_to_index[role_lower]
            if self._config_data:
                jury_models = self._config_data.get("jury_models", [])
                if isinstance(jury_models, list) and 0 <= index < len(jury_models):
                    return jury_models[index]

        # Final fallback
        return self.get_default_model()

    def get_chief_model(self) -> str:
        """
        Get the model name for the chief justice.
        Convenience method that calls get_judge_model("chief").

        Returns:
            str: The chief justice model name
        """
        return self.get_judge_model("chief")

    def get_jury_model(self, index: int) -> str:
        """
        Get the model name for a specific jury member.

        Priority:
        1. Environment variable: JURY_MODEL_{index+1} (e.g., JURY_MODEL_1, JURY_MODEL_2)
        2. YAML config: jury_models[index]
        3. Judge model (same as main judge)

        Args:
            index: Zero-based index of the jury member (0-4 for 5 jury members)

        Returns:
            str: The model name for this jury member
        """
        # Check environment variable (1-based indexing for user friendliness)
        env_var_name = f"JURY_MODEL_{index + 1}"
        env_model = os.getenv(env_var_name)
        if env_model:
            return env_model

        # Check YAML config
        if self._config_data:
            jury_models = self._config_data.get("jury_models", [])
            if isinstance(jury_models, list) and 0 <= index < len(jury_models):
                return jury_models[index]

        # Fallback to judge model
        return self.get_judge_model()

    def get_all_jury_models(self) -> Dict[str, str]:
        """
        Get all jury member models by role name.

        Returns:
            Dict[str, str]: Dictionary mapping role names to model names
                {
                    "logic": "qwen-max",
                    "expression": "qwen-plus",
                    "utility": "qwen-turbo",
                    "moral": "qwen-max",
                    "chief": "qwen-max"
                }
        """
        roles = ["logic", "expression", "utility", "moral", "chief"]
        return {role: self.get_judge_model(role) for role in roles}

    def get_all_jury_models_list(self) -> List[str]:
        """
        Get all jury member models as a list (legacy compatibility).

        Returns:
            List[str]: List of model names in order [logic, expression, utility, moral]
        """
        roles = ["logic", "expression", "utility", "moral"]
        return [self.get_judge_model(role) for role in roles]

    def get_provider_model(self, provider: str) -> Optional[str]:
        """
        Get provider-specific model mapping.

        This allows you to define different model names per provider in the config:

        model_settings:
          provider_models:
            openrouter: "anthropic/claude-3.5-sonnet"
            dashscope: "qwen-max"

        Args:
            provider: Provider name (e.g., "openrouter", "dashscope")

        Returns:
            Optional[str]: The model name for this provider, or None if not configured
        """
        if not self._config_data:
            return None

        model_settings = self._config_data.get("model_settings", {})
        if not isinstance(model_settings, dict):
            return None

        provider_models = model_settings.get("provider_models", {})
        if not isinstance(provider_models, dict):
            return None

        return provider_models.get(provider)

    def get_config_summary(self) -> Dict[str, any]:
        """
        Get a summary of the current model configuration.

        Useful for debugging and displaying configuration to users.

        Returns:
            Dict: Summary of current configuration including all models
        """
        jury_models = self.get_all_jury_models()
        return {
            "config_path": self.config_path,
            "default_model": self.get_default_model(),
            "chief_model": jury_models.get("chief"),
            "judge_models": {
                "logic": jury_models.get("logic"),
                "expression": jury_models.get("expression"),
                "utility": jury_models.get("utility"),
                "moral": jury_models.get("moral"),
            },
            "has_env_overrides": bool(
                os.getenv("DEFAULT_MODEL")
                or os.getenv("CHIEF_MODEL")
                or os.getenv("LOGIC_JUDGE_MODEL")
                or os.getenv("EXPRESSION_JUDGE_MODEL")
                or os.getenv("UTILITY_JUDGE_MODEL")
                or os.getenv("MORAL_JUDGE_MODEL")
            ),
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        summary = self.get_config_summary()
        return f"ModelConfig(chief={summary['chief_model']}, judges=4)"


# Convenience function for getting the singleton instance
def get_model_config() -> ModelConfig:
    """
    Get the ModelConfig singleton instance.

    This is a convenience function that returns the singleton instance.
    You can also instantiate ModelConfig() directly.

    Returns:
        ModelConfig: The singleton configuration instance
    """
    return ModelConfig()


# Example usage and testing
if __name__ == "__main__":
    # Example usage
    config = ModelConfig()

    print("=== Model Configuration Summary ===")
    print(f"Config file: {config.config_path}")
    print(f"Default model: {config.get_default_model()}")
    print(f"Chief Justice model: {config.get_chief_model()}")
    print()

    print("=== Individual Judge Models ===")
    roles = ["logic", "expression", "utility", "moral"]
    for role in roles:
        print(f"{role.capitalize()} Judge: {config.get_judge_model(role)}")
    print()

    print("=== All Judge Models (Dict) ===")
    print(config.get_all_jury_models())
    print()

    print("=== Full Summary ===")
    import json

    print(json.dumps(config.get_config_summary(), indent=2, ensure_ascii=False))
