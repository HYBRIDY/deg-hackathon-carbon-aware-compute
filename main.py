"""CLI entry point for the Carbon-Aware Compute Orchestrator (CACO)."""

from __future__ import annotations

import asyncio

import typer
import uvicorn

from src.beckn.server import app as beckn_app
from src.compute_agent import start_compute_agent
from src.coordination_agent import start_coordination_agent
from src.grid_agent import start_grid_agent
from src.launcher import launch_caco_simulation

cli = typer.Typer(help="CACO multi-agent orchestration toolkit.")


@cli.command()
def coordination(host: str = "localhost", port: int = 9001):
    """Start the coordination agent."""

    start_coordination_agent(host=host, port=port)


@cli.command()
def compute(host: str = "localhost", port: int = 9002):
    """Start the compute agent."""

    start_compute_agent(host=host, port=port)


@cli.command()
def grid(host: str = "localhost", port: int = 9003):
    """Start the grid agent."""

    start_grid_agent(host=host, port=port)


@cli.command()
def beckn(host: str = "0.0.0.0", port: int = 8000):
    """Start the Beckn Protocol BPP facade."""

    uvicorn.run(beckn_app, host=host, port=port)


@cli.command()
def launch(horizon_hours: int = 24):
    """Launch a complete CACO simulation (all agents + optimizer run)."""

    asyncio.run(launch_caco_simulation(horizon_hours=horizon_hours))


if __name__ == "__main__":
    cli()
