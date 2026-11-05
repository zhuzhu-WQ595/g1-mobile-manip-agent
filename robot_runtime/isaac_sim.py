from __future__ import annotations

import base64
import io
import json
import math
import os
import urllib.request
from typing import Any, Protocol, runtime_checkable

DEFAULT_PLACES: dict[str, tuple[float, float, float]] = {
    "home": (0.0, 0.0, 0.0),
    "living_room": (3.0, -2.0, 90.0),
    "kitchen": (6.0, 2.0, 180.0),
    "dining_table": (4.02, -1.74, -156.4),
}


@runtime_checkable
class MobileManipBackend(Protocol):
    """Boundary to a mobile manipulation simulator (Isaac Sim) or hardware.

    ``navigate_to`` wraps SLAM localization plus a global/local planner.
    ``run_vla`` wraps a VLA policy rollout that ends on success/timeout.
    Every method returns a JSON-serializable dict with at least ``ok`` and ``message``.
    """

    def get_pose(self) -> dict[str, Any]: ...

    def list_places(self) -> dict[str, Any]: ...

    def navigate_to(self, place: str) -> dict[str, Any]: ...

    def run_vla(self, instruction: str, timeout_s: float = 60.0) -> dict[str, Any]: ...

    def verify_scene(self, question: str = "") -> dict[str, Any]: ...


class MockMobileManipBackend:
    """Deterministic in-memory world: apple is inside the fridge in the kitchen."""

    def __init__(self, places: dict[str, tuple[float, float, float]] | None = None) -> None:
        self.places = dict(places or DEFAULT_PLACES)
        self.pose = {"x": 0.0, "y": 0.0, "yaw_deg": 0.0}
        self.fridge_open = False
        self.apple_location = "fridge"
        self.holding: str | None = None

    def _at(self, place: str) -> bool:
        px, py, _ = self.places[place]
        return math.hypot(self.pose["x"] - px, self.pose["y"] - py) < 0.5

    def get_pose(self) -> dict[str, Any]:
        near = [name for name in self.places if self._at(name)]
        return {"ok": True, "message": "pose read", "pose": dict(self.pose), "at_place": near[0] if near else None, "holding": self.holding}

    def list_places(self) -> dict[str, Any]:
        return {
            "ok": True,
            "message": "semantic places",
            "places": {name: {"x": p[0], "y": p[1], "yaw_deg": p[2]} for name, p in self.places.items()},
        }

    def navigate_to(self, place: str) -> dict[str, Any]:
        key = place.strip().lower()
        if key not in self.places:
            return {"ok": False, "error": "unknown_place", "message": f"unknown place: {place}", "known": sorted(self.places)}
        x, y, yaw = self.places[key]
        self.pose = {"x": x, "y": y, "yaw_deg": yaw}
        return {"ok": True, "message": f"arrived at {key}", "pose": dict(self.pose), "at_place": key}

    def run_vla(self, instruction: str, timeout_s: float = 60.0) -> dict[str, Any]:
        text = instruction.lower()
        at_kitchen = self._at("kitchen")
        if "open" in text and "fridge" in text:
            if not at_kitchen:
                return {"ok": False, "error": "target_not_reachable", "message": "fridge is not within reach; navigate to kitchen first"}
            self.fridge_open = True
            return {"ok": True, "message": "fridge opened"}
        if ("pick" in text or "grasp" in text or "take" in text) and "apple" in text:
            if not at_kitchen:
                return {"ok": False, "error": "target_not_reachable", "message": "apple is not within reach"}
            if self.apple_location == "fridge" and not self.fridge_open:
                return {"ok": False, "error": "occluded", "message": "apple is inside a closed fridge"}
            self.holding = "apple"
            self.apple_location = "gripper"
            return {"ok": True, "message": "apple grasped", "holding": self.holding}
        if "apple" in text and any(k in text for k in ("place", "put", "set down", "lay", "leave")):
            if self.holding != "apple":
                return {"ok": False, "error": "not_holding", "message": "not holding the apple"}
            if not self._at("dining_table"):
                return {"ok": False, "error": "target_not_reachable", "message": "dining table is not within reach"}
            self.holding = None
            self.apple_location = "dining_table"
            return {"ok": True, "message": "apple placed on dining table"}
        if "close" in text and "fridge" in text:
            if not at_kitchen:
                return {"ok": False, "error": "target_not_reachable", "message": "fridge is not within reach"}
            self.fridge_open = False
            return {"ok": True, "message": "fridge closed"}
        return {"ok": False, "error": "unsupported_instruction", "message": f"mock VLA cannot perform: {instruction}"}

    def verify_scene(self, question: str = "") -> dict[str, Any]:
        return {
            "ok": True,
            "message": "visual verification (mock: state only, no camera)",
            "holding": self.holding,
            "fridge_open": self.fridge_open,
            "vision": {"engine": "mock_state", "verdict": f"holding={self.holding}, fridge_open={self.fridge_open}"},
        }


class IsaacSimBackend:
    """HTTP client for a bridge process running inside the Isaac Sim Python env.

    The bridge must expose (JSON in/out):
      GET  /pose                       -> SLAM pose
      GET  /places                     -> semantic map
      POST /navigate {"place": str}    -> blocking nav (SLAM + Nav2/planner)
      POST /vla {"instruction": str, "timeout_s": float} -> blocking VLA rollout
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get("ISAAC_SIM_URL", "http://127.0.0.1:8765")).rstrip("/")

    def get_pose(self) -> dict[str, Any]:
        return self._call("/pose", None, timeout=5.0)

    def list_places(self) -> dict[str, Any]:
        return self._call("/places", None, timeout=5.0)

    def navigate_to(self, place: str) -> dict[str, Any]:
        return self._call("/navigate", {"place": place}, timeout=float(os.environ.get("ISAAC_NAV_TIMEOUT", "180")))

    def run_vla(self, instruction: str, timeout_s: float = 60.0) -> dict[str, Any]:
        return self._call("/vla", {"instruction": instruction, "timeout_s": timeout_s}, timeout=timeout_s + 10.0)

    def capture_scene(self) -> dict[str, Any]:
        return self._call("/camera", None, timeout=30.0)

    def verify_scene(self, question: str = "") -> dict[str, Any]:
        shot = self.capture_scene()
        if not shot.get("ok"):
            return shot
        verdict = self._vision_answer(shot.get("png_b64", ""), question)
        out = {
            "ok": True,
            "message": "visual verification",
            "question": question,
            "vision": verdict,
        }
        for key in ("pose", "at_place", "holding", "fridge_open"):
            if key in shot:
                out[key] = shot[key]
        return out

    def _vision_answer(self, png_b64: str, question: str) -> dict[str, Any]:
        base_url = (os.environ.get("VISION_BASE_URL") or os.environ.get("VLM_BASE_URL") or "").rstrip("/")
        api_key = os.environ.get("VISION_API_KEY") or os.environ.get("VLM_API_KEY") or ""
        model = os.environ.get("VISION_MODEL") or os.environ.get("VLM_MODEL") or ""
        if base_url and api_key and model:
            try:
                return self._vlm_call(base_url, api_key, model, png_b64, question)
            except Exception as exc:  # noqa: BLE001
                heuristic = _heuristic_vision(png_b64, question)
                heuristic["vlm_error"] = str(exc)
                return heuristic
        return _heuristic_vision(png_b64, question)

    @staticmethod
    def _vlm_call(base_url: str, api_key: str, model: str, png_b64: str, question: str) -> dict[str, Any]:
        prompt = (question or "Describe what the robot is doing and whether it is holding the red apple.")
        prompt += " Answer in JSON: {\"observed\": string, \"success\": true/false/null}."
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png_b64}},
                    ],
                }
            ],
            "max_tokens": 300,
        }
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        last_content = ""
        for _attempt in range(2):
            with urllib.request.urlopen(request, timeout=30.0) as response:
                data = json.loads(response.read().decode("utf-8", errors="replace"))
            last_content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            if last_content.strip():
                return {"engine": "vlm", "model": model, "verdict": last_content}
        raise ValueError("VLM returned empty content")

    def _call(self, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=None if payload is None else json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
        if not isinstance(data, dict):
            raise ValueError("Isaac Sim bridge response must be a JSON object")
        return data


def _heuristic_vision(png_b64: str, question: str) -> dict[str, Any]:
    """No-VLM fallback: locate the red apple sphere in the camera frame.

    The demo apple is the only saturated-red object, so red-pixel blob stats
    are a reasonable proxy for 'apple visible / held'.
    """
    try:
        from PIL import Image
    except ImportError:
        return {"engine": "heuristic_red_detector", "error": "PIL not installed", "verdict": "unavailable"}
    try:
        img = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return {"engine": "heuristic_red_detector", "error": f"image decode failed: {exc}", "verdict": "unavailable"}
    w, h = img.size
    minx, miny, maxx, maxy, n, sx, sy = w, h, -1, -1, 0, 0.0, 0.0
    px = img.load()
    for yy in range(h):
        for xx in range(w):
            r, g, b = px[xx, yy][:3]
            if r > 150 and r > g * 1.8 and r > b * 1.8:
                n += 1
                sx += xx
                sy += yy
                minx, miny, maxx, maxy = min(minx, xx), min(miny, yy), max(maxx, xx), max(maxy, yy)
    if n < 30:
        verdict = "no red object visible: apple not in view (occluded or absent)"
    else:
        cx, cy = sx / n / w, sy / n / h
        where = "held in front of robot" if cy > 0.35 and 0.2 < cx < 0.8 else "visible off-centre"
        verdict = f"red blob {n}px at ({cx:.2f},{cy:.2f}) bbox [({minx},{miny})-({maxx},{maxy})]: {where}"
    return {
        "engine": "heuristic_red_detector",
        "note": "no VLM configured; set VISION_BASE_URL/VISION_API_KEY/VISION_MODEL for full scene QA",
        "red_pixels": n,
        "verdict": verdict,
    }


_BACKEND: MobileManipBackend | None = None


def get_mobile_manip_backend() -> MobileManipBackend:
    global _BACKEND
    if _BACKEND is None:
        mode = os.environ.get("MOBILE_MANIP_BACKEND", "mock").strip().lower()
        if mode == "isaac":
            _BACKEND = IsaacSimBackend()
        elif mode == "mock":
            _BACKEND = MockMobileManipBackend()
        else:
            raise RuntimeError(f"Unknown MOBILE_MANIP_BACKEND: {mode}. Available: mock, isaac")
    return _BACKEND


def reset_mobile_manip_backend() -> None:
    global _BACKEND
    _BACKEND = None
