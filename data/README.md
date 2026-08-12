# Catalog data

## Source

`source/edmund/` contains the ten original Edmund Optics Excel exports supplied
by the user. Import code reads these files in read-only mode. Do not edit or
replace values in the source workbooks during normalization.

## Generated files

`generated/` is reproducibly rebuilt by:

```powershell
.\.venv\Scripts\kirakiralens-import-edmund
```

- `edmund_catalog.sqlite3` is the normalized application database.
- `edmund_catalog.csv` is a documented flat interchange export.
- `edmund_import_report.json` records source hashes and row-level exceptions.

The current source set contains 920 products. Of these, 918 have enough verified
prescription data to use in optical design. Parts `67-332` and `67-333` remain
browsable but are excluded from design search because the supplied workbook does
not include their complete radii and split center thicknesses. Do not infer the
missing values.
