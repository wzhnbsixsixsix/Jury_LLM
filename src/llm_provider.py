import os
from typing import List, Dict, Any, Optional
from openai import OpenAI
import logging
import json
from src.utils import parse_json_output

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMProvider:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        # 1. Try to get generic config first
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")

        # 2. If not set, check for specific providers
        if not self.api_key:
            if os.getenv("OPENROUTER_API_KEY"):
                logger.info("Using OpenRouter configuration.")
                self.api_key = os.getenv("OPENROUTER_API_KEY")
                self.base_url = self.base_url or "https://openrouter.ai/api/v1"
            elif os.getenv("DASHSCOPE_API_KEY"):
                logger.info("Using DashScope configuration.")
                self.api_key = os.getenv("DASHSCOPE_API_KEY")
                self.base_url = self.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            else:
                logger.warning("No API Key found. Please set OPENROUTER_API_KEY or DASHSCOPE_API_KEY.")

        # Initialize OpenAI client
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def generate(self, model: str, messages: List[Dict[str, str]], temperature: float = 0.7, max_tokens: int = 1000) -> str:
        """
        Generate a response using the OpenAI client.
        """
        try:
            # OpenRouter requires the 'referer' header for rankings (optional but recommended)
            extra_headers = {}
            if "openrouter" in (self.base_url or ""):
                extra_headers = {
                    "HTTP-Referer": "https://github.com/jury-llm", # Placeholder
                    "X-Title": "Jury LLM"
                }

            # payload_log = {
            #     "model": model,
            #     "messages": messages,
            #     "temperature": temperature,
            #     "max_tokens": max_tokens
            # }
            # logger.info(f"LLM Request Payload: {json.dumps(payload_log, ensure_ascii=False)}")

            completion = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers=extra_headers
            )
            content = completion.choices[0].message.content
            # try:
            #     parsed = parse_json_output(content)
            #     logger.info(f"LLM Response Parsed: {json.dumps(parsed, ensure_ascii=False)}")
            # except Exception:
            #     logger.info("LLM Response Parsed: {}")
            # logger.info(f"LLM Response Raw: {content}")
            return content
        except Exception as e:
            logger.error(f"Error generating response from {model}: {e}")
            return f"Error: {str(e)}"

    def generate_batch(self, models: List[str], messages: List[Dict[str, str]]) -> Dict[str, str]:
        """
        (Optional) Helper for sequential batch generation. 
        """
        results = {}
        for model in models:
            results[model] = self.generate(model, messages)
        return results
