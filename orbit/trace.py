"""Deterministic serialization for the canonical geometry-only Orbit Trace."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


ORBIT_TRACE_SCHEMA = "orbitserve.orbit_trace"
ORBIT_TRACE_ALGORITHM = "canonical-json-geometry"
ORBIT_TRACE_SCOPE = "orbit_geometry_only"

_MANIFEST_NAME = "trace_manifest.json"
_FILE_PATHS = {
    "satellite_catalog_path": "satellite_catalog.json",
    "ephemeris_trace_path": "ephemeris_trace.json",
    "sgl_windows_path": "sgl_windows.json",
    "isl_windows_path": "isl_windows.json",
    "sunlight_windows_path": "sunlight_windows.json",
}
_FILE_HASH_KEYS = {
    "satellite_catalog_path": "satellite_catalog_sha256",
    "ephemeris_trace_path": "ephemeris_trace_sha256",
    "sgl_windows_path": "sgl_windows_sha256",
    "isl_windows_path": "isl_windows_sha256",
    "sunlight_windows_path": "sunlight_windows_sha256",
}
_FILE_KINDS = {
    "satellite_catalog_path": "satellite_catalog",
    "ephemeris_trace_path": "ephemeris_samples",
    "sgl_windows_path": "sgl_windows",
    "isl_windows_path": "isl_windows",
    "sunlight_windows_path": "sunlight_windows",
}
_TIME_FIELDS = {
    "time_s",
    "start_s",
    "end_s",
    "duration_s",
    "step_s",
    "tca_s",
    "propagation_delay_s",
    "propagation_delay_min_s",
    "propagation_delay_max_s",
}
_WRITER_METADATA_FIELDS = {"schema_version", "trace_id"}
_FORBIDDEN_GEOMETRY_FIELDS = {
    "active_graph_snapshots",
    "bandwidth_bps",
    "battery_capacity_j",
    "b_raw_bps",
    "capacity_bps",
    "charge_rate_w",
    "compute_energy_j_per_token",
    "congestion",
    "deployment_id",
    "dvfs_multiplier",
    "edge_available_external",
    "energy_windows",
    "gateway_available_external",
    "idle_power_w",
    "initial_soc",
    "link_energy_j_per_byte",
    "link_terminal_profile",
    "profile_id",
    "queue",
    "route",
    "runtime_energy_envelope",
    "satellite_initial_soc",
    "setup_delay_s",
    "soc",
    "soc_min",
    "tau_setup_s",
    "terminal_catalog",
    "terminal_count",
    "terminal_count_per_satellite",
    "terminal_pool_id",
}
_HOST_METADATA_FIELDS = {
    "absolute_path",
    "created_at",
    "cwd",
    "generated_at",
    "host",
    "hostname",
    "output_dir",
    "timestamp",
    "trace_dir",
}


@dataclass(frozen=True)
class OrbitTraceManifest:
    """Manifest for the single canonical SGP4-based Orbit Trace format."""

    schema_version: str
    trace_model: str
    evaluated: bool
    trace_id: str
    time: dict[str, Any]
    files: dict[str, str]
    sha256: dict[str, str]
    valid_for_paper_main_results: bool
    scope: str
    warnings: tuple[str, ...]
    provenance: dict[str, Any]

    @classmethod
    def from_value(
        cls, value: Mapping[str, Any] | "OrbitTraceManifest"
    ) -> "OrbitTraceManifest":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("Orbit Trace manifest must be a mapping")
        payload = {str(key): item for key, item in value.items()}
        warnings = payload.get("warnings", ())
        if isinstance(warnings, (str, bytes)) or not isinstance(warnings, Sequence):
            raise TypeError("Orbit Trace manifest warnings must be a sequence")
        return cls(
            schema_version=str(payload.get("schema_version") or ""),
            trace_model=str(payload.get("trace_model") or ""),
            evaluated=bool(payload.get("evaluated", False)),
            trace_id=str(payload.get("trace_id") or ""),
            time=_require_mapping(payload.get("time"), "manifest.time"),
            files={
                str(key): str(item)
                for key, item in _require_mapping(
                    payload.get("files"), "manifest.files"
                ).items()
            },
            sha256={
                str(key): str(item)
                for key, item in _require_mapping(
                    payload.get("sha256"), "manifest.sha256"
                ).items()
            },
            valid_for_paper_main_results=bool(
                payload.get("valid_for_paper_main_results", False)
            ),
            scope=str(payload.get("scope") or ""),
            warnings=tuple(str(item) for item in warnings),
            provenance=_require_mapping(
                payload.get("provenance"), "manifest.provenance"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated": self.evaluated,
            "files": dict(self.files),
            "provenance": dict(self.provenance),
            "schema_version": self.schema_version,
            "scope": self.scope,
            "sha256": dict(self.sha256),
            "time": dict(self.time),
            "trace_id": self.trace_id,
            "trace_model": self.trace_model,
            "valid_for_paper_main_results": self.valid_for_paper_main_results,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class OrbitTraceBundle:
    """Loaded geometry-only records for one canonical Orbit Trace."""

    trace_manifest: OrbitTraceManifest
    satellite_catalog: tuple[dict[str, Any], ...]
    ephemeris_samples: tuple[dict[str, Any], ...]
    sgl_windows: tuple[dict[str, Any], ...]
    isl_windows: tuple[dict[str, Any], ...]
    sunlight_windows: tuple[dict[str, Any], ...]

    @property
    def trace_id(self) -> str:
        return self.trace_manifest.trace_id

    @property
    def trace_model(self) -> str:
        return self.trace_manifest.trace_model

    @property
    def scope(self) -> str:
        return self.trace_manifest.scope

    @property
    def time(self) -> dict[str, Any]:
        return dict(self.trace_manifest.time)

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.trace_manifest.warnings

    @property
    def provenance(self) -> dict[str, Any]:
        return dict(self.trace_manifest.provenance)


def write_orbit_trace(
    output_dir: str | Path,
    *,
    time: Mapping[str, Any],
    satellite_catalog: Iterable[Mapping[str, Any]],
    ephemeris_samples: Iterable[Mapping[str, Any]],
    sgl_windows: Iterable[Mapping[str, Any]],
    isl_windows: Iterable[Mapping[str, Any]],
    sunlight_windows: Iterable[Mapping[str, Any]],
    trace_model: str = "sgp4_orbit_geometry",
    valid_for_paper_main_results: bool = False,
    provenance: Mapping[str, Any] | None = None,
    warnings: Sequence[str] = (),
) -> OrbitTraceManifest:
    """Write one canonical Orbit Trace directory and return its manifest."""

    trace_model = str(trace_model).strip()
    if not trace_model:
        raise ValueError("trace_model must be non-empty")
    canonical_time = _prepare_time(time)
    catalog = _prepare_satellite_catalog(satellite_catalog)
    satellite_ids = {str(row["satellite_id"]) for row in catalog}
    ephemeris = _prepare_ephemeris(ephemeris_samples, satellite_ids, canonical_time)
    sgl = _prepare_sgl_windows(sgl_windows, satellite_ids, canonical_time)
    isl = _prepare_isl_windows(isl_windows, satellite_ids, canonical_time)
    sunlight = _prepare_sunlight_windows(sunlight_windows, satellite_ids, canonical_time)
    canonical_provenance = _prepare_provenance(provenance)
    canonical_warnings = sorted({str(item) for item in warnings})

    identity = {
        "algorithm_version": ORBIT_TRACE_ALGORITHM,
        "ephemeris_samples": ephemeris,
        "isl_windows": isl,
        "satellite_catalog": catalog,
        "schema_version": ORBIT_TRACE_SCHEMA,
        "sgl_windows": sgl,
        "sunlight_windows": sunlight,
        "time": canonical_time,
        "trace_model": trace_model,
    }
    trace_id = f"orbit-{hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()}"

    target = Path(output_dir)
    if target.exists() and any(target.iterdir()):
        raise ValueError(f"Orbit Trace output directory must be empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    datasets = {
        "satellite_catalog_path": catalog,
        "ephemeris_trace_path": ephemeris,
        "sgl_windows_path": sgl,
        "isl_windows_path": isl,
        "sunlight_windows_path": sunlight,
    }
    sha256: dict[str, str] = {}
    for path_key, records in datasets.items():
        payload = {
            "kind": _FILE_KINDS[path_key],
            "records": records,
            "schema_version": ORBIT_TRACE_SCHEMA,
            "trace_id": trace_id,
        }
        path = target / _FILE_PATHS[path_key]
        path.write_bytes(_canonical_json_bytes(payload))
        sha256[_FILE_HASH_KEYS[path_key]] = _file_sha256(path)

    manifest: dict[str, Any] = {
        "evaluated": True,
        "files": dict(_FILE_PATHS),
        "provenance": {
            "algorithm_version": ORBIT_TRACE_ALGORITHM,
            "writer": "orbitserve.orbit.write_orbit_trace",
            **canonical_provenance,
        },
        "schema_version": ORBIT_TRACE_SCHEMA,
        "scope": ORBIT_TRACE_SCOPE,
        "sha256": sha256,
        "time": canonical_time,
        "trace_id": trace_id,
        "trace_model": trace_model,
        "valid_for_paper_main_results": bool(valid_for_paper_main_results),
        "warnings": canonical_warnings,
    }
    content_hash = hashlib.sha256(_canonical_json_bytes(manifest)).hexdigest()
    manifest["sha256"] = {
        **sha256,
        "trace_manifest_content_sha256": content_hash,
    }
    (target / _MANIFEST_NAME).write_bytes(_canonical_json_bytes(manifest))
    return OrbitTraceManifest.from_value(manifest)


def load_orbit_trace(
    trace_manifest: str | Path | Mapping[str, Any] | OrbitTraceManifest,
    *,
    base_dir: str | Path | None = None,
) -> OrbitTraceBundle:
    """Load and verify an Orbit Trace directory without Runtime derivation."""

    manifest, root, exact_manifest = _manifest_source(trace_manifest, base_dir)
    if manifest.get("schema_version") != ORBIT_TRACE_SCHEMA:
        raise ValueError(
            f"unsupported Orbit Trace schema: {manifest.get('schema_version')!r}"
        )
    trace_id = str(manifest.get("trace_id") or "")
    if not trace_id:
        raise ValueError("Orbit Trace manifest is missing trace_id")
    files = _require_mapping(manifest.get("files"), "manifest.files")
    hashes = _require_mapping(manifest.get("sha256"), "manifest.sha256")
    if set(files) != set(_FILE_PATHS):
        raise ValueError("Orbit Trace manifest.files must contain exactly the geometry files")
    if exact_manifest:
        expected_content_hash = str(hashes.get("trace_manifest_content_sha256") or "")
        content_manifest = dict(manifest)
        content_manifest["sha256"] = {
            key: value for key, value in hashes.items() if key != "trace_manifest_content_sha256"
        }
        actual_content_hash = hashlib.sha256(_canonical_json_bytes(content_manifest)).hexdigest()
        if expected_content_hash != actual_content_hash:
            raise ValueError("Orbit Trace manifest content SHA-256 mismatch")

    loaded: dict[str, list[dict[str, Any]]] = {}
    for path_key in _FILE_PATHS:
        relative = str(files.get(path_key) or "")
        path = _resolve_relative_trace_path(root, relative)
        expected_hash = str(hashes.get(_FILE_HASH_KEYS[path_key]) or "")
        if not expected_hash or _file_sha256(path) != expected_hash:
            raise ValueError(f"Orbit Trace SHA-256 mismatch for {path_key}")
        payload = _read_json_mapping(path)
        if payload.get("schema_version") != ORBIT_TRACE_SCHEMA:
            raise ValueError(f"Orbit Trace schema mismatch in {relative}")
        if payload.get("trace_id") != trace_id:
            raise ValueError(f"Orbit Trace trace_id mismatch in {relative}")
        if payload.get("kind") != _FILE_KINDS[path_key]:
            raise ValueError(f"Orbit Trace kind mismatch in {relative}")
        records = payload.get("records")
        if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
            raise ValueError(f"Orbit Trace records must be JSON objects in {relative}")
        loaded[path_key] = [dict(item) for item in records]

    canonical_time = _prepare_time(_require_mapping(manifest.get("time"), "manifest.time"))
    catalog = _prepare_satellite_catalog(loaded["satellite_catalog_path"])
    satellite_ids = {str(row["satellite_id"]) for row in catalog}
    ephemeris = _prepare_ephemeris(loaded["ephemeris_trace_path"], satellite_ids, canonical_time)
    sgl = _prepare_sgl_windows(loaded["sgl_windows_path"], satellite_ids, canonical_time)
    isl = _prepare_isl_windows(loaded["isl_windows_path"], satellite_ids, canonical_time)
    sunlight = _prepare_sunlight_windows(loaded["sunlight_windows_path"], satellite_ids, canonical_time)
    expected = {
        "satellite_catalog_path": catalog,
        "ephemeris_trace_path": ephemeris,
        "sgl_windows_path": sgl,
        "isl_windows_path": isl,
        "sunlight_windows_path": sunlight,
    }
    if loaded != expected:
        raise ValueError("Orbit Trace records are not canonically ordered or normalized")

    parsed_manifest = OrbitTraceManifest.from_value(manifest)
    return OrbitTraceBundle(
        trace_manifest=parsed_manifest,
        satellite_catalog=tuple(catalog),
        ephemeris_samples=tuple(ephemeris),
        sgl_windows=tuple(sgl),
        isl_windows=tuple(isl),
        sunlight_windows=tuple(sunlight),
    )


def _prepare_time(value: Mapping[str, Any]) -> dict[str, Any]:
    source = _require_mapping(value, "time")
    epoch = str(source.get("epoch") or "").strip()
    if not epoch:
        raise ValueError("time.epoch must be non-empty")
    start_s = _finite_float(source.get("start_s", 0.0), "time.start_s", time_value=True)
    step_s = _finite_float(source.get("step_s"), "time.step_s", time_value=True)
    if step_s <= 0.0:
        raise ValueError("time.step_s must be positive")
    duration_value = source.get("duration_s")
    end_value = source.get("end_s")
    if duration_value is None and end_value is None:
        raise ValueError("time must define duration_s or end_s")
    duration_s = (
        _finite_float(duration_value, "time.duration_s", time_value=True)
        if duration_value is not None
        else _finite_float(end_value, "time.end_s", time_value=True) - start_s
    )
    end_s = (
        _finite_float(end_value, "time.end_s", time_value=True)
        if end_value is not None
        else start_s + duration_s
    )
    if duration_s <= 0.0 or end_s <= start_s:
        raise ValueError("time range must satisfy start_s < end_s and duration_s > 0")
    if not math.isclose(end_s - start_s, duration_s, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("time.duration_s must equal time.end_s - time.start_s")
    result = {
        key: item
        for key, item in source.items()
        if key not in {"epoch", "start_s", "end_s", "duration_s", "step_s"}
    }
    result.update(
        {
            "duration_s": duration_s,
            "end_s": end_s,
            "epoch": epoch,
            "start_s": start_s,
            "step_s": step_s,
        }
    )
    _reject_forbidden_fields(result, "time")
    return _normalise_value(result)


def _prepare_satellite_catalog(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = _prepare_rows(values, "satellite_catalog", _WRITER_METADATA_FIELDS)
    for row in rows:
        satellite_id = str(row.get("satellite_id") or "").strip()
        if not satellite_id:
            raise ValueError("every satellite catalog row requires satellite_id")
        row["satellite_id"] = satellite_id
    rows.sort(key=lambda item: str(item["satellite_id"]))
    return _deduplicate_rows(
        rows,
        key=lambda item: str(item["satellite_id"]),
        label="satellite catalog",
    )


def _prepare_ephemeris(
    values: Iterable[Mapping[str, Any]],
    satellite_ids: set[str],
    time: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = _prepare_rows(values, "ephemeris_samples", _WRITER_METADATA_FIELDS)
    for row in rows:
        _validate_satellite_reference(row, "satellite_id", satellite_ids, "ephemeris sample")
        row["time_s"] = _bounded_time(row.get("time_s"), time, "ephemeris.time_s", allow_end=True)
    rows.sort(key=lambda item: (float(item["time_s"]), str(item["satellite_id"])))
    return _deduplicate_rows(
        rows,
        key=lambda item: (float(item["time_s"]), str(item["satellite_id"])),
        label="ephemeris",
    )


def _prepare_sgl_windows(
    values: Iterable[Mapping[str, Any]],
    satellite_ids: set[str],
    time: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = _prepare_rows(
        values,
        "sgl_windows",
        _WRITER_METADATA_FIELDS | {"link_id", "sgl_link_id", "window_id"},
    )
    for row in rows:
        _validate_satellite_reference(row, "satellite_id", satellite_ids, "SGL window")
        ingress_id = str(row.get("ingress_id") or "").strip()
        if not ingress_id:
            raise ValueError("every SGL window requires ingress_id")
        row["ingress_id"] = ingress_id
        _validate_window(row, time, "SGL window")
    rows.sort(key=lambda item: _window_sort_key(item, "ingress_id", "satellite_id"))
    rows = _deduplicate_rows(
        rows,
        key=lambda item: (
            float(item["start_s"]),
            str(item["ingress_id"]),
            str(item["satellite_id"]),
            float(item["end_s"]),
        ),
        label="SGL windows",
    )
    for index, row in enumerate(rows):
        row["sgl_link_id"] = f"sgl:{row['ingress_id']}:{row['satellite_id']}"
        row["window_id"] = f"sgl-{index:08d}"
    return rows


def _prepare_isl_windows(
    values: Iterable[Mapping[str, Any]],
    satellite_ids: set[str],
    time: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = _prepare_rows(
        values,
        "isl_windows",
        _WRITER_METADATA_FIELDS | {"link_id", "window_id"},
    )
    for row in rows:
        endpoint_a = str(row.get("endpoint_a") or "").strip()
        endpoint_b = str(row.get("endpoint_b") or "").strip()
        if endpoint_a not in satellite_ids or endpoint_b not in satellite_ids:
            raise ValueError("every ISL endpoint must reference the satellite catalog")
        if endpoint_a == endpoint_b:
            raise ValueError("an ISL window requires two different satellites")
        endpoint_a, endpoint_b = sorted((endpoint_a, endpoint_b))
        row["endpoint_a"] = endpoint_a
        row["endpoint_b"] = endpoint_b
        _validate_window(row, time, "ISL window")
    rows.sort(key=lambda item: _window_sort_key(item, "endpoint_a", "endpoint_b"))
    rows = _deduplicate_rows(
        rows,
        key=lambda item: (
            float(item["start_s"]),
            str(item["endpoint_a"]),
            str(item["endpoint_b"]),
            float(item["end_s"]),
        ),
        label="ISL windows",
    )
    for index, row in enumerate(rows):
        row["link_id"] = f"isl:{row['endpoint_a']}:{row['endpoint_b']}"
        row["window_id"] = f"isl-{index:08d}"
    return rows


def _prepare_sunlight_windows(
    values: Iterable[Mapping[str, Any]],
    satellite_ids: set[str],
    time: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = _prepare_rows(
        values,
        "sunlight_windows",
        _WRITER_METADATA_FIELDS | {"window_id"},
    )
    for row in rows:
        _validate_satellite_reference(row, "satellite_id", satellite_ids, "sunlight window")
        _validate_window(row, time, "sunlight window")
        if "sunlit" not in row and "eclipsed" not in row:
            raise ValueError("every sunlight window requires sunlit or eclipsed")
        if "sunlit" in row:
            row["sunlit"] = bool(row["sunlit"])
        if "eclipsed" in row:
            row["eclipsed"] = bool(row["eclipsed"])
        if "sunlit" in row and "eclipsed" in row and row["sunlit"] == row["eclipsed"]:
            raise ValueError("sunlit and eclipsed must be logical opposites")
    rows.sort(key=lambda item: _window_sort_key(item, "satellite_id"))
    rows = _deduplicate_rows(
        rows,
        key=lambda item: (
            str(item["satellite_id"]),
            float(item["start_s"]),
            float(item["end_s"]),
        ),
        label="sunlight windows",
    )
    for index, row in enumerate(rows):
        row["window_id"] = f"sunlight-{index:08d}"
    return rows


def _prepare_rows(
    values: Iterable[Mapping[str, Any]],
    label: str,
    removed_fields: set[str],
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes, Mapping)):
        raise TypeError(f"{label} must be an iterable of mappings")
    rows: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise TypeError(f"{label}[{index}] must be a mapping")
        row = {str(key): item for key, item in value.items() if str(key) not in removed_fields}
        _reject_forbidden_fields(row, f"{label}[{index}]")
        rows.append(_normalise_value(row))
    return rows


def _validate_window(row: dict[str, Any], time: Mapping[str, Any], label: str) -> None:
    start_s = _bounded_time(row.get("start_s"), time, f"{label}.start_s", allow_end=False)
    end_s = _bounded_time(row.get("end_s"), time, f"{label}.end_s", allow_end=True)
    if start_s >= end_s:
        raise ValueError(f"{label} must use a non-empty half-open interval [start_s, end_s)")
    row["start_s"] = start_s
    row["end_s"] = end_s
    row["duration_s"] = _finite_float(end_s - start_s, f"{label}.duration_s", time_value=True)


def _window_sort_key(row: Mapping[str, Any], *identity_fields: str) -> tuple[Any, ...]:
    return (
        float(row["start_s"]),
        *(str(row[field]) for field in identity_fields),
        float(row["end_s"]),
        _canonical_json_bytes(row),
    )


def _deduplicate_rows(
    rows: list[dict[str, Any]],
    *,
    key: Callable[[Mapping[str, Any]], Any],
    label: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    by_key: dict[Any, dict[str, Any]] = {}
    for row in rows:
        identity = key(row)
        existing = by_key.get(identity)
        if existing is None:
            by_key[identity] = row
            result.append(row)
            continue
        if existing != row:
            raise ValueError(f"conflicting duplicate identity in {label}: {identity!r}")
    return result


def _validate_satellite_reference(
    row: dict[str, Any],
    field: str,
    satellite_ids: set[str],
    label: str,
) -> None:
    satellite_id = str(row.get(field) or "").strip()
    if satellite_id not in satellite_ids:
        raise ValueError(f"{label} references unknown satellite_id {satellite_id!r}")
    row[field] = satellite_id


def _bounded_time(value: Any, time: Mapping[str, Any], label: str, *, allow_end: bool) -> float:
    result = _finite_float(value, label, time_value=True)
    start_s = float(time["start_s"])
    end_s = float(time["end_s"])
    if result < start_s or result > end_s or (result == end_s and not allow_end):
        raise ValueError(f"{label} lies outside the declared trace time range")
    return result


def _prepare_provenance(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    provenance = _require_mapping(value, "provenance")
    reserved = {"algorithm_version", "writer"}.intersection(provenance)
    if reserved:
        raise ValueError(f"provenance cannot override writer-controlled fields: {sorted(reserved)}")
    _reject_host_metadata(provenance, "provenance")
    return _normalise_value(provenance)


def _reject_forbidden_fields(value: Any, location: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in _FORBIDDEN_GEOMETRY_FIELDS:
                raise ValueError(f"Runtime/Architecture-owned field {key!r} is not allowed in {location}")
            _reject_forbidden_fields(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_forbidden_fields(item, f"{location}[{index}]")


def _reject_host_metadata(value: Any, location: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in _HOST_METADATA_FIELDS:
                raise ValueError(f"host/output-specific metadata {key!r} is not allowed in {location}")
            _reject_host_metadata(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_host_metadata(item, f"{location}[{index}]")


def _normalise_value(value: Any, *, field_name: str | None = None) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return _finite_float(value, field_name or "float", time_value=field_name in _TIME_FIELDS)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            if not isinstance(key, str):
                raise TypeError("Orbit Trace JSON object keys must be strings")
            result[key] = _normalise_value(value[key], field_name=key)
        return result
    if isinstance(value, (list, tuple)):
        return [_normalise_value(item, field_name=field_name) for item in value]
    raise TypeError(f"unsupported Orbit Trace value type: {type(value).__name__}")


def _finite_float(value: Any, label: str, *, time_value: bool) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    result = round(result, 9) if time_value else float(format(result, ".15g"))
    return 0.0 if result == 0.0 else result


def _canonical_json_bytes(value: Any) -> bytes:
    normalised = _normalise_value(value)
    text = json.dumps(
        normalised,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return text.encode("utf-8") + b"\n"


def _manifest_source(
    source: str | Path | Mapping[str, Any] | OrbitTraceManifest,
    base_dir: str | Path | None,
) -> tuple[dict[str, Any], Path, bool]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        return _read_json_mapping(path), path.parent.resolve(), True
    if isinstance(source, OrbitTraceManifest):
        if base_dir is None:
            raise ValueError("base_dir is required when loading an OrbitTraceManifest object")
        return source.to_dict(), Path(base_dir).resolve(), False
    if isinstance(source, Mapping):
        if base_dir is None:
            raise ValueError("base_dir is required when loading an Orbit Trace manifest mapping")
        return dict(source), Path(base_dir).resolve(), True
    raise TypeError("trace_manifest must be a path, mapping, or OrbitTraceManifest")


def _resolve_relative_trace_path(root: Path, value: str) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"Orbit Trace file path must be relative POSIX syntax: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Orbit Trace file path escapes its trace directory: {value!r}")
    path = root.joinpath(*relative.parts).resolve()
    if path != root and root not in path.parents:
        raise ValueError(f"Orbit Trace file path escapes its trace directory: {value!r}")
    if not path.is_file():
        raise ValueError(f"Orbit Trace file is missing: {value!r}")
    return path


def _read_json_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to read Orbit Trace JSON: {path}") from exc
    return _require_mapping(value, str(path))


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): item for key, item in value.items()}


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "ORBIT_TRACE_ALGORITHM",
    "ORBIT_TRACE_SCHEMA",
    "ORBIT_TRACE_SCOPE",
    "OrbitTraceBundle",
    "OrbitTraceManifest",
    "load_orbit_trace",
    "write_orbit_trace",
]
