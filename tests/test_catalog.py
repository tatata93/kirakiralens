from __future__ import annotations

import csv
from pathlib import Path

from kirakiralens.catalog.database import CatalogRepository
from kirakiralens.catalog.edmund import import_edmund_catalog, parse_float, parse_product


def test_numeric_parser_keeps_nominal_value() -> None:
    assert parse_float("12.50 +0.0/-0.025") == 12.5
    assert parse_float("-18.64 ") == -18.64
    assert parse_float(None) is None


def test_achromat_is_parsed_as_three_surfaces() -> None:
    product = parse_product(
        {
            "タイトル": "Achromat",
            "商品コード": "TEST-1",
            "タイプ": "Achromatic Lens",
            "直径 (mm)": "20.0 +0/-0.025",
            "CA (mm)": "18.0",
            "CT 1 (mm)": "3.0 ±0.1",
            "CT 2 (mm)": "2.0 ±0.1",
            "曲率半径 R1 (mm)": "30",
            "曲率半径 R2 (mm)": "-20",
            "曲率半径 R3 (mm)": "-50",
            "基板": "N-BK7 / N-SF5",
        }
    )

    assert product.designable
    assert [(s.radius_mm, s.material_after, s.thickness_after_mm) for s in product.surfaces] == [
        (30.0, "N-BK7", 3.0),
        (-20.0, "N-SF5", 2.0),
        (-50.0, "air", 0.0),
    ]


def test_supplied_edmund_files_import_to_normalized_database(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    database = tmp_path / "catalog.sqlite3"
    csv_path = tmp_path / "catalog.csv"
    report_path = tmp_path / "report.json"
    report = import_edmund_catalog(
        repository_root / "data" / "source" / "edmund",
        database,
        csv_path,
        report_path,
    )

    repository = CatalogRepository(database)
    assert repository.count_products() == 920
    assert report.accepted == 918
    assert report.incomplete == 2
    achromat = repository.query_products(search="84-125", limit=1)[0]
    element = repository.element_from_product(achromat.id)
    assert len(element.surfaces) == 3
    assert [surface.material_after for surface in element.surfaces] == ["N-PSK53A", "N-LASF9", "air"]
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        assert sum(1 for _ in csv.DictReader(source)) == 920
