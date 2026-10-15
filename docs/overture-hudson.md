# Hudson Overture acquisition

This is a standalone local download benchmark. It reads the existing Hudson town boundary from PostGIS in a read-only transaction. It does not modify application APIs, map layers, or PostGIS data.

## Reproduce

```bash
scripts/local.sh -m pip install -r requirements-overture.txt
scripts/local.sh scripts/pull_overture_hudson.py
```

The script installs/loads DuckDB's official `httpfs` and `spatial` extensions in `/tmp/prospect-duckdb-extensions`, limits DuckDB to two threads and a 1 GB managed-memory budget, and creates a fresh timestamped directory under `data/overture/hudson/`. The Python environment and extension cache currently live in `/tmp`; the pinned requirements allow reinstallation if they are cleared. Process RSS can exceed DuckDB's managed-memory budget.

It resolves and records the latest release from the [official STAC catalog](https://stac.overturemaps.org/catalog.json), selects overlapping cloud files from the release index, applies bounding-box pushdown, and retains features that intersect the actual Hudson boundary. All source fields and original feature geometries are retained. Features crossing Hudson's border are not clipped; administrative areas can extend far beyond Hudson. This is an intersection subset, not a count of features wholly contained in the town.

Outputs include per-layer compressed GeoParquet, a local `hudson.duckdb` database with the same records, the town boundary, release catalog/index, and `report.json`. The report records each layer's count, unique-ID count, local file size and elapsed time, total runtime, database size and peak process RSS. Layers with no intersecting source files have zero records and no output table/file. Failed layers are reported explicitly.

Timing starts before boundary/catalog retrieval and includes extension setup, remote querying, local filtering and writing. It excludes pip installation. Local file sizes are not measurements of network bytes transferred; Parquet range reads also fetch metadata and surrounding row groups. This is a single-run benchmark, not a general latency guarantee.

Source documentation: [Overture DuckDB guide](https://docs.overturemaps.org/getting-data/duckdb/) and [attribution and licensing](https://docs.overturemaps.org/attribution/). Source attribution fields are retained in the downloaded records.

## Measured run: 2026-10-15 01:33 UTC

Release: 2026-09-23.1. Results: **30,258 records in 59.608 seconds**, including 3.313 seconds of setup. Compressed layer files total **7,591,698 bytes (7.59 MB)**; the additional DuckDB copy is **16,789,504 bytes (16.79 MB)**. Peak process RSS was **770,453,504 bytes (735 MiB)**. Dependency installation is excluded from elapsed time.

| Layer | Records | Bytes | Seconds |
|---|---:|---:|---:|
| building | 8,112 | 1,181,129 | 3.571 |
| building_part | 0 | 1,173 | 2.338 |
| place | 1,224 | 185,042 | 2.397 |
| address | 9,824 | 476,233 | 3.274 |
| segment | 3,301 | 744,577 | 2.776 |
| connector | 5,197 | 261,015 | 2.426 |
| infrastructure | 1,176 | 126,264 | 6.11 |
| land | 683 | 304,921 | 2.661 |
| land_cover | 52 | 863,348 | 4.001 |
| land_use | 361 | 121,857 | 3.33 |
| water | 313 | 172,023 | 7.6 |
| bathymetry | 0 | 588 | 2.009 |
| division | 3 | 8,809 | 2.356 |
| division_area | 11 | 3,125,307 | 8.699 |
| division_boundary | 1 | 19,412 | 2.667 |

All 15 layers completed. Reopened the database and Parquet files and verified matching counts, unique IDs within each layer, and intersection with the town boundary. Detailed evidence: data/overture/hudson/20261015T013342Z/report.json and validation.json.
