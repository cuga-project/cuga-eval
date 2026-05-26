"""
Shared LLM client for LiteLLM interactions.
Provides a reusable base class for LLM analysis tasks.
"""

import logging
import os
from typing import Optional

import litellm
from dotenv import load_dotenv
from jinja2 import Template
from litellm import completion

load_dotenv()

# Drop unsupported params (e.g. 'seed') silently for providers that don't accept them.
litellm.drop_params = True

# Configuration constants
DEFAULT_MODEL = "Azure/gpt-4.1"

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Base class for LiteLLM interactions.
    Handles client initialization and provides common analysis methods.
    Supports multiple LLM providers through LiteLLM.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0,
        max_tokens: int = 15000,
        api_key: Optional[str] = None,
        seed: Optional[int] = 47,
    ):
        """
        Initialize the LLM client with LiteLLM.

        Args:
            model: The model name to use (e.g., "gpt-4o-2024-08-06", "azure/gpt-4o")
            temperature: Sampling temperature (default: 0 for deterministic output)
            max_tokens: Maximum tokens in response
            api_key: API key for the LLM provider (optional, can use env vars)
            seed: Random seed for reproducibility
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed
        self.last_usage: dict | None = None

        # Set API key if provided, otherwise LiteLLM will use environment variables
        if api_key:
            os.environ["LITELLM_API_KEY"] = api_key

        # LiteLLM will automatically detect the provider based on model name
        # and use appropriate environment variables (OPENAI_API_KEY, AZURE_API_KEY, etc.)

    def analyze(
        self,
        prompt: str,
        system_message: str,
        # temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> str:
        """
        Perform LLM analysis with the given prompt and system message.

        Args:
            prompt: The user prompt to send to the LLM
            system_message: The system message defining the LLM's role
            temperature: Override default temperature (optional)
            max_tokens: Override default max_tokens (optional)
            seed: Override default seed (optional)

        Returns:
            The LLM's response content

        Raises:
            Exception: If the LLM call fails
        """
        try:
            # Prepare completion arguments
            completion_args = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                "max_tokens": (max_tokens if max_tokens is not None else self.max_tokens),
            }

            # Add seed if provided (for reproducibility)
            seed_value = seed if seed is not None else self.seed
            if seed_value is not None:
                completion_args["seed"] = seed_value

            # Configure for LiteLLM proxy if credentials are present.
            # Check LITELLM_* vars first, then fall back to OPENAI_* vars
            # (OPENAI_BASE_URL may point to an IBM/internal LiteLLM proxy).
            litellm_key = os.getenv("LITELLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            litellm_base = os.getenv("LITELLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")

            if litellm_key and litellm_base:
                # Using LiteLLM proxy - pass model name as-is
                completion_args["api_key"] = litellm_key
                completion_args["base_url"] = litellm_base
                completion_args["custom_llm_provider"] = "openai"
            elif litellm_key:
                completion_args["api_key"] = litellm_key

            response = completion(**completion_args)

            llm_response = response.choices[0].message.content
            if hasattr(response, "usage") and response.usage:
                self.last_usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            logger.info(f"LLM analysis completed using model {self.model}")
            return llm_response

        except Exception as e:
            error_msg = f"LLM analysis failed: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg) from e

    def analyze_with_template(
        self,
        prompt_template: Template,
        template_vars: dict,
        system_message: str,
        # temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> str:
        """
        Perform LLM analysis using a Jinja2 template.

        Args:
            prompt_template: Jinja2 Template object
            template_vars: Dictionary of variables to render in template
            system_message: The system message defining the LLM's role
            temperature: Override default temperature (optional)
            max_tokens: Override default max_tokens (optional)
            seed: Override default seed (optional)

        Returns:
            The LLM's response content

        Raises:
            Exception: If template rendering or LLM call fails
        """
        try:
            prompt = prompt_template.render(**template_vars)
            return self.analyze(
                # prompt, system_message, temperature, max_tokens, seed
                prompt,
                system_message,
                max_tokens,
                seed,
            )
        except Exception as e:
            error_msg = f"Template rendering or LLM analysis failed: {str(e)}"
            logger.error(error_msg)
            raise Exception(error_msg) from e


# Backward compatibility: LLMAnalysis alias
class LLMAnalysis(LLMClient):
    """
    Deprecated: Use LLMClient instead.
    Kept for backward compatibility with existing code.
    """

    def __init__(self):
        """Initialize with default settings for backward compatibility."""
        super().__init__()
        logger.warning("LLMAnalysis is deprecated. Please use LLMClient instead.")

    def _perform_llm_analysis(self, prompt_template: Template, content: str) -> str:
        """
        Deprecated method for backward compatibility.

        Args:
            prompt_template: Jinja2 template
            content: Content to analyze (passed as template variable)

        Returns:
            LLM response
        """
        # Determine the template variable name based on common patterns
        # This is a heuristic for backward compatibility
        template_vars = {}
        if "agent_info" in prompt_template.render():
            template_vars["agent_info"] = content
        elif "trace_comparison_report" in prompt_template.render():
            template_vars["trace_comparison_report"] = content
        else:
            # Fallback: try common variable names
            template_vars["content"] = content

        system_message = "You are an expert AI assistant."
        return self.analyze_with_template(prompt_template, template_vars, system_message)
