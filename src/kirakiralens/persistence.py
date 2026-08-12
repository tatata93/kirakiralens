from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .domain import OpticalDesign


PROJECT_MEMBER = "design.json"


def save_project(design: OpticalDesign, path: str | Path) -> Path:
    destination = Path(path)
    if destination.suffix.lower() != ".kklens":
        destination = destination.with_suffix(".kklens")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(design.to_dict(), ensure_ascii=False, indent=2, allow_nan=False)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(PROJECT_MEMBER, payload.encode("utf-8"))
    return destination


def load_project(path: str | Path) -> OpticalDesign:
    with zipfile.ZipFile(Path(path), "r") as archive:
        payload = json.loads(archive.read(PROJECT_MEMBER).decode("utf-8"))
    return OpticalDesign.from_dict(payload)
