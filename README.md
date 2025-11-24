# Carbon-Aware Compute Orchestrator (CACO)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Hackathon](https://img.shields.io/badge/DEG%20Hackathon-2025-green.svg)](https://energy.becknprotocol.io/)

> **Multi-agent system for optimizing data center AI workloads with real-time grid energy signals**  
> Submission for **Digital Energy Grid Hackathon 2025** - Problem Statement 2: Compute-Energy Convergence

---

## 🎯 Problem Statement

AI and data centers are now major energy loads. How do we ensure our digital future doesn't destabilize the physical grid that powers it?

**CACO transforms data centers from passive grid loads into active flexibility providers** by intelligently scheduling AI workloads during low-carbon, low-cost periods while maintaining SLA compliance.

---

## 🌟 Key Features

- **🤖 Multi-Agent Architecture**: Compute, Grid, and Coordination agents working in harmony
- **🌱 Carbon-Aware Scheduling**: Minimize g CO₂/inference with real-time grid signals
- **💰 Cost Optimization**: 30-40% reduction in electricity bills
- **⚡ Flexibility Monetization**: Earn £150-250/MWh from P415 grid services
- **🔗 Beckn Protocol Integration**: Publish compute flexibility as tradeable products
- **📊 Real-Time Forecasting**: LSTM-based carbon intensity & price predictions
- **🔐 Blockchain Audit Trail**: Immutable logs for P444 settlement compliance

---

## 📋 Table of Contents

- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Data Sources](#data-sources)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Team](#team)
- [References](#references)

---

## 🏗️ Architecture
```
┌─────────────────────────────────────────────────────────────┐
│                    COMPUTE AGENT                            │
│  Job Queue → Power Estimator → Flexibility Assessor        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     GRID AGENT                              │
│  Carbon API → LSTM Forecaster → Opportunity Detector       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│              OPTIMIZATION ENGINE                            │
│  Minimize: cost + carbon_penalty                            │
│  Subject to: deadlines, SLA, carbon caps                    │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│         COORDINATION AGENT (Beckn Protocol)                 │
│  Catalog Publisher → Order Handler → Settlement Verifier    │
└─────────────────────────────────────────────────────────────┘
                              ↓
                    Grid Operator (UKPN/ESO)
```

**See full architecture diagram:** [docs/DESIGN_DOCUMENT.pdf](docs/DESIGN_DOCUMENT.pdf)

---

### 📁 Code Layout Highlights
- `src/domain/models.py` - shared dataclasses (`JobSpec`, `CarbonPoint`, `FlexOffer`, etc.)
- `src/data_sources/` - async clients for Carbon Intensity API + Elexon BMRS.
- `src/compute_agent/`, `src/grid_agent/`, `src/coordination_agent/` - the three A2A agents.
- `src/optimization/engine.py` - heuristic scheduler producing `ScheduledJob` + `FlexOffer`.
- `src/beckn/server.py` - FastAPI Beckn BPP façade exported via `python main.py beckn`.
- `data/synthetic/workloads.json` - sample AI workloads ingested by the compute agent.

### 🔌 Expected Agent Payloads
```jsonc
// Grid Agent
{ "command": "get_grid_forecast", "from": "...", "to": "...", "region": "GB" }

// Compute Agent
{ "command": "ingest_jobs", "jobs": [ ... JobSpec ... ] }
{ "command": "get_flexibility_profile", "from": "...", "to": "...", "cluster_id": "hpc-1" }

// Coordination Agent
{
  "command": "run_caco_planning",
  "horizon_hours": 24,
  "region": "GB",
  "cluster_id": "hpc-1",
  "optimization": { "carbon_penalty_weight": 0.5, "sla_penalty_weight": 2.0, "max_power_kw": 12000 }
}
```

Each agent responds with JSON strings; the coordination agent emits both optimized schedules and Beckn-ready flexibility offers which the Beckn server publishes as catalog items.

---

### 🔄 Beckn Protocol Flow (Spec-Compliant)
- Every Beckn API (`/search`, `/init`, `/confirm`, …) **immediately ACK/NACKs** with `{"message":{"ack":{"status":"ACK"}}}` while the actual business payload is delivered asynchronously via the matching callback (`/on_search`, `/on_init`, `/on_confirm`).  
- `context` objects follow the Beckn Core 1.0.0 schema (`domain`, `country`, `city`, `action`, `core_version`, `bap_id`, `bpp_id`, `transaction_id`, `message_id`, `timestamp`, `ttl`). The **transaction id stays constant** across the entire flow; callback message IDs are regenerated.
- `/search` requests expect Beckn’s canonical intent shape (`message.intent.fulfillment.start.location/time`, optional `intent.tags` for power/duration filters). The BPP turns the resulting flexibility offers into proper Beckn catalog items under `message.catalog["bpp/providers"]`.
- Example interaction:
  1. BAP `POST /search` (intent describes time/location & tags like `power_kw`, `duration_hours`).
  2. CACO BPP returns `ACK` immediately and, once the optimizer finishes, calls `POST {bap_uri}/on_search` with the catalog.
  3. BAP `POST /init` with selected `order`; BPP ACKs and later invokes `{bap_uri}/on_init`.
  4. BAP `POST /confirm`; BPP ACKs and follows up with `{bap_uri}/on_confirm` that includes the committed fulfillment.

This keeps the prototype faithful to the Beckn asynchronous contract while still allowing the coordination agent to perform multi-minute optimizations before publishing the catalog.

---

## 🚀 Installation

### Prerequisites

- Python 3.9+
- Git
- (Optional) Docker for containerized deployment

### Clone Repository
```bash
git clone https://github.com/YOUR_USERNAME/deg-hackathon-carbon-aware-compute.git
cd deg-hackathon-carbon-aware-compute
```

### Install Dependencies
```bash
# Create uv-managed virtual environment
uv venv
.\.venv\Scripts\activate  # macOS/Linux: source .venv/bin/activate

# Install project in editable mode
uv pip install -e .
```

### Environment Setup
```bash
# Copy example config
cp config/config.example.yaml config/config.yaml

# Add API keys (optional for MVP)
# - Carbon Intensity API: https://carbonintensity.org.uk (no key needed)
# - Elexon BMRS: Register at https://bmreports.com
```

---

## ⚡ Quick Start

### 1. Generate Synthetic Data
```bash
python scripts/generate_synthetic_data.py --days 30 --output data/synthetic/
```

### 2. Launch the full CACO simulation
```bash
uv run python main.py launch --horizon-hours 24
```

### 3. Start individual agents (optional)
```bash
# in separate shells
uv run python main.py coordination
uv run python main.py compute
uv run python main.py grid
uv run python main.py beckn --port 8000
```

`main.py` is a Typer CLI, so `uv run python main.py --help` lists all available commands.

---

## 📚 Documentation

- **[Design Document (PDF)](docs/DESIGN_DOCUMENT.pdf)** - Complete hackathon submission
- **[Architecture Guide](docs/ARCHITECTURE.md)** - Detailed component breakdown
- **[API Reference](docs/API.md)** - Agent interfaces and Beckn endpoints
- **[User Guide](docs/USER_GUIDE.md)** - How to use CACO in production
- **[Contributing Guide](CONTRIBUTING.md)** - Development workflow

---

## 🌐 Data Sources

| Source | Purpose | API/Link | Cost |
|--------|---------|----------|------|
| **UK Carbon Intensity API** | Real-time & forecast grid carbon | https://carbonintensity.org.uk | Free |
| **Elexon BMRS** | Imbalance pricing, system frequency | https://api.bmreports.com | Free (registration) |
| **Azure Workload Traces** | Historical compute job patterns | https://github.com/Azure/AzurePublicDataset | Free |
| **Google Cluster Traces** | Job scheduling baselines | https://github.com/google/cluster-data | Free |
| **Met Office DataPoint** | Weather forecasts (cooling load) | https://www.metoffice.gov.uk/datapoint | £ (optional) |

---

## 🗺️ Roadmap

### ✅ Phase 1: MVP (Weeks 1-2)
- [x] Synthetic data generation
- [x] Rule-based scheduler
- [x] Carbon Intensity API integration
- [x] Basic dashboard

### 🚧 Phase 2: ML Integration (Weeks 3-4)
- [ ] LSTM forecasting model
- [ ] XGBoost job predictor
- [ ] CVXPY optimization solver
- [ ] Performance benchmarking

### 📅 Phase 3: Beckn Protocol (Weeks 5-6)
- [ ] Catalog publisher
- [ ] Order handler (P415 activation)
- [ ] Mock grid operator
- [ ] Settlement verification

### 🎯 Phase 4: Pilot (Weeks 7-8)
- [ ] University HPC cluster deployment
- [ ] Real AI workload testing
- [ ] Cost/carbon measurement
- [ ] Blockchain audit trail

### 🚀 Phase 5: Production (Post-Hackathon)
- [ ] Cloud provider partnership
- [ ] Multi-region orchestration
- [ ] Commercial SaaS platform
- [ ] P415 market integration

---

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup
```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run tests
pytest tests/

# Run linter
flake8 src/

# Format code
black src/
```

### Current Needs

- **Data Scientists**: Improve forecasting models
- **Energy Experts**: Validate grid integration logic
- **DevOps**: Kubernetes deployment, CI/CD pipeline
- **Frontend**: Enhance dashboard visualizations

---

## 📄 License

This project is licensed under the **MIT License** - see [LICENSE](LICENSE) file for details.

**TL;DR**: You can use, modify, and distribute this software freely, even commercially, as long as you include the original license.

---

## 👥 Team

**FlexCompute Labs** - DEG Hackathon 2025

| Name | Role | LinkedIn | GitHub |
|------|------|----------|--------|
| Xiaoyi Sun | AI/ML Engineer | https://www.linkedin.com/in/xiaoyi-sun-xs522 | https://github.com/weepsdanky |
| Charles Cai | Energy Analyst | [Link] | https://github.com/charles-cai |
| Mathew Obasuyi | Backend Dev | https://gravatar.com/cyrilobasuyi1 | https://github.com/Megabrain256 |
| Khin Saw | Data Scientist | https://www.linkedin.com/in/khin-s-3946a161/ |  [link]|

**Contact:** brainiac@hybridy.site | **Discord:** divineseal040

---

## 📖 References

### Academic Research
- Microsoft Research: *Carbon Explorer* (2024)
- Meta AI: *Chasing Carbon* (2023)
- Google: *24/7 Carbon-Free Energy* Methodology

### Standards & Protocols
- [Beckn Protocol v1.1](https://becknprotocol.io)
- [BSC P415](https://www.elexon.co.uk/mod-proposal/p415/) - VLP for DER Aggregation
- [BSC P444](https://www.elexon.co.uk/mod-proposal/p444/) - Half-Hourly Settlement

### DEG Initiative
- [FIDE-IEA Digital Energy Grid Paper](https://energy.becknprotocol.io/wp-content/uploads/2025/01/DIGITAL_fide-deg-paper-250212-v13-1.pdf)
- [Unified Energy Interface](https://ueialliance.org/)

---

## 🏆 Hackathon Submission

**Event:** Digital Energy Grid Hackathon 2025  
**Problem:** #2 - Compute-Energy Convergence  
**Platform:** [Dora Hacks](https://dorahacks.io)  
**Deadline:** 23 Nov 2025, 17:00 GMT  

**Submission Materials:**
- [Design Document (PDF)](docs/DESIGN_DOCUMENT.pdf)
- [Pitch Deck (optional)](docs/PITCH_DECK.pdf)
- [Demo Video (optional)](https://youtu.be/your-video-id)

---

## 📊 Impact Metrics (Projected)

| Metric | Value | Basis |
|--------|-------|-------|
| **Cost Reduction** | 30-40% | Shift to low-price periods |
| **Carbon Reduction** | 60-70% | Schedule during renewable surplus |
| **Flexibility Revenue** | £200k/year | P415 market rates (2 MW capacity) |
| **Grid Benefit** | 20-30 MW | Per 100 MW data center cluster |
| **Emissions Avoided** | 150k tons CO₂/yr | If 10% of UK data centers adopt |

---

## 🌍 Sustainability Statement

CACO directly contributes to:
- **UN SDG 7**: Affordable and Clean Energy
- **UN SDG 9**: Industry, Innovation, Infrastructure
- **UN SDG 13**: Climate Action

By enabling 24/7 carbon-free computing and transforming data centers into grid stability assets, we're building the infrastructure for a sustainable AI future.

---

## ⭐ Star This Repo!

If you find this project interesting, please give it a star ⭐ and share it with your network!

---

**Built with ❤️ for the Digital Energy Grid | Powered by Beckn Protocol | Carbon-Aware Computing FTW 🌱**
