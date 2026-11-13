"""Image-generation task registry with persistence.

Statuses (never collapses "timeout" into "failed" or "success"):
  submitted        — accepted by the local pipeline, message not yet acked
  pending          — delivered to Muse, generation in progress
  approval_required — Muse VM is waiting for a human egress approval
  completed        — reply finished; images[] holds the public links (+paths once downloaded)
  timeout          — wait window elapsed while Muse was still working; task is
                     kept and re-pollable (NOT lost, NOT failed)
  failed           — the send itself failed; nothing was delivered
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

STATUSES = ("submitted", "pending", "approval_required", "completed", "timeout", "failed")


class TaskStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else Path("~/.config/muse-agent/tasks.json").expanduser()
        self.tasks: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self.tasks = data
            except (json.JSONDecodeError, OSError):
                self.tasks = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.tasks, indent=1, ensure_ascii=False))

    def create(self, prompt: str, session_id: str) -> dict:
        task_id = uuid.uuid4().hex[:16]
        task = {
            "task_id": task_id,
            "session_id": session_id,
            "prompt": prompt,
            "status": "submitted",
            "created_at": time.time(),
            "updated_at": time.time(),
            "sent_prompt": False,
            "reply": "",
            "images": [],       # {url,label,mime,width,height,byte_len,path}
            "approvals": [],    # latest pending approvals observed
            "error": "",
        }
        self.tasks[task_id] = task
        self._save()
        return task

    def get(self, task_id: str) -> dict | None:
        return self.tasks.get(task_id)

    def update(self, task_id: str, **fields) -> dict:
        task = self.tasks[task_id]
        for key, value in fields.items():
            if key == "status" and value not in STATUSES:
                raise ValueError(f"unknown status {value!r}")
            task[key] = value
        task["updated_at"] = time.time()
        self._save()
        return task

    def add_images(self, task_id: str, images: list[dict]) -> list[dict]:
        """Merge newly seen images (dedupe by URL, also within one batch)."""
        task = self.tasks[task_id]
        known = {i["url"] for i in task["images"]}
        fresh = []
        for i in images:
            if i.get("url") and i["url"] not in known:
                known.add(i["url"])
                fresh.append(i)
        task["images"].extend(fresh)
        task["updated_at"] = time.time()
        self._save()
        return fresh

    def mark_image_path(self, task_id: str, url: str, path: str) -> None:
        for image in self.tasks[task_id]["images"]:
            if image["url"] == url:
                image["path"] = path
        self._save()
