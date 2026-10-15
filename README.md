# LabHaptic property intelligence — Massachusetts map

A local Massachusetts property map backed by official municipal geodatabases and PostgreSQL/PostGIS. The original Hudson diagnostic interface remains available at `/hudson`. Marketing belongs in GoHighLevel; this application does not send messages.

## Run in WSL

Requires Python 3.10+, Python venv support, Docker Engine and Docker Compose.

```bash
./scripts/setup.sh
./scripts/local.sh -m pytest -q
./scripts/local.sh scripts/download_statewide.py
./scripts/local.sh -m app.statewide
./scripts/local.sh -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Open http://localhost:8000 for the statewide map (interactive API contracts at `/docs`). The map uses locally served MapLibre assets and locally generated parcel vector tiles; the contextual basemap streams from MassGIS. PostgreSQL binds only to `127.0.0.1:55432`. This pilot has no authentication: keep it local; it is not deployable as a public service yet.

Setup generates a random local database password in ignored `.env`. It does not print credentials. Python packages live on the Linux filesystem in `/tmp/prospect-intelligence-venv`; rerun setup if temporary files are cleaned. Database storage uses a Docker named volume. `docker compose stop` stops it without removing data. Never use `down -v` if you want to preserve the database.


## Statewide map

- All 351 current municipal File Geodatabase archives are downloaded with SHA-256 and ZIP-integrity checks. Historical vintages are outside this acquisition.
- Original parcel geometry, assessment records, legal-interest layers, miscellaneous layers, and lookup tables remain available in the immutable source archives.
- Separate local `map_parcels`, `map_assessments`, and `map_supplementary` tables preserve source grains; table joins do not multiply assessment totals.
- The importer uses two bounded town workers, atomic per-town transactions, source checksums, an exclusive import lock, and resume-by-completed-town behavior.
- If a municipal archive omits the Assess table, a separately checksummed official MassGIS assessor-service supplement is fetched automatically. Its URL, timestamp and manifest are attached to that town's provenance.
- Statewide coverage, municipality selection, local address/owner search, property-type filters, parcel details, candidate neighbors, and layer toggles are available.
- The map starts with town boundaries. Parcel vector tiles begin at zoom 13, are limited to 20,000 candidates / 3 MB per tile, and use PostGIS spatial indexes. Full source geometry is never sent statewide to the browser.
- Curved geometry is linearized through GDAL at a 1-degree angular step for display. Invalid or empty geometries are quarantined from map display; no silent topology repair is performed. Original source files remain intact.
- Source classifications are provisional. Commercial subsegments and legal ownership/entity resolution need reviewed enrichment. Municipality catalog fiscal years may differ from individual assessor rows; inspect the record's FY.
- The complete current source acquisition is not a single simultaneous statewide assessment year. Source currency and submission schedules vary by municipality.

Read [statewide engineering notes](docs/statewide-map.md) for endpoints, data grain, provenance and verification.

### Re-running acquisition

The downloader resumes the **same catalog snapshot** from `data/statewide/download-catalog.json`; existing archives are rechecked against stored hashes. It does not silently reinterpret a resume as a refresh to newer provider files. A future source refresh should use a new acquisition directory/catalog and publication, rather than replacing the preserved snapshot.

The import uses `/tmp/prospect-intelligence-gdb` for disposable Linux-filesystem extraction, while verified originals remain under ignored `data/statewide/archives`. The database uses a Docker named volume. No source data or credentials should be committed to Git.

## Original Hudson pilot implementation

- Hudson (municipality 141) allowlisted acquisition, using a complete object-ID inventory and bounded batches, with retries for transport errors.
- Source schema checks, per-page ID checks, town checks, source edit timestamp consistency check, checksummed GeoJSON pages and metadata manifest.
- Original attribute values and full polygon geometry retained; topologically invalid geometry is explicitly flagged and excluded from the usable spatial column without repairing the source; standardized uppercase/whitespace names and addresses alongside originals. No speculative name splitting or legal entity merging.
- Conservative source-derived classifications, missing-value flags, unknown unit counts, repeated assessment identifier flags.
- PostgreSQL transactional publication: incomplete or structurally invalid imports cannot replace the active dataset. Identical data with the same processing version is reused. Replaying an older publication does not roll back the active pointer.
- Exclusive per-town import lock, persisted run status, failure details, and interrupted-run detection when the next run starts.
- Read-only FastAPI endpoints: paginated search, counts, details, publication metadata, quality summaries, candidate owner groups, and import runs.
- Local HTML inspection interface at `/hudson`. The new root map uses MapLibre; a React application shell remains future work.
- Separate persistent property-note table, with refresh preservation covered by integration tests. Note editing is not exposed yet.

## Replay an existing snapshot

Find the completed snapshot directory under `data/raw/<run-id>` and run:

```bash
./scripts/local.sh -m app.cli ingest --snapshot data/raw/<run-id>
```

A partial failed download cannot be published without a complete valid manifest. The pipeline is currently invoked as a separate CLI process; durable queue scheduling, heartbeats, automatic restart and a browser admin console are future work. A killed process may appear running until the next import marks it interrupted.

## Data grain and uncertainty

The MassGIS service is a parcel/assessor joined feature layer. One feature is **not necessarily one unique property or assessment**. Preserve each source OBJECTID within a publication, and expose distinct LOC_ID/PROP_ID counts separately. Assessment totals are deliberately not summed. Source OBJECTIDs are publication-scoped, not stable identities across releases. LOC_ID-based notes persist, but parcel splits/merges and identifier changes still need reconciliation.

Repeated ownership name plus complete matching mailing address produces a candidate group only. Shared mailboxes and property managers can create false matches. Source descriptions drive initial segments; extended local use codes and commercial subsegments need a reviewed town-specific crosswalk. Zero unit counts are unknown, not evidence of zero units.

Contacts are explicitly "not started"; this parcel source does not establish valid phones, email, current management, purchasing authority, or outreach readiness. Acquisition snapshots are local observations of a mutable public service, not official immutable provider release IDs.

## Before shipping

1. Review Hudson classification coverage and source-to-assessment grain against municipal originals.
2. Add proper property/assessment/party entities and reviewed relationship reconciliation.
3. Add durable queue leases, browser admin controls, and automatic worker recovery to the current resumable statewide CLI.
4. Evolve the existing MapLibre interface into the planned React application as workflows grow.
5. Add authentication, authorization, migrations policy, off-server backup/restore and resource measurements.
6. Add evidence-backed enrichment and reviewed GoHighLevel export mapping.

## Sources

- [MassGIS layer schema](https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/Massachusetts_Property_Tax_Parcels/FeatureServer/0?f=pjson)
- [ArcGIS feature queries](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/)
- [PostGIS GeoJSON ingestion](https://postgis.net/docs/ST_GeomFromGeoJSON.html)
- [Psycopg transaction behavior](https://www.psycopg.org/psycopg3/docs/basic/usage.html)
