"""Thin logging wrapper around LLM completion calls."""

from __future__ import annotations
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple
from litellm import completion
from src.logging import CsvEventLogger, DEFAULT_EVENT_FIELDS, now_iso


class LoggedLLM:
    """Wrap an LLM client call and append telemetry to a CSV file."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        agent_type: str,
        csv_path: str = "logs/events.csv",
        code_version: str = "dev",
        currency: str = "USD",
        llm_call_fn: Callable[..., Any] = completion,
        logger: Optional[CsvEventLogger] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.agent_type = agent_type
        self.code_version = code_version
        self.currency = currency
        self.llm_call_fn = llm_call_fn
        self.logger = logger or CsvEventLogger(csv_path, DEFAULT_EVENT_FIELDS)

    @staticmethod
    def _usage_value(usage: Any, key: str, default: int = 0) -> int:
        if usage is None:
            return default
        if hasattr(usage, key):
            try:
                return int(getattr(usage, key))
            except (TypeError, ValueError):
                return default
        if isinstance(usage, dict):
            try:
                return int(usage.get(key, default))
            except (TypeError, ValueError):
                return default
        return default

    @staticmethod
    def _cost_value(resp: Any, key: str) -> float:
        hidden = getattr(resp, "_hidden_params", {}) or {}
        try:
            return float(hidden.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _assistant_text(resp: Any) -> str:
        message = resp.choices[0].message
        if hasattr(message, "model_dump"):
            return message.model_dump().get("content", "")
        if isinstance(message, dict):
            return message.get("content", "")
        return str(message)

    def call(
        self,
        *,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        user_prompt: str,
        runtime_parameters: Optional[Dict[str, Any]] = None,
        streaming: bool = False,
    ) -> Tuple[Any, str]:
        """Execute the LLM call and append a telemetry row."""

        request_id = uuid.uuid4().hex
        runtime_parameters = runtime_parameters or {}
        start_ms = int(time.time() * 1000)
        prefill_done_ms = start_ms
        response = self.llm_call_fn(
            messages=messages,
            model=self.model,
            custom_llm_provider=self.provider,
            **runtime_parameters,
        )
        assistant_text = self._assistant_text(response)
        usage = getattr(response, "usage", None)
        tokens_in = self._usage_value(usage, "prompt_tokens")
        tokens_out = self._usage_value(usage, "completion_tokens")
        input_cost = self._cost_value(response, "prompt_cost")
        output_cost = self._cost_value(response, "completion_cost")

        first_ms = prefill_done_ms if not streaming else prefill_done_ms
        last_ms = int(time.time() * 1000)
        latency = last_ms - start_ms
        ttft_ms = first_ms - prefill_done_ms
        prefill_time_ms = prefill_done_ms - start_ms
        duration_s = max(1, last_ms - first_ms) / 1000.0
        tps = round(tokens_out / duration_s, 3) if tokens_out else 0.0

        self.logger.append(
            {
                "datetime": now_iso(),
                "request_id": request_id,
                "agent_type": self.agent_type,
                "provider": self.provider,
                "llm_model": self.model,
                "code_version": self.code_version,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_text": assistant_text,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "input_cost": input_cost,
                "output_cost": output_cost,
                "currency": self.currency,
                "ttft_ms": ttft_ms,
                "prefill_time_ms": prefill_time_ms,
                "latency_ms_total": latency,
                "tps": tps,
                "runtime_parameters": runtime_parameters,
                "human_vote": "",
            }
        )
        return response, assistant_text


__all__ = ["LoggedLLM"]

