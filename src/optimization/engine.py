"""Heuristic optimization engine for scheduling workloads vs. grid signals."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Sequence, Tuple

from src.domain import (
    CarbonPoint,
    FlexOffer,
    JobSpec,
    PricePoint,
    ScheduledJob,
    isoformat,
)

SLOT_DURATION = timedelta(minutes=30)
SLOT_HOURS = SLOT_DURATION.total_seconds() / 3600


def optimize_schedule(
    jobs: Sequence[JobSpec],
    carbon_series: Sequence[CarbonPoint],
    price_series: Sequence[PricePoint],
    *,
    carbon_penalty_weight: float,
    sla_penalty_weight: float,
    max_power_kw: float,
) -> Tuple[List[ScheduledJob], List[FlexOffer]]:
    """Return heuristic schedule + flex offers."""

    if not jobs:
        return [], []

    timeline, price_lookup, carbon_lookup = _build_timeline(carbon_series, price_series)
    if not timeline:
        return [], []

    power_usage = [0.0 for _ in timeline]
    scheduled_jobs: List[ScheduledJob] = []

    # Prioritize higher priority / shorter duration workloads
    sorted_jobs = sorted(
        jobs,
        key=lambda job: (-job.priority, job.duration_hours, job.arrival_time),
    )

    for job in sorted_jobs:
        start_index, lateness_hours = _select_start_index(
            job,
            timeline,
            price_lookup,
            carbon_lookup,
            power_usage,
            max_power_kw,
            carbon_penalty_weight,
            sla_penalty_weight,
        )
        if start_index is None:
            continue

        slot_count = job.duration_slots
        start_time = timeline[start_index]
        end_time = timeline[start_index + slot_count - 1] + SLOT_DURATION
        job_energy_kwh = job.power_kw * job.duration_hours

        # Compute aggregate price / carbon
        price_cost = 0.0
        carbon_cost = 0.0
        for offset in range(slot_count):
            idx = start_index + offset
            slot_price = price_lookup[timeline[idx]]
            slot_carbon = carbon_lookup[timeline[idx]]
            slot_energy = job.power_kw * SLOT_HOURS
            price_cost += slot_price * slot_energy
            carbon_cost += slot_carbon * slot_energy / 1000  # g → kg
            power_usage[idx] += job.power_kw

        scheduled_jobs.append(
            ScheduledJob(
                job_id=job.job_id,
                start_time=start_time,
                end_time=end_time,
                power_kw=job.power_kw,
                expected_cost_gbp=round(price_cost, 2),
                expected_carbon_kg=round(carbon_cost, 3),
                is_flexible_offer=job.is_flexible,
                metadata={
                    "lateness_hours": lateness_hours,
                    "cluster_id": job.cluster_id,
                    "priority": job.priority,
                },
            )
        )

    flex_offers = _flex_offers_from_schedule(
        scheduled_jobs,
        carbon_lookup,
        price_lookup,
        carbon_penalty_weight,
    )
    return scheduled_jobs, flex_offers


def _build_timeline(
    carbon_series: Sequence[CarbonPoint],
    price_series: Sequence[PricePoint],
) -> Tuple[List[datetime], Dict[datetime, float], Dict[datetime, float]]:
    timestamps = sorted({point.timestamp for point in carbon_series} | {point.timestamp for point in price_series})
    if not timestamps:
        return [], {}, {}

    price_map = {point.timestamp: point.system_buy_price_gbp_per_mwh / 1000 for point in price_series}  # GBP/kWh
    carbon_map = {point.timestamp: point.forecast_g_per_kwh for point in carbon_series}

    # Fill missing slots by forward filling last known value
    filled_prices: Dict[datetime, float] = {}
    filled_carbons: Dict[datetime, float] = {}
    last_price = next(iter(price_map.values()))
    last_carbon = next(iter(carbon_map.values()))

    for ts in timestamps:
        if ts in price_map:
            last_price = price_map[ts]
        if ts in carbon_map:
            last_carbon = carbon_map[ts]
        filled_prices[ts] = last_price
        filled_carbons[ts] = last_carbon

    return timestamps, filled_prices, filled_carbons


def _select_start_index(
    job: JobSpec,
    timeline: Sequence[datetime],
    price_lookup: Dict[datetime, float],
    carbon_lookup: Dict[datetime, float],
    power_usage: List[float],
    max_power_kw: float,
    carbon_penalty_weight: float,
    sla_penalty_weight: float,
) -> Tuple[int | None, float]:
    slot_count = job.duration_slots
    best_index = None
    best_score = math.inf
    best_lateness = 0.0

    for idx, slot_start in enumerate(timeline):
        if idx + slot_count > len(timeline):
            break
        if slot_start < job.arrival_time:
            continue

        slot_end = timeline[idx + slot_count - 1] + SLOT_DURATION
        lateness_hours = max(0.0, (slot_end - job.deadline).total_seconds() / 3600)
        if lateness_hours > job.max_deferral_hours and job.max_deferral_hours > 0:
            continue

        # Power cap constraint
        if any(power_usage[idx + offset] + job.power_kw > max_power_kw for offset in range(slot_count)):
            continue

        score = 0.0
        for offset in range(slot_count):
            ts = timeline[idx + offset]
            slot_energy = job.power_kw * SLOT_HOURS
            slot_price = price_lookup[ts]
            slot_carbon = carbon_lookup[ts]
            score += slot_price * slot_energy
            score += carbon_penalty_weight * slot_carbon * slot_energy / 1000

        # SLA penalty
        score += (sla_penalty_weight + job.sla_penalty_per_hour) * lateness_hours

        if score < best_score:
            best_score = score
            best_index = idx
            best_lateness = lateness_hours

    return best_index, best_lateness


def _flex_offers_from_schedule(
    scheduled_jobs: Iterable[ScheduledJob],
    carbon_lookup: Dict[datetime, float],
    price_lookup: Dict[datetime, float],
    carbon_penalty_weight: float,
) -> List[FlexOffer]:
    offers: List[FlexOffer] = []
    for job in scheduled_jobs:
        if not job.is_flexible_offer:
            continue

        avg_price = _average_value_between(price_lookup, job.start_time, job.end_time)
        max_carbon = _average_value_between(carbon_lookup, job.start_time, job.end_time)
        offers.append(
            FlexOffer(
                offer_id=f"flex-{job.job_id}",
                cluster_id=job.metadata.get("cluster_id", "default"),
                power_kw=job.power_kw,
                duration_hours=(job.end_time - job.start_time).total_seconds() / 3600,
                earliest_start=job.start_time,
                latest_end=job.end_time,
                min_activation_notice_minutes=60,
                price_gbp_per_mwh=max(1.0, avg_price * 1000 * (1 + carbon_penalty_weight / 10)),
                carbon_intensity_cap_g_per_kwh=max_carbon,
                tags={
                    "job_id": job.job_id,
                    "scheduled_start": isoformat(job.start_time),
                },
            )
        )
    return offers


def _average_value_between(values: Dict[datetime, float], start: datetime, end: datetime) -> float:
    selected = [val for ts, val in values.items() if start <= ts <= end]
    if not selected:
        return next(iter(values.values())) if values else 0.0
    return sum(selected) / len(selected)


