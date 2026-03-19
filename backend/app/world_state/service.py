"""
World-State Service — in-memory spatial state for VR sessions.

The VR client pushes position updates; the embodiment planner reads them.
Thread-safe via simple locking.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Vector3:
    """3D position."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "Vector3":
        return cls(x=d.get("x", 0.0), y=d.get("y", 0.0), z=d.get("z", 0.0))

    def distance_to(self, other: "Vector3") -> float:
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2 + (self.z - other.z) ** 2) ** 0.5


@dataclass
class Anchor:
    """A spatial anchor (seat, desk, door, etc.)."""
    id: str = ""
    type: str = ""
    position: Vector3 = field(default_factory=Vector3)
    rotation_y_deg: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "position": self.position.to_dict(),
            "rotation_y_deg": self.rotation_y_deg,
        }


@dataclass
class EntityState:
    """Spatial state of an entity (user or avatar)."""
    position: Vector3 = field(default_factory=Vector3)
    head_position: Optional[Vector3] = None
    head_rotation_y_deg: float = 0.0
    left_hand: Optional[Vector3] = None
    right_hand: Optional[Vector3] = None
    velocity_mps: float = 0.0
    state: str = "idle"
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "position": self.position.to_dict(),
            "head_rotation_y_deg": self.head_rotation_y_deg,
            "velocity_mps": self.velocity_mps,
            "state": self.state,
            "updated_at": self.updated_at,
        }
        if self.head_position:
            result["head_position"] = self.head_position.to_dict()
        if self.left_hand:
            result["left_hand"] = self.left_hand.to_dict()
        if self.right_hand:
            result["right_hand"] = self.right_hand.to_dict()
        return result


class WorldStateService:
    """In-memory world state for a single VR session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._user = EntityState()
        self._avatars: Dict[str, EntityState] = {}
        self._anchors: Dict[str, Anchor] = {}

    def update_user(self, data: Dict[str, Any]) -> None:
        with self._lock:
            if "position" in data:
                self._user.position = Vector3.from_dict(data["position"])
            if "head_position" in data:
                self._user.head_position = Vector3.from_dict(data["head_position"])
            if "head_rotation_y_deg" in data:
                self._user.head_rotation_y_deg = data["head_rotation_y_deg"]
            if "left_hand" in data:
                self._user.left_hand = Vector3.from_dict(data["left_hand"])
            if "right_hand" in data:
                self._user.right_hand = Vector3.from_dict(data["right_hand"])
            if "velocity_mps" in data:
                self._user.velocity_mps = data["velocity_mps"]
            self._user.updated_at = time.time()

    def update_avatar(self, persona_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            if persona_id not in self._avatars:
                self._avatars[persona_id] = EntityState()
            avatar = self._avatars[persona_id]
            if "position" in data:
                avatar.position = Vector3.from_dict(data["position"])
            if "state" in data:
                avatar.state = data["state"]
            avatar.updated_at = time.time()

    def set_anchors(self, anchors: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._anchors.clear()
            for a in anchors:
                anchor = Anchor(
                    id=a.get("id", ""),
                    type=a.get("type", ""),
                    position=Vector3.from_dict(a.get("position", {})),
                    rotation_y_deg=a.get("rotation_y_deg", 0.0),
                )
                self._anchors[anchor.id] = anchor

    def get_user(self) -> EntityState:
        with self._lock:
            return self._user

    def get_avatar(self, persona_id: str) -> Optional[EntityState]:
        with self._lock:
            return self._avatars.get(persona_id)

    def get_anchors(self) -> List[Anchor]:
        with self._lock:
            return list(self._anchors.values())

    def find_nearest_anchor(self, anchor_type: str, to: Vector3) -> Optional[Anchor]:
        with self._lock:
            candidates = [a for a in self._anchors.values() if a.type == anchor_type]
            if not candidates:
                return None
            return min(candidates, key=lambda a: a.position.distance_to(to))

    def user_avatar_distance(self, persona_id: str) -> Optional[float]:
        with self._lock:
            avatar = self._avatars.get(persona_id)
            if avatar is None:
                return None
            return self._user.position.distance_to(avatar.position)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "user": self._user.to_dict(),
                "avatars": {k: v.to_dict() for k, v in self._avatars.items()},
                "anchors": [a.to_dict() for a in self._anchors.values()],
            }
