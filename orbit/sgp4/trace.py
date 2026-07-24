"""SGP4 geometry adapter for the canonical Orbit Trace writer."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..trace import OrbitTraceManifest, write_orbit_trace
from .elements import Sgp4ElementBundle, load_sgp4_element_bundle
from .frames import (
    Sgp4EarthFixedResult,
    Sgp4ItrsSample,
    compute_sgp4_sun_positions_itrs,
    transform_sgp4_teme_to_itrs,
)
from .geometry import (
    SGP4_GEOMETRY_SCHEMA,
    Sgp4GeometryResult,
    Sgp4GroundIngress,
    evaluate_sgp4_geometry,
)
from .propagation import (
    Sgp4PropagationResult,
    Sgp4TemeSample,
    propagate_sgp4_teme,
)


SGP4_ORBIT_TRACE_ADAPTER_ALGORITHM_VERSION = "sgp4-orbit-trace-adapter"
SGP4_ORBIT_TRACE_MODEL = "sgp4-wgs72-teme-astropy-itrs-wgs84"


def generate_orbit_trace(
    output_dir: str | Path,
    *,
    elements: str | Path | Mapping[str, Any] | Sgp4ElementBundle,
    simulation_epoch_utc: str,
    sample_times_s: Sequence[float],
    ground_ingresses: Sequence[Mapping[str, Any] | Sgp4GroundIngress],
    isl_pairs: Sequence[Sequence[str]] = (),
    valid_for_paper_main_results: bool = False,
    warnings: Sequence[str] = (),
) -> OrbitTraceManifest:
    """Generate one canonical Orbit Trace from structured SGP4 inputs."""

    bundle = load_sgp4_element_bundle(elements)
    propagation = propagate_sgp4_teme(
        bundle,
        simulation_epoch_utc=simulation_epoch_utc,
        sample_times_s=sample_times_s,
    )
    earth_fixed = transform_sgp4_teme_to_itrs(propagation)
    sun_positions = compute_sgp4_sun_positions_itrs(earth_fixed)
    geometry = evaluate_sgp4_geometry(
        earth_fixed,
        ground_ingresses=ground_ingresses,
        isl_pairs=isl_pairs,
        sun_positions=sun_positions,
    )
    return write_sgp4_orbit_trace(
        output_dir,
        elements=bundle,
        propagation=propagation,
        earth_fixed=earth_fixed,
        geometry=geometry,
        valid_for_paper_main_results=valid_for_paper_main_results,
        warnings=warnings,
    )


def write_sgp4_orbit_trace(
    output_dir: str | Path,
    *,
    elements: str | Path | Mapping[str, Any] | Sgp4ElementBundle,
    propagation: Sgp4PropagationResult,
    earth_fixed: Sgp4EarthFixedResult,
    geometry: Sgp4GeometryResult,
    valid_for_paper_main_results: bool = False,
    warnings: Sequence[str] = (),
) -> OrbitTraceManifest:
    """Write aligned SGP4 states and geometry through the Orbit Trace writer."""

    bundle = load_sgp4_element_bundle(elements)
    if not isinstance(valid_for_paper_main_results, bool):
        raise TypeError("valid_for_paper_main_results must be boolean")
    canonical_warnings = _prepare_warnings(warnings)
    times, paired_samples = _validate_aligned_inputs(
        bundle, propagation, earth_fixed, geometry
    )
    step_s = _uniform_step(times)

    automatic_warnings = [
        "SGP4 Orbit Trace generation is not yet consumed by Runtime or DSE"
    ]
    if not bundle.provenance.observationally_fitted:
        automatic_warnings.append(
            "SGP4 mean elements are synthetic and are not observationally fitted"
        )
    if earth_fixed.earth_orientation_quality == "predictive":
        automatic_warnings.append("Earth orientation uses predictive IERS-A values")

    return write_orbit_trace(
        output_dir,
        time={
            "epoch": propagation.simulation_epoch_utc,
            "start_s": times[0],
            "end_s": times[-1],
            "duration_s": times[-1] - times[0],
            "step_s": step_s,
            "time_scale": "utc",
        },
        satellite_catalog=_satellite_catalog(bundle),
        ephemeris_samples=_ephemeris_rows(paired_samples),
        sgl_windows=_sgl_window_rows(geometry),
        isl_windows=_isl_window_rows(geometry),
        sunlight_windows=_sunlight_window_rows(geometry),
        trace_model=SGP4_ORBIT_TRACE_MODEL,
        valid_for_paper_main_results=valid_for_paper_main_results,
        provenance=_trace_provenance(bundle, propagation, earth_fixed, geometry),
        warnings=tuple((*canonical_warnings, *automatic_warnings)),
    )


def _validate_aligned_inputs(
    bundle: Sgp4ElementBundle,
    propagation: Any,
    earth_fixed: Any,
    geometry: Any,
) -> tuple[
    tuple[float, ...],
    tuple[tuple[Sgp4TemeSample, Sgp4ItrsSample], ...],
]:
    if not isinstance(propagation, Sgp4PropagationResult):
        raise TypeError("propagation must be Sgp4PropagationResult")
    if not isinstance(earth_fixed, Sgp4EarthFixedResult):
        raise TypeError("earth_fixed must be Sgp4EarthFixedResult")
    if not isinstance(geometry, Sgp4GeometryResult):
        raise TypeError("geometry must be Sgp4GeometryResult")
    if geometry.schema_version != SGP4_GEOMETRY_SCHEMA:
        raise ValueError(f"geometry.schema_version must be {SGP4_GEOMETRY_SCHEMA}")

    identity = (
        ("propagation", propagation.element_set_id),
        ("earth_fixed", earth_fixed.element_set_id),
        ("geometry", geometry.element_set_id),
    )
    for label, element_set_id in identity:
        if element_set_id != bundle.element_set_id:
            raise ValueError(f"{label}.element_set_id does not match elements")
    for label, epoch in (
        ("earth_fixed", earth_fixed.simulation_epoch_utc),
        ("geometry", geometry.simulation_epoch_utc),
    ):
        if epoch != propagation.simulation_epoch_utc:
            raise ValueError(f"{label}.simulation_epoch_utc does not match propagation")
    if propagation.gravity_model != bundle.gravity_model:
        raise ValueError("propagation.gravity_model does not match elements")
    if propagation.ops_mode != bundle.ops_mode:
        raise ValueError("propagation.ops_mode does not match elements")
    if propagation.reference_frame != "TEME":
        raise ValueError("propagation.reference_frame must be TEME")
    if propagation.position_unit != "km" or propagation.velocity_unit != "km/s":
        raise ValueError("propagation state units must be km and km/s")
    if earth_fixed.source_algorithm_version != propagation.algorithm_version:
        raise ValueError(
            "earth_fixed.source_algorithm_version does not match propagation"
        )
    if earth_fixed.source_reference_frame != propagation.reference_frame:
        raise ValueError("earth_fixed.source_reference_frame does not match propagation")
    if earth_fixed.reference_frame != "ITRS":
        raise ValueError("earth_fixed.reference_frame must be ITRS")
    if earth_fixed.position_unit != "km" or earth_fixed.velocity_unit != "km/s":
        raise ValueError("earth_fixed state units must be km and km/s")
    if earth_fixed.network_access:
        raise ValueError("earth_fixed.network_access must be false")
    if geometry.earth_fixed_reference_frame != earth_fixed.reference_frame:
        raise ValueError(
            "geometry.earth_fixed_reference_frame does not match earth_fixed"
        )

    source_provenance = (
        (
            "geometry.earth_fixed_algorithm_version",
            geometry.earth_fixed_algorithm_version,
            earth_fixed.algorithm_version,
        ),
        (
            "geometry.iers_data_release",
            geometry.iers_data_release,
            earth_fixed.iers_data_release,
        ),
        ("geometry.iers_a_sha256", geometry.iers_a_sha256, earth_fixed.iers_a_sha256),
        (
            "geometry.iers_readme_sha256",
            geometry.iers_readme_sha256,
            earth_fixed.iers_readme_sha256,
        ),
        (
            "geometry.leap_seconds_sha256",
            geometry.leap_seconds_sha256,
            earth_fixed.leap_seconds_sha256,
        ),
        (
            "geometry.earth_orientation_quality",
            geometry.earth_orientation_quality,
            earth_fixed.earth_orientation_quality,
        ),
        (
            "geometry.earth_fixed_engine_name",
            geometry.earth_fixed_engine_name,
            earth_fixed.engine_name,
        ),
        (
            "geometry.earth_fixed_engine_version",
            geometry.earth_fixed_engine_version,
            earth_fixed.engine_version,
        ),
        (
            "geometry.astropy_iers_data_version",
            geometry.astropy_iers_data_version,
            earth_fixed.astropy_iers_data_version,
        ),
    )
    for label, actual, expected in source_provenance:
        if actual != expected:
            raise ValueError(f"{label} does not match earth_fixed")

    propagation_keys = _validate_teme_samples(propagation.samples)
    earth_fixed_keys = _validate_itrs_samples(earth_fixed.samples)
    if propagation_keys != earth_fixed_keys:
        raise ValueError("TEME and ITRS samples must have identical ordered keys")
    bundle_ids = tuple(element.satellite_id for element in bundle.satellites)
    sample_ids = tuple(sorted({satellite_id for _, satellite_id in propagation_keys}))
    if sample_ids != bundle_ids:
        raise ValueError("state samples must contain every element-bundle satellite")
    times = tuple(sorted({time_s for time_s, _ in propagation_keys}))
    if len(times) < 2:
        raise ValueError("Orbit Trace requires at least two SGP4 sample times")
    if geometry.interval_start_s != times[0] or geometry.interval_end_s != times[-1]:
        raise ValueError("geometry interval does not match the SGP4 sample grid")
    _validate_geometry_sample_grid(geometry, times, bundle_ids)
    return times, tuple(zip(propagation.samples, earth_fixed.samples, strict=True))


def _validate_teme_samples(
    samples: Sequence[Sgp4TemeSample],
) -> tuple[tuple[float, str], ...]:
    keys: list[tuple[float, str]] = []
    for sample in samples:
        if not isinstance(sample, Sgp4TemeSample):
            raise TypeError("propagation.samples must contain Sgp4TemeSample values")
        keys.append((_sample_time(sample.time_s), _identifier(sample.satellite_id)))
        _vector(sample.position_teme_km, "position_teme_km")
        _vector(sample.velocity_teme_km_s, "velocity_teme_km_s")
    if tuple(keys) != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("propagation.samples must be unique and canonically ordered")
    return tuple(keys)


def _validate_itrs_samples(
    samples: Sequence[Sgp4ItrsSample],
) -> tuple[tuple[float, str], ...]:
    keys: list[tuple[float, str]] = []
    for sample in samples:
        if not isinstance(sample, Sgp4ItrsSample):
            raise TypeError("earth_fixed.samples must contain Sgp4ItrsSample values")
        keys.append((_sample_time(sample.time_s), _identifier(sample.satellite_id)))
        _vector(sample.position_itrs_km, "position_itrs_km")
        _vector(sample.velocity_itrs_km_s, "velocity_itrs_km_s")
    if tuple(keys) != tuple(sorted(keys)) or len(keys) != len(set(keys)):
        raise ValueError("earth_fixed.samples must be unique and canonically ordered")
    return tuple(keys)


def _validate_geometry_sample_grid(
    geometry: Sgp4GeometryResult,
    times: tuple[float, ...],
    satellite_ids: tuple[str, ...],
) -> None:
    ingress_ids = tuple(ingress.ingress_id for ingress in geometry.ground_ingresses)
    if ingress_ids != tuple(sorted(ingress_ids)) or len(ingress_ids) != len(set(ingress_ids)):
        raise ValueError("geometry.ground_ingresses must be unique and canonically ordered")
    if geometry.isl_pairs != tuple(sorted(geometry.isl_pairs)) or len(
        geometry.isl_pairs
    ) != len(set(geometry.isl_pairs)):
        raise ValueError("geometry.isl_pairs must be unique and canonically ordered")

    expected_sgl = tuple(
        (time_s, ingress_id, satellite_id)
        for time_s in times
        for ingress_id in ingress_ids
        for satellite_id in satellite_ids
    )
    actual_sgl = tuple(
        (sample.time_s, sample.ingress_id, sample.satellite_id)
        for sample in geometry.sgl_samples
    )
    if actual_sgl != expected_sgl:
        raise ValueError("geometry.sgl_samples do not match the complete state grid")
    expected_isl = tuple(
        (time_s, endpoint_a, endpoint_b)
        for time_s in times
        for endpoint_a, endpoint_b in geometry.isl_pairs
    )
    actual_isl = tuple(
        (sample.time_s, sample.endpoint_a, sample.endpoint_b)
        for sample in geometry.isl_samples
    )
    if actual_isl != expected_isl:
        raise ValueError("geometry.isl_samples do not match the complete state grid")
    expected_sunlight = tuple(
        (time_s, satellite_id) for time_s in times for satellite_id in satellite_ids
    )
    actual_sunlight = tuple(
        (sample.time_s, sample.satellite_id) for sample in geometry.sunlight_samples
    )
    if actual_sunlight != expected_sunlight:
        raise ValueError("geometry.sunlight_samples do not match the complete state grid")


def _uniform_step(times: tuple[float, ...]) -> float:
    step_s = round(times[1] - times[0], 9)
    if step_s <= 0.0:
        raise ValueError("SGP4 sample times must be strictly increasing")
    for previous, current in zip(times, times[1:]):
        if round(current - previous, 9) != step_s:
            raise ValueError("Orbit Trace requires a uniform SGP4 sample grid")
    return step_s


def _satellite_catalog(bundle: Sgp4ElementBundle) -> tuple[dict[str, Any], ...]:
    return tuple(element.to_dict() for element in bundle.satellites)


def _ephemeris_rows(
    samples: tuple[tuple[Sgp4TemeSample, Sgp4ItrsSample], ...],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "time_s": teme.time_s,
            "satellite_id": teme.satellite_id,
            "position_teme_km": list(teme.position_teme_km),
            "velocity_teme_km_s": list(teme.velocity_teme_km_s),
            "position_itrs_km": list(itrs.position_itrs_km),
            "velocity_itrs_km_s": list(itrs.velocity_itrs_km_s),
            "source_reference_frame": "TEME",
            "earth_fixed_reference_frame": "ITRS",
        }
        for teme, itrs in samples
    )


def _sgl_window_rows(geometry: Sgp4GeometryResult) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for window in geometry.sgl_windows:
        samples = [
            sample
            for sample in geometry.sgl_samples
            if sample.ingress_id == window.ingress_id
            and sample.satellite_id == window.satellite_id
            and sample.visible
            and window.start_s <= sample.time_s <= window.end_s
        ]
        row = {
            **window.to_dict(),
            "geometry_model": geometry.sgl_model,
        }
        _add_min_max(
            row,
            samples,
            "propagation_delay_s",
            "propagation_delay_min_s",
            "propagation_delay_max_s",
        )
        _add_min_max(
            row, samples, "slant_range_km", "slant_range_min_km", "slant_range_max_km"
        )
        _add_min_max(
            row, samples, "elevation_deg", "elevation_min_deg", "elevation_max_deg"
        )
        rows.append(row)
    return tuple(rows)


def _isl_window_rows(geometry: Sgp4GeometryResult) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for window in geometry.isl_windows:
        samples = [
            sample
            for sample in geometry.isl_samples
            if sample.endpoint_a == window.endpoint_a
            and sample.endpoint_b == window.endpoint_b
            and sample.visible
            and window.start_s <= sample.time_s <= window.end_s
        ]
        row = {
            **window.to_dict(),
            "geometry_model": geometry.isl_model,
        }
        _add_min_max(
            row,
            samples,
            "propagation_delay_s",
            "propagation_delay_min_s",
            "propagation_delay_max_s",
        )
        _add_min_max(row, samples, "distance_km", "distance_min_km", "distance_max_km")
        _add_min_max(
            row,
            samples,
            "earth_clearance_km",
            "earth_clearance_min_km",
            "earth_clearance_max_km",
        )
        rows.append(row)
    return tuple(rows)


def _sunlight_window_rows(geometry: Sgp4GeometryResult) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for window in geometry.sunlight_windows:
        samples = [
            sample
            for sample in geometry.sunlight_samples
            if sample.satellite_id == window.satellite_id
            and sample.sunlit == window.sunlit
            and window.start_s <= sample.time_s <= window.end_s
        ]
        row = {
            **window.to_dict(),
            "geometry_model": geometry.sunlight_model,
        }
        _add_min_max(
            row,
            samples,
            "shadow_margin_km",
            "shadow_margin_min_km",
            "shadow_margin_max_km",
        )
        _add_min_max(
            row,
            samples,
            "sun_distance_km",
            "sun_distance_min_km",
            "sun_distance_max_km",
        )
        rows.append(row)
    return tuple(rows)


def _add_min_max(
    row: dict[str, Any],
    samples: Sequence[Any],
    attribute: str,
    minimum_field: str,
    maximum_field: str,
) -> None:
    if not samples:
        return
    values = [float(getattr(sample, attribute)) for sample in samples]
    row[minimum_field] = min(values)
    row[maximum_field] = max(values)


def _trace_provenance(
    bundle: Sgp4ElementBundle,
    propagation: Sgp4PropagationResult,
    earth_fixed: Sgp4EarthFixedResult,
    geometry: Sgp4GeometryResult,
) -> dict[str, Any]:
    return {
        "sgp4_trace_adapter": {
            "algorithm_version": SGP4_ORBIT_TRACE_ADAPTER_ALGORITHM_VERSION,
            "trace_model": SGP4_ORBIT_TRACE_MODEL,
        },
        "element_input": {
            "element_set_id": bundle.element_set_id,
            "schema_version": bundle.schema_version,
            "element_semantics": bundle.element_semantics,
            "gravity_model": bundle.gravity_model,
            "ops_mode": bundle.ops_mode,
            "time_scale": bundle.time_scale,
            "provenance": bundle.provenance.to_dict(),
        },
        "propagation": {
            "algorithm_version": propagation.algorithm_version,
            "engine_name": propagation.engine_name,
            "engine_version": propagation.engine_version,
            "gravity_model": propagation.gravity_model,
            "ops_mode": propagation.ops_mode,
            "reference_frame": propagation.reference_frame,
        },
        "earth_fixed_transform": {
            "algorithm_version": earth_fixed.algorithm_version,
            "engine_name": earth_fixed.engine_name,
            "engine_version": earth_fixed.engine_version,
            "astropy_iers_data_version": earth_fixed.astropy_iers_data_version,
            "iers_data_release": earth_fixed.iers_data_release,
            "iers_a_sha256": earth_fixed.iers_a_sha256,
            "iers_readme_sha256": earth_fixed.iers_readme_sha256,
            "leap_seconds_sha256": earth_fixed.leap_seconds_sha256,
            "earth_orientation_quality": earth_fixed.earth_orientation_quality,
            "source_reference_frame": earth_fixed.source_reference_frame,
            "reference_frame": earth_fixed.reference_frame,
            "network_access": earth_fixed.network_access,
        },
        "geometry": {
            "schema_version": geometry.schema_version,
            "algorithm_version": geometry.algorithm_version,
            "sun_position_algorithm_version": geometry.sun_position_algorithm_version,
            "sgl_model": geometry.sgl_model,
            "isl_model": geometry.isl_model,
            "sunlight_model": geometry.sunlight_model,
            "isl_clearance_km": geometry.isl_clearance_km,
            "shadow_atmosphere_margin_km": geometry.shadow_atmosphere_margin_km,
        },
    }


def _prepare_warnings(values: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("warnings must be a sequence of strings")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError("warnings must contain strings")
        text = value.strip()
        if not text:
            raise ValueError("warnings must not contain empty strings")
        result.append(text)
    return tuple(sorted(set(result)))


def _sample_time(value: Any) -> float:
    result = _finite_float(value, "sample.time_s")
    result = round(result, 9)
    if result < 0.0:
        raise ValueError("sample.time_s must be non-negative")
    return 0.0 if result == 0.0 else result


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("satellite_id must be a non-empty string")
    return value.strip()


def _vector(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must contain exactly three finite numbers")
    if len(value) != 3:
        raise ValueError(f"{label} must contain exactly three finite numbers")
    result = tuple(_finite_float(item, label) for item in value)
    return result[0], result[1], result[2]


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


__all__ = [
    "SGP4_ORBIT_TRACE_ADAPTER_ALGORITHM_VERSION",
    "SGP4_ORBIT_TRACE_MODEL",
    "generate_orbit_trace",
    "write_sgp4_orbit_trace",
]
