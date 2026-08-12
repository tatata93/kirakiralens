from __future__ import annotations

from pathlib import Path

from kirakiralens.domain import OpticalDesign
from kirakiralens.optics.optiland_adapter import OptilandAdapter
from kirakiralens.optics.paraxial import trace_parallel_rays


def test_starter_prescription_matches_initial_targets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))
    design = OpticalDesign.starter()
    result = OptilandAdapter().analyze_first_order(design)

    assert result.valid, result.error
    assert result.engine == "Optiland 0.5.9"
    assert abs(result.effective_focal_length_mm - 50.0) < 0.01
    assert abs(result.back_focal_length_mm - 45.46) < 0.01
    rays = trace_parallel_rays(design, result.refractive_indices)
    assert len(rays) == 5
    assert all(len(ray) == 7 for ray in rays)
