# SGP4 Element Input Contract

## Status

- Contract ID: `orbitserve.sgp4_element_bundle.v1`
- Decision status: implemented
- Frozen date: 2026-07-20
- Code status: the public input models, strict validator, direct-element
  SGP4-to-TEME propagation, pinned-data TEME-to-ITRS transformation,
  geometry-only SGL/ISL/sunlight evaluation, and canonical Orbit Trace
  serialization are implemented

This contract defines the parameters supplied to Orbit for SGP4 propagation.
The canonical end-to-end public entry point is `generate_orbit_trace`.

The public input entry points are `Sgp4ElementBundle`,
`Sgp4SatelliteElements`, `Sgp4ElementProvenance`, and
`load_sgp4_element_bundle`, exported from `orbitserve.orbit`. The loader accepts
a JSON path, JSON-compatible mapping, or an already validated bundle. It does
not initialize an SGP4 engine by itself.

The public propagation entry point is `propagate_sgp4_teme`. It accepts
one validated element bundle, a canonical simulation UTC epoch, and unique
non-negative relative sample times. It uses `python-sgp4==2.27`, WGS-72, and
improved mode, fails the complete call on any initialization or sample error,
and returns records ordered by `(time_s, satellite_id)` in TEME kilometres and
kilometres per second.

The public frame entry point is `transform_sgp4_teme_to_itrs`. It uses
`astropy==6.1.3`, disables IERS network updates, and requires local IERS-A and
leap-second files that cover every sample. Their SHA-256 values, data release,
the installed `astropy-iers-data` version, and whether Earth-orientation values
are definitive or predictive are recorded in the result. Absolute data paths
are excluded. Orbit defaults to the vendored
`astropy-iers-data-0.2026.5.11.1.8.52` files and verifies their fixed hashes
before use; callers may supply different immutable files explicitly.
Out-of-range data fails the complete transformation instead of extrapolating
silently.

The public geometry entry points are `compute_sgp4_sun_positions_itrs` and
`evaluate_sgp4_geometry`. The geometry evaluator accepts a complete
`Sgp4EarthFixedResult`, geometry-only ground ingresses, and explicit candidate
ISL endpoint pairs. It produces deterministic samples plus half-open windows
over `[first_sample_time, last_sample_time)`. It does not choose an ISL
topology and does not emit bandwidth, terminal, routing, graph, SOC, or other
Runtime/Architecture state.

Ground geometry uses WGS-84 geodetic coordinates and the local geodetic up
direction. ISL occultation tests the complete line segment against the WGS-84
ellipsoid, with an optional non-negative clearance margin. Sun positions use
Astropy's geocentric Sun ephemeris transformed to ITRS under the exact pinned
IERS/leap-second provenance of the Earth-fixed result. Eclipse classification
uses a conical umbra with the IAU nominal solar radius and an optional
atmospheric Earth-radius margin. Boolean crossings are refined by linear
interpolation of the corresponding signed boundary function; this refinement
is declared by `sgp4-wgs84-geometry-v1`.

The trace adapter entry point is `write_sgp4_orbit_trace`. It accepts the
validated element bundle, TEME propagation result, ITRS transformation result,
and geometry result from the preceding public stages. Before writing anything,
it requires identical element-set identity, simulation epoch, ordered sample
keys, satellite membership, geometry source provenance, and a uniform sample
grid. It delegates canonical JSON, file hashes, Runtime/Architecture-field
rejection, and manifest construction to the unchanged public
`write_orbit_trace` entry point.

Trace ephemeris records deliberately use explicit `position_teme_km`,
`velocity_teme_km_s`, `position_itrs_km`, and `velocity_itrs_km_s` fields. They
do not overload the legacy `r_eci_km` name. The satellite catalog contains the
canonical structured SGP4 mean-element records. Window records contain only
geometry and sampled distance/delay bounds; they do not contain bandwidth,
terminal, graph, routing, capacity, or SOC state. Trace provenance records all
element, propagation, frame, Earth-orientation, and geometry algorithm/data
versions. Synthetic and predictive-data status is emitted as an explicit
warning, and formal-results eligibility is never inferred automatically.

## Frozen decisions

1. The authoritative input is a structured, full-precision set of
   SGP4-compatible mean elements, not two fixed-width TLE text lines.
2. Orbit initializes SGP4 directly from the structured values. Canonical TLE
   lines may be generated as an audit and interoperability artifact, but the
   quantized lines are not read back as the propagation source.
3. Input elements have SGP4 mean-element semantics. They are not osculating
   Keplerian elements and must not be produced by merely renaming a Cartesian
   state or classical-element record.
4. Contract v1 supports the WGS-72 gravity constants and improved SGP4
   operation mode only.
5. Synthetic inputs must be identified as synthetic and must not claim to be
   observationally fitted. Orbit does not silently promote synthetic output to
   formal-experiment evidence.
6. Identical canonical element input, propagation request, pinned Earth
   orientation data, schema version, and algorithm version must produce
   byte-for-byte identical Orbit output.

## Module boundary

The upstream constellation or scenario builder owns generation or fitting of
the mean elements. Orbit owns validation, deterministic normalization, SGP4
initialization and propagation, coordinate transformation, geometric-window
calculation, and trace serialization.

The upstream provider must not depend on Orbit implementation files. Input is
passed through the public `orbitserve.orbit` entry points. Runtime consumes
only the public Orbit Trace contract and must not initialize or call the SGP4
engine itself.

This contract does not assign Architecture or Runtime data to Orbit. Initial
SOC, terminal capabilities or allocation, active graphs, bandwidth, routing,
queues, and energy state remain outside this input and outside Orbit output.

## Canonical bundle shape

The transport representation is a JSON-compatible mapping with this shape:

```json
{
  "schema_version": "orbitserve.sgp4_element_bundle.v1",
  "element_semantics": "sgp4_mean_elements",
  "gravity_model": "wgs72",
  "ops_mode": "improved",
  "time_scale": "utc",
  "satellites": [
    {
      "satellite_id": "sat-00001",
      "satnum": 10001,
      "classification": "U",
      "object_id": "2026-001A",
      "epoch_utc": "2026-07-20T00:00:00.000000Z",
      "inclination_deg": 53.0,
      "raan_deg": 0.0,
      "eccentricity": 0.001,
      "argument_of_perigee_deg": 0.0,
      "mean_anomaly_deg": 0.0,
      "mean_motion_rev_per_day": 15.25,
      "mean_motion_dot_rev_per_day2": 0.0,
      "mean_motion_ddot_rev_per_day3": 0.0,
      "bstar_inv_earth_radii": 0.00001,
      "ephemeris_type": 0,
      "element_set_number": 1,
      "revolution_number_at_epoch": 1
    }
  ],
  "provenance": {
    "source_kind": "synthetic_sgp4_mean_elements",
    "source_name": "scenario-builder",
    "source_version": "example-v1",
    "observationally_fitted": false
  }
}
```

The example values illustrate representation only; they are not a validated
reference orbit.

## Bundle fields

| Field | Type | Required value or rule |
|---|---|---|
| `schema_version` | string | Exactly `orbitserve.sgp4_element_bundle.v1` |
| `element_semantics` | string | Exactly `sgp4_mean_elements` |
| `gravity_model` | string | Exactly `wgs72` in v1 |
| `ops_mode` | string | Exactly `improved` in v1 |
| `time_scale` | string | Exactly `utc` in v1 |
| `satellites` | array | Non-empty, unique records ordered canonically by `satellite_id` |
| `provenance` | object | Required source and fitting declaration described below |

Unknown bundle, satellite, or provenance fields are rejected in v1. This
fail-closed rule prevents misspelled parameters and undeclared units from being
silently ignored. A later additive schema version is required for new fields.

## Satellite element fields

### Identity and bookkeeping

| Field | Type | Rule |
|---|---|---|
| `satellite_id` | string | Required, non-empty, stable Orbit identity; unique in the bundle |
| `satnum` | integer | Required, `1..339999`, unique in the bundle; used for SGP4/TLE identity |
| `classification` | string | Required, one ASCII character from `U`, `C`, or `S` |
| `object_id` | string or null | Optional CCSDS-style international designator `YYYY-NNNPPP`; `null` for synthetic objects without one |
| `ephemeris_type` | integer | Required and exactly `0` in v1 |
| `element_set_number` | integer | Required, `0..9999` |
| `revolution_number_at_epoch` | integer | Required, `0..99999` |

`satellite_id` is the identifier used by Orbit Trace records. `satnum` and
`object_id` are external catalog or TLE bookkeeping and must not replace it.
Reordering input records must not change satellite identity or output bytes.

### Epoch and physical elements

| Field | Unit | Range or interpretation |
|---|---|---|
| `epoch_utc` | UTC text | RFC 3339 UTC, canonical form `YYYY-MM-DDTHH:MM:SS.ffffffZ`; seconds are `00..59` |
| `inclination_deg` | degree | `0 <= value <= 180` |
| `raan_deg` | degree | `0 <= value < 360` |
| `eccentricity` | dimensionless | `0 <= value < 1` |
| `argument_of_perigee_deg` | degree | `0 <= value < 360` |
| `mean_anomaly_deg` | degree | `0 <= value < 360` |
| `mean_motion_rev_per_day` | revolution/day | Finite and strictly positive |
| `mean_motion_dot_rev_per_day2` | revolution/day^2 | Finite, true first derivative `dn/dt` |
| `mean_motion_ddot_rev_per_day3` | revolution/day^3 | Finite, true second derivative `d2n/dt2` |
| `bstar_inv_earth_radii` | 1/Earth radius | Finite SGP4 BSTAR value |

The derivative fields contain the mathematical derivatives. They do not
contain the TLE line-1 display values `ndot/2` and `nddot/6`. Only the TLE
formatter applies those representation conventions.

All numeric inputs must be JSON integers or finite JSON numbers. Boolean values
are not accepted as numbers. Unit conversion is explicit at the Orbit-to-SGP4
adapter: degrees become radians, revolutions/day become the engine's angular
rate units, and derivative units are converted exactly once.

## Provenance fields

| Field | Type | Rule |
|---|---|---|
| `source_kind` | string | `synthetic_sgp4_mean_elements` or `observationally_fitted_general_perturbations` |
| `source_name` | string | Required, non-empty generator, catalog, or fitting-pipeline name |
| `source_version` | string | Required, non-empty immutable version, revision, or data-release identifier |
| `observationally_fitted` | boolean | Must be `false` for synthetic input and `true` for observationally fitted input |

Provenance may describe how the upstream provider generated the mean elements,
but it must not contain host names, absolute paths, wall-clock generation
times, random process IDs, or other non-reproducible metadata.

For synthetic inputs, the future SGP4 path defaults
`valid_for_paper_main_results` to `false`. Any policy that permits a synthetic
scenario in formal results belongs to the experiment owner and must be an
explicit reviewed decision; Orbit never infers it from numerically plausible
elements.

## Authority and TLE generation rules

- The structured fields above are the sole propagation authority.
- Input `tle_line1` and `tle_line2` fields are not part of schema v1 and are
  rejected as unknown fields.
- An audit TLE formatter uses the same structured record, deterministic
  rounding, fixed-width fields, checksum rules, and Alpha-5 satellite-number
  encoding when required.
- Audit TLE generation must report overflow or an unrepresentable value as an
  error. It must not truncate a value silently.
- Parsing the generated TLE back into SGP4 is allowed only in formatter
  compatibility tests. Production propagation must not use that round trip.
- Because TLE is a lower-precision fixed-width representation, propagation
  from audit lines is not required to be bit-identical to propagation directly
  from the full-precision structured input.

## Propagation and frame interpretation

The element bundle does not contain the simulation sample grid. The Orbit
propagation request supplies start time, end time, and step separately using
the existing trace time semantics. Every requested absolute sample instant is
derived deterministically from the simulation epoch and `time_s`.

SGP4 natively produces position in kilometres and velocity in kilometres per
second in the TEME frame. Any Earth-fixed ground geometry uses an explicit TEME
to ITRS transformation. A simple Earth-rotation angle or an undeclared ECI/ECEF
alias is not an acceptable high-precision substitute.

The implementation pins and records:

- the SGP4 library and algorithm version;
- the WGS-72 constants selection and improved operation mode;
- the time conversion implementation;
- the TEME-to-ITRS transformation implementation;
- the Earth orientation data release or immutable data hash;
- all window-detection and boundary-refinement algorithm versions.

Runtime network access for Earth orientation updates is prohibited during a
reproducible run. Missing or out-of-range pinned data must fail closed or emit
an explicitly versioned fallback result that is ineligible for formal results.

## Validation and failure behavior

The future public validator must reject the complete bundle before propagation
when any of these conditions occurs:

- a required field is absent, an unknown field is present, or a type is wrong;
- an identifier is empty or duplicated;
- a number is non-finite or outside its declared range;
- an angle relies on implicit wrapping instead of canonical input;
- the epoch is not canonical UTC or contains a leap-second literal;
- element semantics, gravity model, operation mode, or time scale is
  unsupported;
- provenance is inconsistent with `observationally_fitted`;
- the SGP4 initializer returns an error for any satellite.

Per-sample SGP4 error codes must be preserved with satellite identity and
sample time. A failed sample must never be serialized as a plausible zero or
stale position. The later implementation phase will freeze whether a complete
trace fails or supports an explicitly partial, ineligible diagnostic trace;
the initial production path will fail the complete run.

## Determinism and canonical identity

Before hashing or propagation, Orbit normalizes the bundle as follows:

- satellite records are sorted by `satellite_id`;
- JSON object keys are sorted lexicographically;
- UTF-8, LF, one final newline, and the Orbit Trace finite-float rules apply;
- negative zero becomes `0.0`;
- no implicit angle wrapping, epoch rounding, or duplicate de-duplication is
  performed;
- identifiers and provenance strings are preserved exactly after validation;
- the propagation request and all pinned algorithm/data versions participate
  in trace identity.

The future normalized input exposes an `element_set_id` of the form
`sgp4-elements-v1-<sha256>`. Its digest covers the canonical physical controls
and satellite records but excludes non-physical provenance. Complete output
bytes still include deterministic provenance, so changing provenance may
change file bytes even when `element_set_id` stays the same.

## Cross-module consumer requirements

Runtime, DSE, and Experiments must use public `orbitserve.orbit` entry points
and structured SGP4 element bundles. The circular configuration, legacy
`r_eci_km` trace shape, trace builders, and compatibility aliases have been
removed. DSE/Experiments generation and search policy is deferred to their
owners; Orbit does not retain a circular fallback.

Root dependencies and vendored IERS package-data are declared in
`pyproject.toml`.

## Acceptance criteria for contract freeze

- Every required upstream parameter has one name, type, unit, and semantic
  interpretation.
- Structured full-precision input and audit TLE authority are unambiguous.
- Synthetic and observationally fitted provenance cannot be confused.
- Validation, error handling, coordinate-frame requirements, and deterministic
  identity are explicit.
- Cross-module consumers have explicit migration requirements and use only
  public Orbit interfaces.
