# Local validation — 14 October 2026

## Actual Hudson acquisition

Source: MassGIS Massachusetts Property Tax Parcels, municipal ID 141.

- 7,452 source feature rows acquired and published.
- 5,949 distinct non-null LOC_ID parcel identifiers.
- 7,441 distinct non-null PROP_ID assessment identifiers.
- One source geometry quarantined from spatial use; original geometry and attributes retained.
- Replaying the complete checksummed snapshot returned `reused: true` and the same publication ID.

These are source-grain observations, not independently verified counts of marketable properties, owners or contacts.

## Source issues discovered

A 200-ID GET batch exceeded the provider's effective URL limit when IDs grew longer. Acquisition now uses at most 100 IDs per request and verifies each returned ID set. The failed acquisition remained unpublished.

Source OBJECTID 1833882 has nested polygon shells. PostGIS repair would change projected area from approximately 315,435 to 217,797 square meters. No automatic repair was accepted. The original GeoJSON is retained in `raw_geometry`, the usable `geom` is null, and `invalid_geometry_quarantined` is visible as a quality issue. Missing/unsupported, empty or out-of-range geometry still blocks publication.

## Tests completed

14 tests passed against local PostgreSQL/PostGIS:

- Name normalization without changing originals; unknown units; condominium classification.
- Snapshot checksum integrity; complete bounded source pages; partial-page rejection.
- Idempotent publication; refresh preserving notes; replay without active-version rollback.
- Duplicate IDs, wrong-town records, out-of-range geometry, missing geometry and count mismatches preserve the prior publication.
- Repeated assessment IDs flagged without merging records.
- Invalid topology preserved and quarantined.
- API filter behavior, SQL injection-shaped input, literal wildcard searches, pagination bounds, publication lookup and raw-value retrieval.

Chromium smoke passed: initial loading, pagination, segment filtering, source detail, quarantine filtering, mobile overflow check, no JavaScript errors. Screenshot stored locally at `/tmp/prospect-intelligence-desktop.png` (contains source owner data; not committed).

## Limits

No production deployment, authentication, second-town test, durable queue, map rendering, contact enrichment or GoHighLevel integration was performed. One dependency deprecation warning appears in the test client; it does not fail tests. Full source-assessment grain and classification coverage require review before prospect exports or financial aggregations.
