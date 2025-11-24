"""Shared CSV schema definition for event logging."""

from __future__ import annotations

DEFAULT_EVENT_FIELDS = [
    "datetime",
    "request_id",
    "agent_type",
    "provider",
    "llm_model",
    "code_version",
    "system_prompt",
    "user_prompt",
    "response_text",
    "tokens_in",
    "tokens_out",
    "input_cost",
    "output_cost",
    "currency",
    "ttft_ms",
    "prefill_time_ms",
    "latency_ms_total",
    "tps",
    "runtime_parameters",
    "human_vote",
]

__all__ = ["DEFAULT_EVENT_FIELDS"]

