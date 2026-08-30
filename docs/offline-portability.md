# Offline writes, privacy, and Trip Bundle recovery

Travel owns place, Trip, and Visit facts. Garden may consume only an explicit public projection;
Archive owns original receipts and durable derived resources. Travel stores stable `shadow://` references
to Platform Asset or Archive resources and never copies original bytes into its database or Bundle.

## Offline write contract

`Trip` and `Visit` mutations use a client-generated `client_record_id`, an integer `version`,
`Idempotency-Key`, and `X-Correlation-Id`:

- replaying the same key and canonical payload returns the original record with `replayed=true`;
- reusing a key or client record ID with another payload returns `409`;
- updates may send `expected_version`; stale updates return `409` with the current safe representation;
- the PWA keeps failed Visit creates locally, replays on `online`, and leaves conflicts visible instead of
  overwriting either side.

Client IDs are fact identities, not transport request IDs. `X-Request-Id` identifies one attempt;
`X-Correlation-Id` survives retries. Neither contains location, note, or user data.

## Trip Bundle v1

`GET /api/browser/v1/trips/{trip_id}/bundle` exports:

- Trip facts and referenced places;
- owned Visits and their optional records;
- Platform Asset and Archive references only;
- a minimum share projection, never the private projection;
- a verification checklist, per-section SHA-256 values, and a manifest hash.

`POST /api/browser/v1/trip-bundles/verify` performs an isolated, write-free rehydrate check. It rejects
section or manifest tampering, dangling Visit-to-Place references, duplicate client IDs, embedded media,
and unsupported contracts. It never merges into the active database. Operators must restore a backup or
Bundle into a separate target, run the verifier, and only then make a separate recovery decision.

## Privacy and location

Map points default to `public_location_precision=approximate`, which rounds public coordinates to two
decimal places. `exact` is explicit. A `privacy_zone` always overrides precision and removes coordinates.
Public links omit internal Place IDs, exact addresses, custom fields, provider identities, and media URLs.
Access is audited without tokens or client IPs, with bounded write frequency. Links expire and can be
revoked immediately.

Location history is disabled by default. Configuration accepts only explicit `local` or `self-hosted`
adapters. Production self-hosted adapters require HTTPS. Travel provides no implicit continuous tracking,
remote vendor adapter, or background opt-in.

## Platform capability lifecycle

`scripts/travel_conformance.py` emits `shadow.conformance-evidence.v1` bound to an exact deployment and
build. Stages stay independent:

- `deployed` checks the packaged contracts and migration;
- `observed` exercises live health and the granted metadata-only summary, and therefore marks only
  `travel.maps.read` observed;
- `restore-tested` requires a valid Bundle and passing `healthz` plus `readyz` on an isolated restore URL.

The output can be consumed by Platform's conformance gate. Missing stages remain unknown; the script does
not manufacture online or restore evidence from source-code tests.
