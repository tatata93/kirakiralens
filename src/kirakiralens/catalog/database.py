from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..domain import LensElement, SurfaceSpec


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS manufacturers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    source_kind TEXT NOT NULL,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    incomplete_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturers(id),
    part_number TEXT NOT NULL,
    title TEXT NOT NULL,
    product_type TEXT NOT NULL,
    shape TEXT NOT NULL,
    outer_diameter_mm REAL,
    clear_aperture_mm REAL,
    effective_focal_length_mm REAL,
    back_focal_length_mm REAL,
    coating TEXT,
    wavelength_min_nm REAL,
    wavelength_max_nm REAL,
    reference_wavelength_nm REAL,
    designable INTEGER NOT NULL DEFAULT 1,
    raw_json TEXT NOT NULL,
    UNIQUE(manufacturer_id, part_number)
);

CREATE TABLE IF NOT EXISTS surfaces (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    surface_index INTEGER NOT NULL,
    radius_mm REAL,
    material_after TEXT NOT NULL,
    thickness_after_mm REAL NOT NULL DEFAULT 0,
    clear_aperture_mm REAL,
    coating TEXT,
    UNIQUE(product_id, surface_index)
);

CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    import_run_id INTEGER NOT NULL REFERENCES import_runs(id),
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_shape ON products(shape);
CREATE INDEX IF NOT EXISTS idx_products_diameter ON products(outer_diameter_mm);
CREATE INDEX IF NOT EXISTS idx_surfaces_material ON surfaces(material_after);
"""


@dataclass(slots=True)
class CatalogProduct:
    id: int
    manufacturer: str
    part_number: str
    title: str
    product_type: str
    shape: str
    outer_diameter_mm: float | None
    clear_aperture_mm: float | None
    effective_focal_length_mm: float | None
    back_focal_length_mm: float | None
    coating: str
    wavelength_min_nm: float | None
    wavelength_max_nm: float | None
    materials: str
    designable: bool


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


class CatalogRepository:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def available(self) -> bool:
        return self.database_path.exists()

    def query_products(
        self,
        search: str = "",
        shape: str = "",
        material: str = "",
        coating: str = "",
        min_diameter_mm: float | None = None,
        max_diameter_mm: float | None = None,
        min_clear_aperture_mm: float | None = None,
        min_efl_mm: float | None = None,
        max_efl_mm: float | None = None,
        power: str = "",
        wavelength_nm: float | None = None,
        manufacturer: str = "",
        designable_only: bool = True,
        sort: str = "target_efl",
        target_efl_mm: float = 50.0,
        limit: int = 1000,
    ) -> list[CatalogProduct]:
        if not self.available():
            return []
        clauses: list[str] = []
        params: list[object] = []
        if search:
            clauses.append("(p.part_number LIKE ? OR p.title LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        if shape:
            clauses.append("p.shape = ?")
            params.append(shape)
        if material:
            clauses.append("EXISTS (SELECT 1 FROM surfaces sm WHERE sm.product_id=p.id AND sm.material_after=?)")
            params.append(material)
        if coating:
            clauses.append("p.coating = ?")
            params.append(coating)
        if min_diameter_mm is not None:
            clauses.append("p.outer_diameter_mm >= ?")
            params.append(min_diameter_mm)
        if max_diameter_mm is not None:
            clauses.append("p.outer_diameter_mm <= ?")
            params.append(max_diameter_mm)
        if min_clear_aperture_mm is not None:
            clauses.append("p.clear_aperture_mm >= ?")
            params.append(min_clear_aperture_mm)
        if min_efl_mm is not None:
            clauses.append("p.effective_focal_length_mm >= ?")
            params.append(min_efl_mm)
        if max_efl_mm is not None:
            clauses.append("p.effective_focal_length_mm <= ?")
            params.append(max_efl_mm)
        if power == "positive":
            clauses.append("p.effective_focal_length_mm > 0")
        elif power == "negative":
            clauses.append("p.effective_focal_length_mm < 0")
        if wavelength_nm is not None:
            clauses.append("p.wavelength_min_nm <= ? AND p.wavelength_max_nm >= ?")
            params.extend([wavelength_nm, wavelength_nm])
        if manufacturer:
            clauses.append("m.name = ?")
            params.append(manufacturer)
        if designable_only:
            clauses.append("p.designable = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order_by = {
            "target_efl": "ABS(ABS(COALESCE(p.effective_focal_length_mm, 1e9)) - ?), p.outer_diameter_mm DESC, p.part_number",
            "diameter_desc": "p.outer_diameter_mm DESC, ABS(COALESCE(p.effective_focal_length_mm, 1e9)), p.part_number",
            "efl_asc": "p.effective_focal_length_mm, p.outer_diameter_mm DESC, p.part_number",
            "part_number": "m.name, p.part_number",
        }.get(sort, "ABS(ABS(COALESCE(p.effective_focal_length_mm, 1e9)) - ?), p.outer_diameter_mm DESC, p.part_number")
        if sort == "target_efl" or sort not in {"diameter_desc", "efl_asc", "part_number"}:
            params.append(abs(target_efl_mm))
        query = f"""
            SELECT p.*, m.name AS manufacturer,
                   GROUP_CONCAT(DISTINCT CASE WHEN s.material_after != 'air' THEN s.material_after END) AS materials
            FROM products p
            JOIN manufacturers m ON m.id=p.manufacturer_id
            LEFT JOIN surfaces s ON s.product_id=p.id
            {where}
            GROUP BY p.id
            ORDER BY {order_by}
            LIMIT ?
        """
        params.append(limit)
        with connect(self.database_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            CatalogProduct(
                id=row["id"],
                manufacturer=row["manufacturer"],
                part_number=row["part_number"],
                title=row["title"],
                product_type=row["product_type"],
                shape=row["shape"],
                outer_diameter_mm=row["outer_diameter_mm"],
                clear_aperture_mm=row["clear_aperture_mm"],
                effective_focal_length_mm=row["effective_focal_length_mm"],
                back_focal_length_mm=row["back_focal_length_mm"],
                coating=row["coating"] or "",
                wavelength_min_nm=row["wavelength_min_nm"],
                wavelength_max_nm=row["wavelength_max_nm"],
                materials=row["materials"] or "",
                designable=bool(row["designable"]),
            )
            for row in rows
        ]

    def filter_values(self, column: str) -> list[str]:
        if not self.available():
            return []
        with connect(self.database_path) as connection:
            if column == "shape":
                rows = connection.execute("SELECT DISTINCT shape FROM products ORDER BY shape").fetchall()
            elif column == "manufacturer":
                rows = connection.execute("SELECT name FROM manufacturers ORDER BY name").fetchall()
            elif column == "material":
                rows = connection.execute(
                    "SELECT DISTINCT material_after FROM surfaces WHERE material_after != 'air' ORDER BY material_after"
                ).fetchall()
            elif column == "coating":
                rows = connection.execute(
                    "SELECT DISTINCT coating FROM products WHERE coating != '' ORDER BY coating"
                ).fetchall()
            else:
                raise ValueError(f"Unsupported filter column: {column}")
        return [str(row[0]) for row in rows if row[0]]

    def element_from_product(self, product_id: int) -> LensElement:
        with connect(self.database_path) as connection:
            product = connection.execute(
                """
                SELECT p.*, m.name AS manufacturer
                FROM products p JOIN manufacturers m ON m.id=p.manufacturer_id
                WHERE p.id=?
                """,
                (product_id,),
            ).fetchone()
            if product is None:
                raise KeyError(f"Unknown catalog product {product_id}")
            rows = connection.execute(
                "SELECT * FROM surfaces WHERE product_id=? ORDER BY surface_index",
                (product_id,),
            ).fetchall()
        surfaces = [
            SurfaceSpec(
                radius_mm=row["radius_mm"],
                material_after=row["material_after"],
                thickness_after_mm=row["thickness_after_mm"],
                clear_aperture_mm=row["clear_aperture_mm"],
                coating=row["coating"] or "",
                radius_locked=True,
                thickness_locked=True,
                material_locked=True,
                clear_aperture_locked=True,
            )
            for row in rows
        ]
        return LensElement(
            name=product["title"],
            manufacturer=product["manufacturer"],
            part_number=product["part_number"],
            shape=product["shape"],
            catalog_product_id=product["id"],
            is_catalog=True,
            surfaces=surfaces,
            outer_diameter_mm=product["outer_diameter_mm"],
            diameter_locked=True,
            gap_after_mm=2.0,
        )

    def count_products(self) -> int:
        if not self.available():
            return 0
        with connect(self.database_path) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM products").fetchone()[0])


def insert_surfaces(
    connection: sqlite3.Connection,
    product_id: int,
    surfaces: Iterable[SurfaceSpec],
) -> None:
    connection.executemany(
        """
        INSERT INTO surfaces(
            product_id, surface_index, radius_mm, material_after,
            thickness_after_mm, clear_aperture_mm, coating
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                product_id,
                index,
                surface.radius_mm,
                surface.material_after,
                surface.thickness_after_mm,
                surface.clear_aperture_mm,
                surface.coating,
            )
            for index, surface in enumerate(surfaces)
        ],
    )


def raw_json(data: dict[str, object]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
