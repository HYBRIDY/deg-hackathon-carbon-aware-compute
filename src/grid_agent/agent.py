"""Grid Agent serving carbon intensity and BMRS price forecasts."""

from __future__ import annotations

import asyncio
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

from src.data_sources import BMRSClient, CarbonIntensityClient
from src.domain import parse_datetime

dotenv.load_dotenv()


def _load_agent_card(agent_name: str) -> Dict[str, Any]:
    config_path = Path(__file__).parent / f"{agent_name}.toml"
    with config_path.open("rb") as file_obj:
        return tomllib.load(file_obj)


class GridAgentExecutor(AgentExecutor):
    """Handles get_grid_forecast commands."""

    def __init__(
        self,
        *,
        carbon_client: CarbonIntensityClient | None = None,
        bmrs_client: BMRSClient | None = None,
    ) -> None:
        self._carbon_client = carbon_client or CarbonIntensityClient()
        api_key = os.getenv("BMRS_API_KEY")
        self._bmrs_client = bmrs_client or BMRSClient(api_key=api_key)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        try:
            payload = json.loads(context.get_user_input())
        except json.JSONDecodeError as exc:
            await self._emit_error(event_queue, context.context_id, f"Invalid JSON payload: {exc}")
            return

        command = payload.get("command")
        if command != "get_grid_forecast":
            await self._emit_error(event_queue, context.context_id, f"Unsupported command '{command}'")
            return

        try:
            window_start = parse_datetime(payload["from"])
            window_end = parse_datetime(payload["to"])
        except Exception as exc:
            await self._emit_error(event_queue, context.context_id, f"Invalid window: {exc}")
            return

        carbon_task = asyncio.create_task(self._carbon_client.get_forecast_24h(window_start))
        price_task = asyncio.create_task(self._bmrs_client.get_system_prices(window_start, window_end))
        carbon_series_raw, price_series = await asyncio.gather(carbon_task, price_task)

        carbon_series = [
            point for point in carbon_series_raw if window_start <= point.timestamp <= window_end
        ] or carbon_series_raw

        response = {
            "carbon_series": [point.to_dict() for point in carbon_series],
            "price_series": [point.to_dict() for point in price_series],
        }

        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(response), context_id=context.context_id)
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:  # pragma: no cover - cancellation not used
        await self._emit_error(event_queue, context.context_id, "Request cancelled")

    @staticmethod
    async def _emit_error(event_queue: EventQueue, context_id: str, message: str) -> None:
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps({"status": "error", "message": message}), context_id=context_id)
        )


def start_grid_agent(agent_name: str = "caco_grid_agent", host: str = "localhost", port: int = 9003) -> None:
    agent_card_dict = _load_agent_card(agent_name)
    agent_card_dict["url"] = f"http://{host}:{port}"

    request_handler = DefaultRequestHandler(
        agent_executor=GridAgentExecutor(),
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


