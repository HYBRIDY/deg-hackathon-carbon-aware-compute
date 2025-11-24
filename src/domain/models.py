"""Domain models shared across Grid, Compute, and Coordination agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware datetime in UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def isoformat(value: datetime) -> str:
    """Serialize datetime → ISO-8601 string with Z suffix."""

    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def parse_datetime(raw: str) -> datetime:
    """Parse ISO-8601 string (with optional Z) into UTC datetime."""

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw).astimezone(timezone.utc)


def _convert_sequence(seq: Sequence[Any]) -> List[Any]:
    return [dataclass_to_dict(item) if hasattr(item, "to_dict") else item for item in seq]


def dataclass_to_dict(instance: Any) -> Dict[str, Any]:
    """Convert dataclass to dict, normalizing datetime fields recursively."""

    as_dict: Dict[str, Any] = {}
    for field_name in getattr(instance, "__dataclass_fields__", {}):
        value = getattr(instance, field_name)
        if isinstance(value, datetime):
            as_dict[field_name] = isoformat(value)
        elif hasattr(value, "to_dict"):
            as_dict[field_name] = value.to_dict()
        elif isinstance(value, dict):
            as_dict[field_name] = {
                key: isoformat(val) if isinstance(val, datetime) else val for key, val in value.items()
            }
        elif isinstance(value, (list, tuple)):
            as_dict[field_name] = [
                isoformat(item) if isinstance(item, datetime) else dataclass_to_dict(item) if hasattr(item, "to_dict") else item
                for item in value
            ]
        else:
            as_dict[field_name] = value
    return as_dict


@dataclass(slots=True)
class JobSpec:
    job_id: str
    arrival_time: datetime
    power_kw: float
    duration_hours: float
    deadline: datetime
    max_deferral_hours: float
    priority: int
    sla_penalty_per_hour: float
    workload_type: str
    cluster_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_slots(self) -> int:
        """Number of half-hour slots the job requires."""

        return max(1, int(round(self.duration_hours * 2)))

    @property
    def is_flexible(self) -> bool:
        return self.max_deferral_hours > 0

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "JobSpec":
        return cls(
            job_id=payload["job_id"],
            arrival_time=parse_datetime(payload["arrival_time"]) if isinstance(payload["arrival_time"], str) else payload["arrival_time"],
            power_kw=float(payload["power_kw"]),
            duration_hours=float(payload["duration_hours"]),
            deadline=parse_datetime(payload["deadline"]) if isinstance(payload["deadline"], str) else payload["deadline"],
            max_deferral_hours=float(payload.get("max_deferral_hours", 0)),
            priority=int(payload.get("priority", 0)),
            sla_penalty_per_hour=float(payload.get("sla_penalty_per_hour", 0.0)),
            workload_type=payload.get("workload_type", "batch"),
            cluster_id=payload.get("cluster_id", "default"),
            metadata=payload.get("metadata", {}),
        )


@dataclass(slots=True)
class CarbonPoint:
    timestamp: datetime
    forecast_g_per_kwh: float
    index: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CarbonPoint":
        return cls(
            timestamp=parse_datetime(payload["timestamp"]) if isinstance(payload["timestamp"], str) else payload["timestamp"],
            forecast_g_per_kwh=float(payload["forecast_g_per_kwh"]),
            index=payload.get("index", "unknown"),
        )


@dataclass(slots=True)
class PricePoint:
    timestamp: datetime
    system_buy_price_gbp_per_mwh: float
    system_sell_price_gbp_per_mwh: float

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "PricePoint":
        return cls(
            timestamp=parse_datetime(payload["timestamp"]) if isinstance(payload["timestamp"], str) else payload["timestamp"],
            system_buy_price_gbp_per_mwh=float(payload["system_buy_price_gbp_per_mwh"]),
            system_sell_price_gbp_per_mwh=float(payload["system_sell_price_gbp_per_mwh"]),
        )


@dataclass(slots=True)
class ScheduledJob:
    job_id: str
    start_time: datetime
    end_time: datetime
    power_kw: float
    expected_cost_gbp: float
    expected_carbon_kg: float
    is_flexible_offer: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ScheduledJob":
        return cls(
            job_id=payload["job_id"],
            start_time=parse_datetime(payload["start_time"]) if isinstance(payload["start_time"], str) else payload["start_time"],
            end_time=parse_datetime(payload["end_time"]) if isinstance(payload["end_time"], str) else payload["end_time"],
            power_kw=float(payload["power_kw"]),
            expected_cost_gbp=float(payload.get("expected_cost_gbp", 0.0)),
            expected_carbon_kg=float(payload.get("expected_carbon_kg", 0.0)),
            is_flexible_offer=bool(payload.get("is_flexible_offer", False)),
            metadata=payload.get("metadata", {}),
        )


@dataclass(slots=True)
class FlexOffer:
    offer_id: str
    cluster_id: str
    power_kw: float
    duration_hours: float
    earliest_start: datetime
    latest_end: datetime
    min_activation_notice_minutes: int
    price_gbp_per_mwh: float
    carbon_intensity_cap_g_per_kwh: float
    tags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_to_dict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "FlexOffer":
        return cls(
            offer_id=payload["offer_id"],
            cluster_id=payload.get("cluster_id", "default"),
            power_kw=float(payload["power_kw"]),
            duration_hours=float(payload["duration_hours"]),
            earliest_start=parse_datetime(payload["earliest_start"]) if isinstance(payload["earliest_start"], str) else payload["earliest_start"],
            latest_end=parse_datetime(payload["latest_end"]) if isinstance(payload["latest_end"], str) else payload["latest_end"],
            min_activation_notice_minutes=int(payload.get("min_activation_notice_minutes", 0)),
            price_gbp_per_mwh=float(payload.get("price_gbp_per_mwh", 0.0)),
            carbon_intensity_cap_g_per_kwh=float(payload.get("carbon_intensity_cap_g_per_kwh", 0.0)),
            tags=payload.get("tags", {}),
        )


def align_time_series(series: Iterable[CarbonPoint | PricePoint]) -> List[datetime]:
    """Return ordered timestamps present in provided series."""

    unique = {point.timestamp for point in series}
    return sorted(unique)


