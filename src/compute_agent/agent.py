"""Compute Agent responsible for workload ingestion and flexibility reporting."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import dotenv
import tomllib
import uvicorn
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.apps import A2AStarletteApplication
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCard
from a2a.utils import new_agent_text_message
from starlette.responses import JSONResponse

from src.domain import JobSpec, isoformat, parse_datetime

dotenv.load_dotenv()


def _load_agent_card(agent_name: str) -> Dict[str, Any]:
    with (Path(__file__).parent / f"{agent_name}.toml").open("rb") as file_obj:
        return tomllib.load(file_obj)


class ComputeAgentExecutor(AgentExecutor):
    def __init__(self, *, bootstrap_path: str | None = None) -> None:
        self.jobs: Dict[str, JobSpec] = {}
        if bootstrap_path and Path(bootstrap_path).exists():
            self._load_from_file(bootstrap_path)

    def _load_from_file(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
        for job_payload in data.get("jobs", []):
            job = JobSpec.from_dict(job_payload)
            self.jobs[job.job_id] = job

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            payload = json.loads(context.get_user_input())
        except json.JSONDecodeError as exc:
            await self._emit_error(event_queue, context.context_id, f"Invalid JSON payload: {exc}")
            return

        command = payload.get("command")
        if command == "ingest_jobs":
            response = self._handle_ingest(payload)
        elif command == "get_flexibility_profile":
            response = self._handle_flex_profile(payload)
        else:
            response = {"status": "error", "message": f"Unknown command '{command}'"}

        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(response), context_id=context.context_id)
        )

    def _handle_ingest(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        jobs_payload = payload.get("jobs", [])
        ingested = 0
        for job_data in jobs_payload:
            job = JobSpec.from_dict(job_data)
            self.jobs[job.job_id] = job
            ingested += 1
        return {"status": "ok", "num_jobs_ingested": ingested, "total_jobs": len(self.jobs)}

    def _handle_flex_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        window_start = parse_datetime(payload["from"])
        window_end = parse_datetime(payload["to"])
        cluster_filter = payload.get("cluster_id")

        jobs_view: List[Dict[str, Any]] = []
        for job in self.jobs.values():
            if cluster_filter and job.cluster_id != cluster_filter:
                continue
            if job.deadline < window_start or job.arrival_time > window_end:
                continue

            earliest_start = max(job.arrival_time, window_start)
            latest_end = min(job.deadline, window_end)
            slack_hours = max(0.0, (latest_end - earliest_start).total_seconds() / 3600 - job.duration_hours)

            jobs_view.append(
                {
                    **job.to_dict(),
                    "earliest_start": isoformat(earliest_start),
                    "latest_end": isoformat(latest_end),
                    "slack_hours": round(slack_hours, 2),
                    "is_flexible": job.is_flexible,
                }
            )

        return {"status": "ok", "jobs": jobs_view}

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:  # pragma: no cover - cancellation unused
        await self._emit_error(event_queue, context.context_id, "Request cancelled")

    @staticmethod
    async def _emit_error(event_queue: EventQueue, context_id: str, message: str) -> None:
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps({"status": "error", "message": message}), context_id=context_id)
        )


def start_compute_agent(agent_name: str = "caco_compute_agent", host: str = "localhost", port: int = 9002) -> None:
    bootstrap_path = os.getenv("COMPUTE_AGENT_JOBS_PATH")
    agent_card_dict = _load_agent_card(agent_name)
    agent_card_dict["url"] = f"http://{host}:{port}"

    request_handler = DefaultRequestHandler(
        agent_executor=ComputeAgentExecutor(bootstrap_path=bootstrap_path),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(
        agent_card=AgentCard(**agent_card_dict),
        http_handler=request_handler,
    )

    starlette_app = app.build()

    @starlette_app.route("/", methods=["GET"])
    async def _agent_card_route(_request):
        return JSONResponse(agent_card_dict)

    uvicorn.run(starlette_app, host=host, port=port)


