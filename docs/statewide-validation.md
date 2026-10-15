# Statewide acquisition and map validation — 14 October 2026

Completed locally. All 351 municipalities are published with zero pending or failed towns.

| Verified measure | Result |
| --- | ---: |
| Municipal archives | 351 |
| Archive bytes, before assessor supplements | 1,013,469,665 |
| Parcel geometry records | 2,197,515 |
| Assessment records | 2,553,888 |
| Supporting source records | 830,434 |
| Parcel geometries quarantined from mapping | 263 |

Every original municipal archive passed SHA-256 reconciliation. Every town’s database parcel, assessment, and supporting-record counts match its recorded layer inventory. Assessment supplement pages passed checksum, unique-ID, municipality, and row-count reconciliation.

Archives missing an assessment table were supplemented from the official separate MassGIS assessor service:

- Boston: 180,445 assessment rows.
- Williamsburg: 1,380 assessment rows.
- Gloucester: 14,879 assessment rows.

Dataset UUID: `f6087ff7-028c-4a8e-870d-a31babfbe239`.

Original curved geometries remain in the source geodatabases. Display geometry is linearized at a 1-degree angular step. The 263 quarantined parcel geometries are retained in their original archives and their attribute records remain in the database; they are not silently repaired or drawn.

## Verification

- 19 automated tests passed against PostgreSQL/PostGIS.
- Chromium acceptance passed: statewide overview, Hudson navigation, local vector tiles, assessment details, neighboring-parcel candidates, type filters, address/owner search, layer controls, and mobile layout.
- No JavaScript errors were reported in the acceptance run.
- Desktop statewide, property detail and mobile screenshots were inspected.
- The old Hudson pilot remains available at `/hudson`.

## Local spot measurements after statewide completion

These are individual requests on the local WSL machine, not sustained-load benchmarks.

| Request | Seconds | Response bytes |
| --- | ---: | ---: |
| statewide catalog | 0.246 | 212,773 |
| boston search | 0.593 | 11,047 |
| hudson search | 0.054 | 11,143 |
| boston tile cold | 0.035 | 8,530 |
| boston tile warm | 0.011 | 8,530 |

## Reproduce

```bash
./scripts/local.sh -m scripts.validate_statewide
./scripts/local.sh -m pytest -q
./scripts/local.sh scripts/map_browser_smoke.py
```

The browser check requires the optional Playwright package and Chromium installation.

No production deployment, authentication, offline basemap download, contact enrichment, or GoHighLevel synchronization is included. The local parcel data is complete for the acquired official packages; fiscal years and source freshness vary by town. See [engineering and source notes](statewide-map.md).
