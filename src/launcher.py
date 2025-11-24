"""Launcher module for the CACO multi-agent stack."""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Dict, List

from a2a.utils import get_text_parts

from src.compute_agent import start_compute_agent
from src.coordination_agent import start_coordination_agent
from src.grid_agent import start_grid_agent
from src.my_util import my_a2a

AGENT_CONFIG = {
    "coord": {"host": "localhost", "port": 9001},
    "compute": {"host": "localhost", "port": 9002},
    "grid": {"host": "localhost", "port": 9003},
}

SYNTHETIC_DATA_PATH = Path("data/synthetic/workloads.json")


async def launch_caco_simulation(horizon_hours: int = 24) -> Dict[str, List[Dict[str, str]]]:
    """Spin up agents, ingest workloads, and run a planning cycle."""

    processes: List[multiprocessing.Process] = []
    coordination_url = _spawn_agent(processes, start_coordination_agent, "coord", agent_name="caco_coordination_agent")
    assert await my_a2a.wait_agent_ready(coordination_url), "Coordination agent failed to start"
    compute_url = _spawn_agent(processes, start_compute_agent, "compute", agent_name="caco_compute_agent")
    assert await my_a2a.wait_agent_ready(compute_url), "Compute agent failed to start"
    grid_url = _spawn_agent(processes, start_grid_agent, "grid", agent_name="caco_grid_agent")
    assert await my_a2a.wait_agent_ready(grid_url), "Grid agent failed to start"

    try:
        jobs_payload = _load_jobs()
        if jobs_payload:
            ingest_payload = json.dumps({"command": "ingest_jobs", "jobs": jobs_payload})
            await my_a2a.send_message(compute_url, ingest_payload)

        planning_payload = json.dumps(
            {
                "command": "run_caco_planning",
                "horizon_hours": horizon_hours,
                "region": "GB",
                "cluster_id": "hpc-1",
                "optimization": {
                    "carbon_penalty_weight": 0.6,
                    "sla_penalty_weight": 2.0,
                    "max_power_kw": 12000,
                },
                "endpoints": {
                    "compute_agent_url": compute_url,
                    "grid_agent_url": grid_url,
                },
            }
        )
        response = await my_a2a.send_message(coordination_url, planning_payload)
        text = get_text_parts(response.root.result.parts)[0]
        print("CACO planning result:", text)
        return json.loads(text)
    finally:
        for process in processes:
            process.terminate()
            process.join()


def _spawn_agent(
    processes: List[multiprocessing.Process],
    target,
    key: str,
    *,
    agent_name: str,
) -> str:
    host = AGENT_CONFIG[key]["host"]
    port = AGENT_CONFIG[key]["port"]
    url = f"http://{host}:{port}"
    process = multiprocessing.Process(target=target, args=(agent_name, host, port))
    process.start()
    processes.append(process)
    return url


def _load_jobs() -> List[Dict[str, str]]:
    if not SYNTHETIC_DATA_PATH.exists():
        return []
    with SYNTHETIC_DATA_PATH.open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    return data.get("jobs", [])
