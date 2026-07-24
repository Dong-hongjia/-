# Orbit Trace Contract

## Status

- Contract ID: `orbitserve.orbit_trace_contract`
- Decision status: implemented
- Frozen date: 2026-07-20
- Canonical schema: `orbitserve.orbit_trace`

This contract defines the sole SGP4-based, geometry-only Orbit output. The old
circular-orbit simulator, surrogate schemas, trace builders, and compatibility
aliases have been removed with provider/consumer confirmation.

## Module boundary

Orbit deterministically produces physical geometry and environmental facts. It
does not make communication, scheduling, deployment, or request-execution
decisions.

### Orbit-owned inputs

- structured SGP4 mean elements and stable satellite identities;
- simulation epoch and sample grid;
- ground ingress identities, coordinates, and elevation masks;
- explicit candidate ISL pairs;
- geometric and sunlight-model controls;
- schema, algorithm, and immutable reference-data versions.

Output paths, host names, process IDs, wall-clock timestamps, and temporary
names are not physical inputs and must not affect trace identity or bytes.

### Orbit-owned outputs

- trace metadata, relative file references, SHA-256 values, provenance, and warnings;
- geometry-only satellite catalog;
- ordered TEME and ITRS ephemeris samples;
- SGL and ISL geometric windows with distance and propagation-delay facts;
- sunlight and shadow windows.

### Runtime-owned derived state

| Field or concept | Source of truth |
|---|---|
| `satellite_initial_soc` | Runtime configuration constrained by Architecture |
| `terminal_catalog` | Orbit satellite IDs plus Architecture and Runtime configuration |
| `active_graph_snapshots` | Orbit visibility plus Runtime state and policy |
| bandwidth and capacity | Architecture plus Runtime configuration |
| terminal allocation | Runtime state |
| route, queue, congestion, DVFS, SOC, energy | Runtime and scheduler state |

These fields must not appear in Orbit-generated payloads or `OrbitTraceBundle`.

## Canonical public contract

Other modules import only from `orbitserve.orbit`.

- Producer entry points: `generate_orbit_trace`, `write_sgp4_orbit_trace`,
  `write_orbit_trace`
- Consumer entry point: `load_orbit_trace`
- Public types: `OrbitTraceManifest`, `OrbitTraceBundle`

`OrbitTraceBundle` exposes `trace_manifest`, `satellite_catalog`,
`ephemeris_samples`, `sgl_windows`, `isl_windows`, and `sunlight_windows`, plus
read-only metadata properties. No `RuntimeTrace*` or surrogate aliases exist.

## Manifest and record invariants

- `trace_id`, schema, time range, and satellite identities agree across files.
- `trace_id` is derived from canonical physical inputs and algorithm versions,
  never the output directory.
- File paths are relative POSIX paths.
- Every referenced data file has a SHA-256 value.
- Ephemeris records are ordered by `(time_s, satellite_id)`.
- SGL uses the shared `ingress_id` namespace.
- ISL endpoint ordering is canonical.
- Windows are half-open `[start_s, end_s)` with `start_s < end_s`.
- Runtime- and Architecture-owned fields are rejected.

The writer emits:

- `trace_manifest.json`
- `satellite_catalog.json`
- `ephemeris_trace.json`
- `sgl_windows.json`
- `isl_windows.json`
- `sunlight_windows.json`

## Byte-level reproducibility

For identical canonical inputs, code, schema, algorithms, and reference data:

- all JSON uses UTF-8 without BOM, sorted keys, compact separators, and one LF;
- numeric values are finite; negative zero becomes `0.0`;
- time and window boundaries are rounded to nine decimal places;
- other floats are normalized to 15 significant decimal digits;
- set-like inputs and warnings are deterministically sorted and deduplicated;
- no host-specific or wall-clock metadata is serialized;
- the complete file set, raw bytes, SHA-256 values, and `trace_id` are identical.

The manifest content hash is computed from the canonical manifest with its own
`trace_manifest_content_sha256` field omitted.

Required tests compare different output directories, mapping insertion orders,
input collection orders, and independent `PYTHONHASHSEED` values. Windows and
CI Linux must produce identical bytes for the same supported environment.

## Consumer obligations

- Consumers use only public Orbit entry points.
- Runtime derives SOC, terminal catalogs, active graphs, capacities, and
  runtime state after loading the geometry-only trace.
- Workload gateway data is adapted through public contracts; gateway bandwidth,
  cost, and runtime availability do not enter Orbit.
- DSE and Experiments must provide or select structured SGP4 element bundles;
  the removed circular configuration is not a fallback.

Any future public field or semantic change requires agreement between the Orbit
producer and affected consumers before code and interface tests change.
