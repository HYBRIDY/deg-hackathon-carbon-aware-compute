"""Coordination Agent orchestrating CACO planning."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
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
from a2a.utils import get_text_parts, new_agent_text_message

from src.domain import CarbonPoint, FlexOffer, JobSpec, PricePoint, ScheduledJob, isoformat, parse_datetime
from src.my_util import my_a2a
from src.optimization import optimize_schedule

dotenv.load_dotenv()


def _load_agent_card(agent_name: str) -> Dict[str, Any]:
    with (Path(__file__).parent / f"{agent_name}.toml").open("rb") as file_obj:
        return tomllib.load(file_obj)


class CoordinationAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self._last_schedule: List[ScheduledJob] = []
        self._last_flex_offers: List[FlexOffer] = []

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            payload = json.loads(context.get_user_input())
        except json.JSONDecodeError as exc:
            await self._emit(event_queue, context.context_id, {"status": "error", "message": str(exc)})
            return

        command = payload.get("command")
        if command == "run_caco_planning":
            response = await self._handle_run_planning(payload)
        elif command == "export_beckn_catalog":
            response = {
                "status": "ok",
                "flex_offers": [offer.to_dict() for offer in self._last_flex_offers],
            }
        else:
            response = {"status": "error", "message": f"Unknown command '{command}'"}

        await self._emit(event_queue, context.context_id, response)

    async def _handle_run_planning(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        horizon_hours = int(payload.get("horizon_hours", 24))
        window_start = (
            parse_datetime(payload["from"]) if "from" in payload else datetime.now(timezone.utc)
        )
        window_end = (
            parse_datetime(payload["to"]) if "to" in payload else window_start + timedelta(hours=horizon_hours)
        )
        region = payload.get("region", "GB")
        cluster_id = payload.get("cluster_id", "default")

        endpoints = payload.get("endpoints", {})
        compute_url = endpoints.get("compute_agent_url") or os.getenv("COMPUTE_AGENT_URL", "http://localhost:9002")
        grid_url = endpoints.get("grid_agent_url") or os.getenv("GRID_AGENT_URL", "http://localhost:9003")

        optimization_cfg = payload.get(
            "optimization",
            {"carbon_penalty_weight": 0.5, "sla_penalty_weight": 1.0, "max_power_kw": 10000},
        )

        carbon_series, price_series = await self._fetch_grid_series(grid_url, window_start, window_end, region)
        job_specs = await self._fetch_jobs(compute_url, window_start, window_end, cluster_id)

        scheduled_jobs, flex_offers = optimize_schedule(
            job_specs,
            carbon_series,
            price_series,
            carbon_penalty_weight=float(optimization_cfg.get("carbon_penalty_weight", 0.5)),
            sla_penalty_weight=float(optimization_cfg.get("sla_penalty_weight", 1.0)),
            max_power_kw=float(optimization_cfg.get("max_power_kw", 10000)),
        )

        self._last_schedule = scheduled_jobs
        self._last_flex_offers = flex_offers

        return {
            "status": "success",
            "window": {"from": isoformat(window_start), "to": isoformat(window_end), "region": region},
            "scheduled_jobs": [job.to_dict() for job in scheduled_jobs],
            "flex_offers": [offer.to_dict() for offer in flex_offers],
        }

    async def _fetch_grid_series(
        self,
        grid_url: str,
        window_start: datetime,
        window_end: datetime,
        region: str,
    ) -> tuple[List[CarbonPoint], List[PricePoint]]:
        request_payload = json.dumps(
            {
                "command": "get_grid_forecast",
                "from": isoformat(window_start),
                "to": isoformat(window_end),
                "region": region,
            }
        )
        response = await my_a2a.send_message(grid_url, request_payload)
        text_parts = get_text_parts(response.root.result.parts)
        grid_payload = json.loads(text_parts[0])
        carbon_series = [CarbonPoint.from_dict(entry) for entry in grid_payload.get("carbon_series", [])]
        price_series = [PricePoint.from_dict(entry) for entry in grid_payload.get("price_series", [])]
        return carbon_series, price_series

    async def _fetch_jobs(
        self,
        compute_url: str,
        window_start: datetime,
        window_end: datetime,
        cluster_id: str,
    ) -> List[JobSpec]:
        request_payload = json.dumps(
            {
                "command": "get_flexibility_profile",
                "from": isoformat(window_start),
                "to": isoformat(window_end),
                "cluster_id": cluster_id,
            }
        )
        response = await my_a2a.send_message(compute_url, request_payload)
        text_parts = get_text_parts(response.root.result.parts)
        jobs_payload = json.loads(text_parts[0])
        if jobs_payload.get("status") != "ok":
            raise RuntimeError(f"Compute agent error: {jobs_payload}")
        return [JobSpec.from_dict(job) for job in jobs_payload.get("jobs", [])]

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:  # pragma: no cover
        await self._emit(event_queue, context.context_id, {"status": "cancelled"})

    @staticmethod
    async def _emit(event_queue: EventQueue, context_id: str, payload: Dict[str, Any]) -> None:
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(payload), context_id=context_id)
        )


def start_coordination_agent(agent_name: str = "caco_coordination_agent", host: str = "localhost", port: int = 9001) -> None:
    agent_card_dict = _load_agent_card(agent_name)
    agent_card_dict["url"] = f"http://{host}:{port}"

    request_handler = DefaultRequestHandler(
        agent_executor=CoordinationAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(
        agent_card=AgentCard(**agent_card_dict),
        http_handler=request_handler,
    )

    uvicorn.run(app.build(), host=host, port=port)


