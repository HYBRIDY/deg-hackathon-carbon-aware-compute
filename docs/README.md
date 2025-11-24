<!--
  CACO documentation for developers and reviewers.
  Explains architecture, execution and I/O expectations.
-->

# Carbon-Aware Compute Orchestrator (CACO) – Technical Guide

## 1. System Overview

CACO is a multi-agent orchestration platform that shifts AI workloads toward low-carbon, low-cost grid periods and exposes flexibility offers via the Beckn protocol. The stack comprises:

- **Compute Agent (`src/compute_agent`)**  
  Ingests workload jobs (`JobSpec`), tracks flexibility windows, and returns aggregated power/SLA metadata.

- **Grid Agent (`src/grid_agent`)**  
  Wraps the UK **Carbon Intensity API** and **BMRS/Elexon** feeds, normalizing carbon and price forecasts to half-hour settlement periods.

- **Coordination Agent (`src/coordination_agent`)**  
  Calls the other two agents, runs the heuristic optimizer (`src/optimization/engine.py`), and maintains the latest schedule/flex offers.

- **Beckn BPP Server (`src/beckn/server.py`)**  
  Presents the flexibility catalog to grid operators through Beckn Core 1.0.0 compliant `search/on_search/init/confirm` flows.

- **Launcher/CLI (`main.py`, `src/launcher.py`)**  
  Typer commands to start agents individually or run a full simulation; includes a helper that spins up all agents, ingests synthetic jobs (`data/synthetic/workloads.json`), and prints scheduling results.

Key shared dataclasses live in `src/domain/models.py`, including `JobSpec`, `CarbonPoint`, `PricePoint`, `ScheduledJob`, and `FlexOffer`.

## 2. How the Code Works

### 2.1 Data Flow
1. **Workload ingestion** – `compute_agent` accepts `{"command":"ingest_jobs","jobs":[...]}` payloads, storing `JobSpec` entries with arrival/deadline, power, SLA, and metadata.
2. **Grid forecasting** – `grid_agent` serves `{"command":"get_grid_forecast","from":...,"to":...}` requests, returning carbon intensity and system buy/sell price series aligned to 30-minute slots.
3. **Planning cycle** – `coordination_agent` receives `run_caco_planning`, calls both agents via `src/my_util/my_a2a.py`, and feeds the responses into `optimize_schedule`. The heuristic sorts jobs by priority, scans feasible slots under power caps and max deferral, and computes cost + carbon scores.
4. **Flex offer generation** – Scheduled flexible jobs are converted into `FlexOffer` instances tagged with power, duration, cluster, and carbon caps.
5. **Catalog publication** – The Beckn server invokes `run_caco_planning` on `search`, then asynchronously POSTs `on_search` to the requesting BAP with a catalog containing each flex offer as a Beckn item.
6. **Commitment** – When the BAP sends `init`/`confirm`, the BPP ACKs immediately and issues `on_init` / `on_confirm` callbacks referencing the chosen order item.

### 2.2 Important Modules
- `src/data_sources/carbon_intensity_client.py` / `bmrs_client.py`: async HTTPX clients with fallback generators for hackathon demos.
- `src/optimization/engine.py`: greedy scheduler + flex offer builder that enforces power caps and penalizes lateness.
- `src/beckn/server.py`: asynchronous Ack/on_* handling, context validation, and callback delivery using an internal `httpx.AsyncClient`.


## 3. Running the Code

### 3.1 Prerequisites
- Python 3.9+  
- [`uv`](https://github.com/astral-sh/uv) for virtualenv + packaging (per project convention)  
- Internet access for Carbon Intensity API (no key) and optional BMRS API key (`BMRS_API_KEY` env var)

### 3.2 Setup
```bash
uv venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\activate
uv pip install -e .
```
Copy or edit environment variables as needed:
```bash
export BMRS_API_KEY="your-key"             # optional
export COMPUTE_AGENT_JOBS_PATH="data/synthetic/workloads.json"
```

### 3.3 CLI Commands (`python main.py ...`)
- `coordination` / `compute` / `grid`: run individual agents (use separate shells).
- `beckn`: start the Beckn BPP FastAPI server (defaults to port 8000).
- `launch --horizon-hours 24`: spin up all agents via multiprocessing, load `data/synthetic/workloads.json`, run a single optimization pass, and print the resulting JSON.

### 3.4 Beckn Flow (manual)
1. Start the Beckn server plus all agents (`coordination`, `compute`, `grid` commands).  
2. A BAP issues `POST /search` to the Beckn server with a valid Beckn `context` and `intent`.  
3. The server immediately responds with Ack, then calls `on_search` at the BAP’s URI once the optimizer returns.  
4. Subsequent `init`/`confirm` follow the same Ack/`on_*` pattern.  
Configure `COORDINATION_AGENT_URL`, `BPP_PROVIDER_ID`, etc., via environment variables if running components on different hosts.


## 4. Expected Inputs

### 4.1 Workload Jobs (`JobSpec`)
```jsonc
{
  "job_id": "job-001",
  "arrival_time": "2025-11-24T06:00:00Z",
  "power_kw": 1500,
  "duration_hours": 4,
  "deadline": "2025-11-24T20:00:00Z",
  "max_deferral_hours": 12,
  "priority": 5,
  "sla_penalty_per_hour": 25,
  "workload_type": "training",
  "cluster_id": "hpc-1"
}
```
Supplied through `ingest_jobs` (JSON over HTTP) or the `COMPUTE_AGENT_JOBS_PATH` bootstrap file.

### 4.2 Grid Forecast Request
```json
{
  "command": "get_grid_forecast",
  "from": "2025-11-24T00:00:00Z",
  "to":   "2025-11-25T00:00:00Z",
  "region": "GB"
}
```

### 4.3 Beckn `/search` Payload (BAP → BPP)
```jsonc
{
  "context": {
    "domain": "nic2004:energy:compute-flex",
    "country": "GB",
    "city": "std:080",
    "action": "search",
    "core_version": "1.0.0",
    "bap_id": "operator.example",
    "bap_uri": "https://operator.example/beckn",
    "bpp_id": "flexcompute-hpc",
    "bpp_uri": "https://bpp.flexcompute.example",
    "transaction_id": "uuid-txn-1",
    "message_id": "uuid-msg-1",
    "timestamp": "2025-11-24T12:00:00Z"
  },
  "message": {
    "intent": {
      "fulfillment": {
        "start": {
          "location": { "city": "std:080" },
          "time": { "range": { "start": "2025-11-24T14:00:00Z", "end": "2025-11-24T22:00:00Z" } }
        }
      },
      "tags": { "power_kw": "2000", "duration_hours": "4", "cluster_id": "hpc-1" }
    }
  }
}
```


## 5. Expected Outputs

### 5.1 Coordination Agent Result (`run_caco_planning`)
```jsonc
{
  "status": "success",
  "window": { "from": "...", "to": "...", "region": "GB" },
  "scheduled_jobs": [
    {
      "job_id": "job-001",
      "start_time": "2025-11-24T07:00:00Z",
      "end_time": "2025-11-24T11:00:00Z",
      "power_kw": 1500,
      "expected_cost_gbp": 145.2,
      "expected_carbon_kg": 120.5,
      "is_flexible_offer": true,
      "metadata": { "lateness_hours": 0, "cluster_id": "hpc-1", "priority": 5 }
    }
  ],
  "flex_offers": [
    {
      "offer_id": "flex-job-001",
      "cluster_id": "hpc-1",
      "power_kw": 1500,
      "duration_hours": 4,
      "earliest_start": "2025-11-24T07:00:00Z",
      "latest_end": "2025-11-24T11:00:00Z",
      "price_gbp_per_mwh": 150,
      "carbon_intensity_cap_g_per_kwh": 90
    }
  ]
}
```

### 5.2 Beckn `on_search` Catalog (BPP → BAP)
```jsonc
{
  "context": { "...", "action": "on_search", "transaction_id": "uuid-txn-1", "message_id": "uuid-msg-2" },
  "message": {
    "catalog": {
      "bpp/descriptor": { "name": "FlexCompute HPC Cluster" },
      "bpp/providers": [
        {
          "id": "flexcompute-hpc",
          "descriptor": { "name": "FlexCompute London Zone" },
          "items": [
            {
              "id": "offer-500kw-4h-150gbp",
              "descriptor": { "name": "500 kW flexible compute (4h window)" },
              "price": { "currency": "GBP", "value": "150.00", "unit": "GBP/MWh" },
              "tags": { "cluster_id": "hpc-1", "power_kw": "500", "duration_hours": "4" }
            }
          ],
          "exp": "2025-11-24T23:59:59Z"
        }
      ]
    }
  }
}
```

### 5.3 Ack/Nack Responses
Every Beckn request (e.g., `POST /search`, `/init`, `/confirm`) receives an immediate Ack:
```json
{ "message": { "ack": { "status": "ACK" } }, "error": null }
```
Errors use `status: "NACK"` with an error object.


## 6. Troubleshooting Tips
- **Agents won’t start** – ensure ports 9001–9003 are free; check environment variables (`COMPUTE_AGENT_JOBS_PATH`, `BMRS_API_KEY`).
- **Beckn callbacks fail** – verify `context.bap_uri` is publicly reachable (or tunnel via ngrok) and that the BAP exposes `/on_search`, `/on_init`, `/on_confirm`.
- **No flex offers** – workloads may lack slack or exceed `max_power_kw`. Inspect `scheduled_jobs` metadata to confirm feasibility.

For further details see inline docstrings across `src/domain`, `src/data_sources`, `src/optimization`, and the README at the project root.

