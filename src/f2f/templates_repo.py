from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path

from f2f.models import PillarTemplate

SEED_PATH = Path(__file__).resolve().parent / "data" / "templates.seed.json"


class TemplateRepo:
    """Pillar templates persisted to a JSON file. Holds no candidate data."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SEED_PATH, path)

    def all(self) -> list[PillarTemplate]:
        with self._lock:
            data = json.loads(self.path.read_text())
        return [PillarTemplate.model_validate(p) for p in data["pillars"]]

    def get(self, key: str) -> PillarTemplate | None:
        return next((p for p in self.all() if p.key == key), None)

    def save(self, template: PillarTemplate) -> None:
        pillars = self.all()
        pillars = [template if p.key == template.key else p for p in pillars]
        if all(p.key != template.key for p in pillars):
            pillars.append(template)
        payload = {"pillars": [p.model_dump() for p in pillars]}
        tmp = self.path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
            tmp.replace(self.path)
