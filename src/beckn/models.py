"""Lightweight Beckn data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from src.domain import isoformat


@dataclass
class BecknContext:
    domain: str
    country: str
    city: str
    action: str
    core_version: str
    bap_id: str
    bap_uri: str
    bpp_id: str
    bpp_uri: str
    transaction_id: str
    message_id: str
    timestamp: str
    ttl: str | None = "PT30S"
    key: str | None = None

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BecknContext":
        return cls(
            domain=payload["domain"],
            country=payload["country"],
            city=payload["city"],
            action=payload["action"],
            core_version=payload["core_version"],
            bap_id=payload["bap_id"],
            bap_uri=payload["bap_uri"],
            bpp_id=payload.get("bpp_id", ""),
            bpp_uri=payload.get("bpp_uri", ""),
            transaction_id=payload["transaction_id"],
            message_id=payload["message_id"],
            timestamp=payload["timestamp"],
            ttl=payload.get("ttl", "PT30S"),
            key=payload.get("key"),
        )

    def with_action(self, *, action: str, message_id: str) -> "BecknContext":
        return BecknContext(
            domain=self.domain,
            country=self.country,
            city=self.city,
            action=action,
            core_version=self.core_version,
            bap_id=self.bap_id,
            bap_uri=self.bap_uri,
            bpp_id=self.bpp_id,
            bpp_uri=self.bpp_uri,
            transaction_id=self.transaction_id,
            message_id=message_id,
            timestamp=isoformat(datetime.now(timezone.utc)),
            ttl=self.ttl,
            key=self.key,
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "domain": self.domain,
            "country": self.country,
            "city": self.city,
            "action": self.action,
            "core_version": self.core_version,
            "bap_id": self.bap_id,
            "bap_uri": self.bap_uri,
            "bpp_id": self.bpp_id,
            "bpp_uri": self.bpp_uri,
            "transaction_id": self.transaction_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }
        if self.ttl is not None:
            data["ttl"] = self.ttl
        if self.key is not None:
            data["key"] = self.key
        return data


@dataclass
class BecknItem:
    id: str
    descriptor: Dict[str, Any]
    price: Dict[str, Any]
    tags: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "descriptor": self.descriptor,
            "price": self.price,
            "tags": self.tags,
        }


@dataclass
class BecknCatalog:
    descriptor: Dict[str, Any]
    providers: List[Dict[str, Any]]
    expires_at: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "bpp/descriptor": self.descriptor,
            "bpp/providers": self.providers,
        }
        if self.expires_at:
            payload["exp"] = self.expires_at
        return payload

