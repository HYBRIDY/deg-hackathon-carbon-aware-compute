"""FastAPI Beckn BPP facade for the Coordination Agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from a2a.utils import get_text_parts

from src.beckn.models import BecknCatalog, BecknContext, BecknItem
from src.domain import isoformat, parse_datetime
from src.my_util import my_a2a

LOGGER = logging.getLogger(__name__)

COORDINATION_AGENT_URL = os.getenv("COORDINATION_AGENT_URL", "http://localhost:9001")
PROVIDER_ID = os.getenv("BPP_PROVIDER_ID", "flexcompute-hpc")
PROVIDER_DESCRIPTOR = {
    "name": os.getenv("BPP_PROVIDER_NAME", "FlexCompute HPC Cluster"),
    "short_desc": "Flexible compute capacity for grid services",
}
CATALOG_EXP_HOURS = float(os.getenv("BPP_CATALOG_TTL_HOURS", "12"))

HTTP_CLIENT = httpx.AsyncClient(timeout=10.0)

app = FastAPI(title="CACO Beckn BPP", version="0.1.0")


@app.on_event("shutdown")
async def _shutdown_http_client() -> None:
    await HTTP_CLIENT.aclose()


@app.post("/search")
async def search(payload: Dict[str, Any]) -> JSONResponse:
    try:
        context = _parse_context(payload, expected_action="search")
    except ValueError as exc:
        return _nack_response("BPP-CONTEXT-001", str(exc))
    intent = (payload.get("message") or {}).get("intent", {})
    asyncio.create_task(_handle_search(context, intent))
    return _ack_response()


@app.post("/init")
async def init(payload: Dict[str, Any]) -> JSONResponse:
    try:
        context = _parse_context(payload, expected_action="init")
    except ValueError as exc:
        return _nack_response("BPP-CONTEXT-001", str(exc))
    order = (payload.get("message") or {}).get("order")
    if not order:
        return _nack_response("BPP-INIT-001", "Missing order in message")

    selected_item = _extract_item(order)
    item_id = selected_item.get("id")
    try:
        await _ensure_offer_exists(item_id)
    except HTTPException as exc:
        return _nack_response("BPP-INIT-002", str(exc.detail), status_code=exc.status_code)

    asyncio.create_task(_send_callback(action="on_init", context=context, message={"order": order}))
    return _ack_response()


@app.post("/confirm")
async def confirm(payload: Dict[str, Any]) -> JSONResponse:
    try:
        context = _parse_context(payload, expected_action="confirm")
    except ValueError as exc:
        return _nack_response("BPP-CONTEXT-001", str(exc))
    order = (payload.get("message") or {}).get("order")
    if not order:
        return _nack_response("BPP-CONFIRM-001", "Missing order in message")

    selected_item = _extract_item(order)
    item_id = selected_item.get("id")
    try:
        await _ensure_offer_exists(item_id)
    except HTTPException as exc:
        return _nack_response("BPP-CONFIRM-002", str(exc.detail), status_code=exc.status_code)

    confirmation = {
        "order": order,
        "status": "CONFIRMED",
        "fulfillments": order.get("fulfillment"),
    }
    asyncio.create_task(
        _send_callback(action="on_confirm", context=context, message=confirmation)
    )
    return _ack_response()


async def _handle_search(context: BecknContext, intent: Dict[str, Any]) -> None:
    try:
        window_start, window_end, region, cluster_id = _intent_to_window(intent)
        planning_payload = {
            "command": "run_caco_planning",
            "from": isoformat(window_start),
            "to": isoformat(window_end),
            "horizon_hours": (window_end - window_start).total_seconds() / 3600,
            "region": region,
            "cluster_id": cluster_id,
        }
        planning_response = await _call_coordination(planning_payload)
        if planning_response.get("status") != "success":
            raise RuntimeError(f"Planning failed: {planning_response}")

        flex_offers = planning_response.get("flex_offers", [])
        catalog_message = _build_catalog_message(flex_offers)
        await _send_callback(action="on_search", context=context, message=catalog_message)
    except Exception as exc:  # pragma: no cover - best-effort callback
        LOGGER.warning("search handling failed: %s", exc)
        await _send_callback(
            action="on_search",
            context=context,
            message={"catalog": {}},
            error={"code": "BPP-SEARCH-ERR", "message": str(exc)},
        )


def _parse_context(payload: Dict[str, Any], *, expected_action: str) -> BecknContext:
    context_raw = payload.get("context")
    if not context_raw:
        raise ValueError("Missing context")
    try:
        context = BecknContext.from_dict(context_raw)
    except Exception as exc:
        raise ValueError(f"Invalid context: {exc}") from exc
    if context.action != expected_action:
        raise ValueError(f"Expected action '{expected_action}' but got '{context.action}'")
    if not context.bap_uri:
        raise ValueError("Missing bap_uri in context")
    return context


def _intent_to_window(intent: Dict[str, Any]) -> Tuple[datetime, datetime, str, str]:
    fulfillment = intent.get("fulfillment", {})
    start_info = fulfillment.get("start", {})
    location = start_info.get("location", {})
    time_info = (start_info.get("time") or {}).get("range", {})

    tags = intent.get("tags", {})
    cluster_id = tags.get("cluster_id", "default")

    window_start = (
        parse_datetime(time_info["start"]) if "start" in time_info else datetime.now(timezone.utc)
    )
    if "end" in time_info:
        window_end = parse_datetime(time_info["end"])
    else:
        duration_hours = float(tags.get("duration_hours", "4"))
        window_end = window_start + timedelta(hours=duration_hours)
    region = location.get("city") or location.get("area_code") or "GB"
    return window_start, window_end, region, cluster_id


async def _call_coordination(command: Dict[str, Any]) -> Dict[str, Any]:
    response = await my_a2a.send_message(COORDINATION_AGENT_URL, json.dumps(command))
    text_parts = get_text_parts(response.root.result.parts)
    return json.loads(text_parts[0])


def _build_catalog_message(flex_offers: List[Dict[str, Any]]) -> Dict[str, Any]:
    provider = {
        "id": PROVIDER_ID,
        "descriptor": PROVIDER_DESCRIPTOR,
        "items": [_flex_offer_to_item(offer).to_dict() for offer in flex_offers],
        "exp": isoformat(datetime.now(timezone.utc) + timedelta(hours=CATALOG_EXP_HOURS)),
    }
    catalog = BecknCatalog(
        descriptor=PROVIDER_DESCRIPTOR,
        providers=[provider],
        expires_at=provider["exp"],
    )
    return {"catalog": catalog.to_dict()}


async def _send_callback(
    *,
    action: str,
    context: BecknContext,
    message: Dict[str, Any],
    error: Dict[str, Any] | None = None,
) -> None:
    callback_context = context.with_action(action=action, message_id=_new_message_id())
    body = {"context": callback_context.to_dict(), "message": message, "error": error}
    url = _compose_callback_url(context.bap_uri, action)
    try:
        response = await HTTP_CLIENT.post(url, json=body)
        response.raise_for_status()
    except Exception as exc:  # pragma: no cover - network failures
        LOGGER.warning("Failed to send %s callback to %s: %s", action, url, exc)


def _compose_callback_url(base_uri: str, action: str) -> str:
    base = base_uri.rstrip("/")
    return f"{base}/{action}"


def _ack_response(status: str = "ACK") -> JSONResponse:
    return JSONResponse({"message": {"ack": {"status": status}}, "error": None})


def _nack_response(code: str, message: str, *, status_code: int = 400) -> JSONResponse:
    payload = {"message": {"ack": {"status": "NACK"}}, "error": {"code": code, "message": message}}
    return JSONResponse(status_code=status_code, content=payload)


def _flex_offer_to_item(offer: Dict[str, Any]) -> BecknItem:
    descriptor = {
        "name": f"{offer['power_kw']} kW flexible compute",
        "short_desc": f"{offer['duration_hours']}h window starting {offer['earliest_start']}",
    }
    price = {
        "currency": "GBP",
        "value": f"{offer['price_gbp_per_mwh']:.2f}",
        "unit": "GBP/MWh",
    }
    tags = {
        "cluster_id": offer.get("cluster_id", "default"),
        "power_kw": str(offer.get("power_kw")),
        "duration_hours": str(offer.get("duration_hours")),
        "carbon_cap_g_per_kwh": str(offer.get("carbon_intensity_cap_g_per_kwh", 0)),
    }
    return BecknItem(id=offer["offer_id"], descriptor=descriptor, price=price, tags=tags)


async def _ensure_offer_exists(item_id: str | None) -> None:
    if not item_id:
        raise HTTPException(status_code=400, detail="Missing item id")
    catalog = await _call_coordination({"command": "export_beckn_catalog"})
    offers = {offer["offer_id"] for offer in catalog.get("flex_offers", [])}
    if item_id not in offers:
        raise HTTPException(status_code=404, detail=f"Offer {item_id} unavailable")


def _extract_item(order: Dict[str, Any]) -> Dict[str, Any]:
    items = order.get("items", [])
    if not items:
        raise HTTPException(status_code=400, detail="Order missing items")
    return items[0]


def _new_message_id() -> str:
    return str(uuid.uuid4())

