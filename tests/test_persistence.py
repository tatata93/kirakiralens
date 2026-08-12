from __future__ import annotations

import json
import zipfile
from pathlib import Path

from kirakiralens.domain import OpticalDesign
from kirakiralens.persistence import load_project, save_project


def test_project_round_trip_uses_versioned_zip_container(tmp_path: Path) -> None:
    design = OpticalDesign.starter()
    destination = save_project(design, tmp_path / "starter")

    assert destination.suffix == ".kklens"
    with zipfile.ZipFile(destination) as archive:
        payload = json.loads(archive.read("design.json"))
    assert payload["schema_version"] == 1
    assert payload["settings"]["object_distance_mm"] == "infinity"
    restored = load_project(destination)
    assert restored.to_dict() == design.to_dict()
