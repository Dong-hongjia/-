"""Deterministic geometric facts derived from Earth-fixed SGP4 states."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .frames import (
    SGP4_EARTH_FIXED_REFERENCE_FRAME,
    Sgp4EarthFixedResult,
    Sgp4ItrsSample,
    Sgp4SunPositionResult,
    Sgp4SunPositionSample,
    compute_sgp4_sun_positions_itrs,
)


SGP4_GEOMETRY_SCHEMA = "orbitserve.sgp4_geometry.v1"
SGP4_GEOMETRY_ALGORITHM_VERSION = "sgp4-wgs84-geometry-v1"
SGP4_SGL_GEOMETRY_MODEL = "wgs84-geodetic-elevation-v1"
SGP4_ISL_GEOMETRY_MODEL = "wgs84-ellipsoid-segment-occultation-v1"
SGP4_SUNLIGHT_GEOMETRY_MODEL = "astropy-sun-conical-umbra-v1"

WGS84_SEMI_MAJOR_AXIS_KM = 6378.137
WGS84_FLATTENING = 1.0 / 298.257223563
WGS84_SEMI_MINOR_AXIS_KM = WGS84_SEMI_MAJOR_AXIS_KM * (1.0 - WGS84_FLATTENING)
IAU_NOMINAL_SOLAR_RADIUS_KM = 695700.0
C_LIGHT_KM_PER_S = 299792.458

_FLOAT_DIGITS = 9
_GROUND_FIELDS = {
    "ingress_id",
    "lat_deg",
    "lon_deg",
    "altitude_km",
    "min_elevation_deg",
}


@dataclass(frozen=True)
class Sgp4GroundIngress:
    """One geometry-only WGS-84 ground ingress."""

    ingress_id: str
    lat_deg: float
    lon_deg: float
    altitude_km: float = 0.0
    min_elevation_deg: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "ingress_id", _identifier(self.ingress_id, "ingress_id"))
        object.__setattr__(
            self,
            "lat_deg",
            _bounded_float(self.lat_deg, "lat_deg", minimum=-90.0, maximum=90.0),
        )
        object.__setattr__(
            self,
            "lon_deg",
            _bounded_float(self.lon_deg, "lon_deg", minimum=-180.0, maximum=180.0),
        )
        altitude = _finite_float(self.altitude_km, "altitude_km")
        if altitude <= -WGS84_SEMI_MINOR_AXIS_KM:
            raise ValueError("altitude_km must remain outside the WGS-84 Earth centre")
        object.__setattr__(self, "altitude_km", _q(altitude))
        object.__setattr__(
            self,
            "min_elevation_deg",
            _bounded_float(
                self.min_elevation_deg,
                "min_elevation_deg",
                minimum=-90.0,
                maximum=90.0,
            ),
        )

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | "Sgp4GroundIngress") -> "Sgp4GroundIngress":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("ground ingress must be a mapping or Sgp4GroundIngress")
        if any(not isinstance(key, str) for key in value):
            raise TypeError("ground ingress field names must be strings")
        unknown = {str(key) for key in value} - _GROUND_FIELDS
        if unknown:
            raise ValueError(f"ground ingress contains unknown fields: {sorted(unknown)}")
        missing = {"ingress_id", "lat_deg", "lon_deg"} - {str(key) for key in value}
        if missing:
            raise ValueError(f"ground ingress is missing required fields: {sorted(missing)}")
        return cls(
            ingress_id=value["ingress_id"],
            lat_deg=value["lat_deg"],
            lon_deg=value["lon_deg"],
            altitude_km=value.get("altitude_km", 0.0),
            min_elevation_deg=value.get("min_elevation_deg", 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingress_id": self.ingress_id,
            "lat_deg": self.lat_deg,
            "lon_deg": self.lon_deg,
            "altitude_km": self.altitude_km,
            "min_elevation_deg": self.min_elevation_deg,
        }


@dataclass(frozen=True)
class Sgp4SglGeometrySample:
    time_s: float
    ingress_id: str
    satellite_id: str
    visible: bool
    elevation_deg: float
    elevation_margin_deg: float
    slant_range_km: float
    propagation_delay_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "ingress_id": self.ingress_id,
            "satellite_id": self.satellite_id,
            "visible": self.visible,
            "elevation_deg": self.elevation_deg,
            "elevation_margin_deg": self.elevation_margin_deg,
            "slant_range_km": self.slant_range_km,
            "propagation_delay_s": self.propagation_delay_s,
        }


@dataclass(frozen=True)
class Sgp4IslGeometrySample:
    time_s: float
    endpoint_a: str
    endpoint_b: str
    visible: bool
    distance_km: float
    propagation_delay_s: float
    earth_clearance_km: float
    closest_segment_fraction: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "endpoint_a": self.endpoint_a,
            "endpoint_b": self.endpoint_b,
            "visible": self.visible,
            "distance_km": self.distance_km,
            "propagation_delay_s": self.propagation_delay_s,
            "earth_clearance_km": self.earth_clearance_km,
            "closest_segment_fraction": self.closest_segment_fraction,
        }


@dataclass(frozen=True)
class Sgp4SunlightGeometrySample:
    time_s: float
    satellite_id: str
    sunlit: bool
    shadow_margin_km: float
    sun_distance_km: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "satellite_id": self.satellite_id,
            "sunlit": self.sunlit,
            "eclipsed": not self.sunlit,
            "shadow_margin_km": self.shadow_margin_km,
            "sun_distance_km": self.sun_distance_km,
        }


@dataclass(frozen=True)
class Sgp4SglWindow:
    ingress_id: str
    satellite_id: str
    start_s: float
    end_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ingress_id": self.ingress_id,
            "satellite_id": self.satellite_id,
            "start_s": self.start_s,
            "end_s": self.end_s,
        }


@dataclass(frozen=True)
class Sgp4IslWindow:
    endpoint_a: str
    endpoint_b: str
    start_s: float
    end_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_a": self.endpoint_a,
            "endpoint_b": self.endpoint_b,
            "start_s": self.start_s,
            "end_s": self.end_s,
        }


@dataclass(frozen=True)
class Sgp4SunlightWindow:
    satellite_id: str
    start_s: float
    end_s: float
    sunlit: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "satellite_id": self.satellite_id,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "sunlit": self.sunlit,
            "eclipsed": not self.sunlit,
        }


@dataclass(frozen=True)
class Sgp4GeometryResult:
    """Pure geometry samples and half-open windows for one SGP4 state grid."""

    element_set_id: str
    simulation_epoch_utc: str
    interval_start_s: float
    interval_end_s: float
    ground_ingresses: tuple[Sgp4GroundIngress, ...]
    isl_pairs: tuple[tuple[str, str], ...]
    sgl_samples: tuple[Sgp4SglGeometrySample, ...]
    isl_samples: tuple[Sgp4IslGeometrySample, ...]
    sunlight_samples: tuple[Sgp4SunlightGeometrySample, ...]
    sgl_windows: tuple[Sgp4SglWindow, ...]
    isl_windows: tuple[Sgp4IslWindow, ...]
    sunlight_windows: tuple[Sgp4SunlightWindow, ...]
    earth_fixed_algorithm_version: str
    sun_position_algorithm_version: str
    iers_data_release: str
    iers_a_sha256: str
    iers_readme_sha256: str
    leap_seconds_sha256: str
    earth_orientation_quality: str
    earth_fixed_engine_name: str
    earth_fixed_engine_version: str
    astropy_iers_data_version: str
    isl_clearance_km: float
    shadow_atmosphere_margin_km: float
    schema_version: str = SGP4_GEOMETRY_SCHEMA
    algorithm_version: str = SGP4_GEOMETRY_ALGORITHM_VERSION
    earth_fixed_reference_frame: str = SGP4_EARTH_FIXED_REFERENCE_FRAME
    sgl_model: str = SGP4_SGL_GEOMETRY_MODEL
    isl_model: str = SGP4_ISL_GEOMETRY_MODEL
    sunlight_model: str = SGP4_SUNLIGHT_GEOMETRY_MODEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "algorithm_version": self.algorithm_version,
            "element_set_id": self.element_set_id,
            "simulation_epoch_utc": self.simulation_epoch_utc,
            "interval_start_s": self.interval_start_s,
            "interval_end_s": self.interval_end_s,
            "earth_fixed_reference_frame": self.earth_fixed_reference_frame,
            "earth_fixed_algorithm_version": self.earth_fixed_algorithm_version,
            "sun_position_algorithm_version": self.sun_position_algorithm_version,
            "iers_data_release": self.iers_data_release,
            "iers_a_sha256": self.iers_a_sha256,
            "iers_readme_sha256": self.iers_readme_sha256,
            "leap_seconds_sha256": self.leap_seconds_sha256,
            "earth_orientation_quality": self.earth_orientation_quality,
            "earth_fixed_engine_name": self.earth_fixed_engine_name,
            "earth_fixed_engine_version": self.earth_fixed_engine_version,
            "astropy_iers_data_version": self.astropy_iers_data_version,
            "sgl_model": self.sgl_model,
            "isl_model": self.isl_model,
            "sunlight_model": self.sunlight_model,
            "isl_clearance_km": self.isl_clearance_km,
            "shadow_atmosphere_margin_km": self.shadow_atmosphere_margin_km,
            "ground_ingresses": [value.to_dict() for value in self.ground_ingresses],
            "isl_pairs": [list(value) for value in self.isl_pairs],
            "sgl_samples": [value.to_dict() for value in self.sgl_samples],
            "isl_samples": [value.to_dict() for value in self.isl_samples],
            "sunlight_samples": [value.to_dict() for value in self.sunlight_samples],
            "sgl_windows": [value.to_dict() for value in self.sgl_windows],
            "isl_windows": [value.to_dict() for value in self.isl_windows],
            "sunlight_windows": [value.to_dict() for value in self.sunlight_windows],
        }

    def canonical_bytes(self) -> bytes:
        text = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return (text + "\n").encode("utf-8")


def evaluate_sgp4_geometry(
    earth_fixed: Sgp4EarthFixedResult,
    *,
    ground_ingresses: Sequence[Mapping[str, Any] | Sgp4GroundIngress] = (),
    isl_pairs: Sequence[Sequence[str]] = (),
    isl_clearance_km: int | float = 0.0,
    shadow_atmosphere_margin_km: int | float = 0.0,
    sun_positions: Sgp4SunPositionResult | None = None,
) -> Sgp4GeometryResult:
    """Evaluate SGL, ISL, and sunlight geometry on a complete sample grid.

    Geometry is evaluated only on ``[first_sample_time, last_sample_time)``.
    Boolean transitions are refined by deterministic linear interpolation of
    their signed boundary functions. Candidate ISL pairs are explicit inputs;
    this function does not choose a network topology.
    """

    times, satellite_ids, by_time = _validate_earth_fixed_grid(earth_fixed)
    ingresses = _prepare_ground_ingresses(ground_ingresses)
    pairs = _prepare_isl_pairs(isl_pairs, set(satellite_ids))
    isl_margin = _nonnegative_float(isl_clearance_km, "isl_clearance_km")
    shadow_margin = _nonnegative_float(
        shadow_atmosphere_margin_km, "shadow_atmosphere_margin_km"
    )
    if sun_positions is None:
        sun_positions = compute_sgp4_sun_positions_itrs(earth_fixed)
    sun_by_time = _validate_sun_positions(earth_fixed, sun_positions, times)

    sgl_samples: list[Sgp4SglGeometrySample] = []
    isl_samples: list[Sgp4IslGeometrySample] = []
    sunlight_samples: list[Sgp4SunlightGeometrySample] = []
    sgl_scores: dict[tuple[str, str], list[tuple[float, bool, float]]] = {}
    isl_scores: dict[tuple[str, str], list[tuple[float, bool, float]]] = {}
    sunlight_scores: dict[str, list[tuple[float, bool, float]]] = {}

    ground_frames = {
        ingress.ingress_id: _ground_position_and_up(ingress) for ingress in ingresses
    }
    for time_s in times:
        states = by_time[time_s]
        for ingress in ingresses:
            ground_position, ground_up = ground_frames[ingress.ingress_id]
            for satellite_id in satellite_ids:
                state = states[satellite_id]
                elevation, slant_range = _elevation_and_range(
                    ground_position, ground_up, state.position_itrs_km
                )
                score = _q(elevation - ingress.min_elevation_deg)
                visible = score >= 0.0
                sample = Sgp4SglGeometrySample(
                    time_s=_q(time_s),
                    ingress_id=ingress.ingress_id,
                    satellite_id=satellite_id,
                    visible=visible,
                    elevation_deg=_q(elevation),
                    elevation_margin_deg=score,
                    slant_range_km=_q(slant_range),
                    propagation_delay_s=_q(slant_range / C_LIGHT_KM_PER_S),
                )
                sgl_samples.append(sample)
                sgl_scores.setdefault((ingress.ingress_id, satellite_id), []).append(
                    (time_s, visible, score)
                )

        for endpoint_a, endpoint_b in pairs:
            first = states[endpoint_a].position_itrs_km
            second = states[endpoint_b].position_itrs_km
            score, clearance_km, fraction = _ellipsoid_segment_clearance(
                first, second, isl_margin
            )
            distance = _norm(_sub(second, first))
            visible = score > 0.0
            isl_samples.append(
                Sgp4IslGeometrySample(
                    time_s=_q(time_s),
                    endpoint_a=endpoint_a,
                    endpoint_b=endpoint_b,
                    visible=visible,
                    distance_km=_q(distance),
                    propagation_delay_s=_q(distance / C_LIGHT_KM_PER_S),
                    earth_clearance_km=_q(clearance_km),
                    closest_segment_fraction=_q(fraction),
                )
            )
            isl_scores.setdefault((endpoint_a, endpoint_b), []).append(
                (time_s, visible, _q(score))
            )

        sun_position = sun_by_time[time_s]
        sun_distance = _norm(sun_position)
        for satellite_id in satellite_ids:
            score = _sunlight_shadow_margin(
                states[satellite_id].position_itrs_km,
                sun_position,
                shadow_margin,
            )
            score = _q(score)
            sunlit = score >= 0.0
            sunlight_samples.append(
                Sgp4SunlightGeometrySample(
                    time_s=_q(time_s),
                    satellite_id=satellite_id,
                    sunlit=sunlit,
                    shadow_margin_km=score,
                    sun_distance_km=_q(sun_distance),
                )
            )
            sunlight_scores.setdefault(satellite_id, []).append((time_s, sunlit, score))

    sgl_windows = tuple(
        Sgp4SglWindow(key[0], key[1], start, end)
        for key in sorted(sgl_scores)
        for start, end, flag in _state_windows(sgl_scores[key])
        if flag
    )
    isl_windows = tuple(
        Sgp4IslWindow(key[0], key[1], start, end)
        for key in sorted(isl_scores)
        for start, end, flag in _state_windows(isl_scores[key])
        if flag
    )
    sunlight_windows = tuple(
        Sgp4SunlightWindow(satellite_id, start, end, flag)
        for satellite_id in sorted(sunlight_scores)
        for start, end, flag in _state_windows(sunlight_scores[satellite_id])
    )
    return Sgp4GeometryResult(
        element_set_id=earth_fixed.element_set_id,
        simulation_epoch_utc=earth_fixed.simulation_epoch_utc,
        interval_start_s=_q(times[0]),
        interval_end_s=_q(times[-1]),
        ground_ingresses=ingresses,
        isl_pairs=pairs,
        sgl_samples=tuple(sgl_samples),
        isl_samples=tuple(isl_samples),
        sunlight_samples=tuple(sunlight_samples),
        sgl_windows=sgl_windows,
        isl_windows=isl_windows,
        sunlight_windows=sunlight_windows,
        earth_fixed_algorithm_version=earth_fixed.algorithm_version,
        sun_position_algorithm_version=sun_positions.algorithm_version,
        iers_data_release=earth_fixed.iers_data_release,
        iers_a_sha256=earth_fixed.iers_a_sha256,
        iers_readme_sha256=earth_fixed.iers_readme_sha256,
        leap_seconds_sha256=earth_fixed.leap_seconds_sha256,
        earth_orientation_quality=earth_fixed.earth_orientation_quality,
        earth_fixed_engine_name=earth_fixed.engine_name,
        earth_fixed_engine_version=earth_fixed.engine_version,
        astropy_iers_data_version=earth_fixed.astropy_iers_data_version,
        isl_clearance_km=_q(isl_margin),
        shadow_atmosphere_margin_km=_q(shadow_margin),
    )


def _validate_earth_fixed_grid(
    earth_fixed: Any,
) -> tuple[tuple[float, ...], tuple[str, ...], dict[float, dict[str, Sgp4ItrsSample]]]:
    if not isinstance(earth_fixed, Sgp4EarthFixedResult):
        raise TypeError("earth_fixed must be Sgp4EarthFixedResult")
    if earth_fixed.reference_frame != SGP4_EARTH_FIXED_REFERENCE_FRAME:
        raise ValueError(
            f"earth_fixed.reference_frame must be {SGP4_EARTH_FIXED_REFERENCE_FRAME}"
        )
    if earth_fixed.position_unit != "km" or earth_fixed.velocity_unit != "km/s":
        raise ValueError("earth_fixed state units must be km and km/s")
    if earth_fixed.network_access:
        raise ValueError("earth_fixed.network_access must be false")
    if not earth_fixed.samples:
        raise ValueError("earth_fixed.samples must be non-empty")
    keys = [(sample.time_s, sample.satellite_id) for sample in earth_fixed.samples]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError(
            "earth_fixed.samples must be unique and ordered by (time_s, satellite_id)"
        )
    by_time: dict[float, dict[str, Sgp4ItrsSample]] = {}
    for sample in earth_fixed.samples:
        if not isinstance(sample, Sgp4ItrsSample):
            raise TypeError("earth_fixed.samples must contain Sgp4ItrsSample values")
        time_s = _nonnegative_float(sample.time_s, "sample.time_s")
        satellite_id = _identifier(sample.satellite_id, "sample.satellite_id")
        _vector(sample.position_itrs_km, "position_itrs_km")
        _vector(sample.velocity_itrs_km_s, "velocity_itrs_km_s")
        by_time.setdefault(time_s, {})[satellite_id] = sample
    times = tuple(sorted(by_time))
    if len(times) < 2 or times[0] >= times[-1]:
        raise ValueError("geometry window evaluation requires at least two distinct sample times")
    satellite_ids = tuple(sorted(by_time[times[0]]))
    if not satellite_ids:
        raise ValueError("earth_fixed.samples must contain at least one satellite")
    expected = set(satellite_ids)
    for time_s in times:
        if set(by_time[time_s]) != expected:
            raise ValueError("earth_fixed.samples must form a complete rectangular time grid")
    return times, satellite_ids, by_time


def _prepare_ground_ingresses(
    values: Sequence[Mapping[str, Any] | Sgp4GroundIngress],
) -> tuple[Sgp4GroundIngress, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("ground_ingresses must be a sequence")
    result = tuple(sorted((Sgp4GroundIngress.from_value(value) for value in values), key=lambda x: x.ingress_id))
    ids = [value.ingress_id for value in result]
    if len(ids) != len(set(ids)):
        raise ValueError("ground ingress identifiers must be unique")
    return result


def _prepare_isl_pairs(
    values: Sequence[Sequence[str]], satellite_ids: set[str]
) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("isl_pairs must be a sequence of two-satellite sequences")
    result: list[tuple[str, str]] = []
    for index, value in enumerate(values):
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise TypeError(f"isl_pairs[{index}] must be a two-satellite sequence")
        if len(value) != 2:
            raise ValueError(f"isl_pairs[{index}] must contain exactly two satellites")
        endpoint_a = _identifier(value[0], f"isl_pairs[{index}][0]")
        endpoint_b = _identifier(value[1], f"isl_pairs[{index}][1]")
        if endpoint_a == endpoint_b:
            raise ValueError("an ISL pair requires two different satellites")
        if endpoint_a not in satellite_ids or endpoint_b not in satellite_ids:
            raise ValueError("every ISL endpoint must exist in the Earth-fixed sample grid")
        result.append(tuple(sorted((endpoint_a, endpoint_b))))
    if len(result) != len(set(result)):
        raise ValueError("isl_pairs must be unique after canonical endpoint ordering")
    return tuple(sorted(result))


def _validate_sun_positions(
    earth_fixed: Sgp4EarthFixedResult,
    sun_positions: Any,
    times: tuple[float, ...],
) -> dict[float, tuple[float, float, float]]:
    if not isinstance(sun_positions, Sgp4SunPositionResult):
        raise TypeError("sun_positions must be Sgp4SunPositionResult")
    if sun_positions.position_unit != "km":
        raise ValueError("sun_positions.position_unit must be km")
    if sun_positions.network_access:
        raise ValueError("sun_positions.network_access must be false")
    matching = (
        ("element_set_id", sun_positions.element_set_id, earth_fixed.element_set_id),
        ("simulation_epoch_utc", sun_positions.simulation_epoch_utc, earth_fixed.simulation_epoch_utc),
        ("reference_frame", sun_positions.reference_frame, earth_fixed.reference_frame),
        ("iers_a_sha256", sun_positions.iers_a_sha256, earth_fixed.iers_a_sha256),
        ("iers_readme_sha256", sun_positions.iers_readme_sha256, earth_fixed.iers_readme_sha256),
        ("leap_seconds_sha256", sun_positions.leap_seconds_sha256, earth_fixed.leap_seconds_sha256),
        ("earth_orientation_quality", sun_positions.earth_orientation_quality, earth_fixed.earth_orientation_quality),
        ("iers_data_release", sun_positions.iers_data_release, earth_fixed.iers_data_release),
        ("astropy_iers_data_version", sun_positions.astropy_iers_data_version, earth_fixed.astropy_iers_data_version),
    )
    for label, actual, expected in matching:
        if actual != expected:
            raise ValueError(f"sun_positions.{label} does not match earth_fixed")
    for sample in sun_positions.samples:
        if not isinstance(sample, Sgp4SunPositionSample):
            raise TypeError(
                "sun_positions.samples must contain Sgp4SunPositionSample values"
            )
    sample_times = tuple(sample.time_s for sample in sun_positions.samples)
    if sample_times != times:
        raise ValueError("sun_positions must contain exactly one ordered sample per grid time")
    return {
        sample.time_s: _vector(sample.position_itrs_km, "sun_position_itrs_km")
        for sample in sun_positions.samples
    }


def _ground_position_and_up(
    ingress: Sgp4GroundIngress,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    lat = math.radians(ingress.lat_deg)
    lon = math.radians(ingress.lon_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    eccentricity_squared = WGS84_FLATTENING * (2.0 - WGS84_FLATTENING)
    prime_vertical = WGS84_SEMI_MAJOR_AXIS_KM / math.sqrt(
        1.0 - eccentricity_squared * sin_lat * sin_lat
    )
    position = (
        (prime_vertical + ingress.altitude_km) * cos_lat * cos_lon,
        (prime_vertical + ingress.altitude_km) * cos_lat * sin_lon,
        (prime_vertical * (1.0 - eccentricity_squared) + ingress.altitude_km) * sin_lat,
    )
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)
    return position, up


def _elevation_and_range(
    ground_position: tuple[float, float, float],
    ground_up: tuple[float, float, float],
    satellite_position: tuple[float, float, float],
) -> tuple[float, float]:
    line = _sub(satellite_position, ground_position)
    distance = _norm(line)
    if distance <= 0.0:
        return -90.0, 0.0
    sine = _dot(line, ground_up) / distance
    return math.degrees(math.asin(max(-1.0, min(1.0, sine)))), distance


def _ellipsoid_segment_clearance(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    margin_km: float,
) -> tuple[float, float, float]:
    semi_major = WGS84_SEMI_MAJOR_AXIS_KM + margin_km
    semi_minor = WGS84_SEMI_MINOR_AXIS_KM + margin_km
    scaled_first = (first[0] / semi_major, first[1] / semi_major, first[2] / semi_minor)
    scaled_second = (
        second[0] / semi_major,
        second[1] / semi_major,
        second[2] / semi_minor,
    )
    delta = _sub(scaled_second, scaled_first)
    denominator = _dot(delta, delta)
    if denominator <= 0.0:
        fraction = 0.0
    else:
        fraction = max(0.0, min(1.0, -_dot(scaled_first, delta) / denominator))
    closest = _add(scaled_first, _scale(delta, fraction))
    scaled_radius = _norm(closest)
    score = scaled_radius - 1.0
    clearance_km = score * min(semi_major, semi_minor)
    return score, clearance_km, fraction


def _sunlight_shadow_margin(
    satellite_position: tuple[float, float, float],
    sun_position: tuple[float, float, float],
    atmosphere_margin_km: float,
) -> float:
    sun_distance = _norm(sun_position)
    if sun_distance <= 0.0:
        raise ValueError("Sun position must not be the zero vector")
    sun_direction = _scale(sun_position, 1.0 / sun_distance)
    anti_sun_distance = -_dot(satellite_position, sun_direction)
    earth_shadow_radius = WGS84_SEMI_MAJOR_AXIS_KM + atmosphere_margin_km
    if anti_sun_distance <= 0.0:
        return _norm(satellite_position) - earth_shadow_radius
    axis_point = _scale(sun_direction, -anti_sun_distance)
    perpendicular_distance = _norm(_sub(satellite_position, axis_point))
    umbra_radius = earth_shadow_radius - anti_sun_distance * (
        IAU_NOMINAL_SOLAR_RADIUS_KM - earth_shadow_radius
    ) / sun_distance
    if umbra_radius <= 0.0:
        return perpendicular_distance + abs(umbra_radius)
    return perpendicular_distance - umbra_radius


def _state_windows(
    samples: Sequence[tuple[float, bool, float]],
) -> tuple[tuple[float, float, bool], ...]:
    if len(samples) < 2:
        return ()
    windows: list[tuple[float, float, bool]] = []
    current_start = samples[0][0]
    current_flag = samples[0][1]
    previous = samples[0]
    for current in samples[1:]:
        if current[1] != current_flag:
            boundary = _linear_boundary(previous, current)
            if boundary > current_start:
                windows.append((_q(current_start), _q(boundary), current_flag))
            current_start = boundary
            current_flag = current[1]
        previous = current
    end_s = samples[-1][0]
    if end_s > current_start:
        windows.append((_q(current_start), _q(end_s), current_flag))
    return tuple(windows)


def _linear_boundary(
    previous: tuple[float, bool, float], current: tuple[float, bool, float]
) -> float:
    t0, _, score0 = previous
    t1, _, score1 = current
    if score0 == score1:
        return (t0 + t1) / 2.0
    fraction = max(0.0, min(1.0, -score0 / (score1 - score0)))
    return t0 + fraction * (t1 - t0)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a non-empty string")
    result = value.strip()
    if not result:
        raise ValueError(f"{label} must be a non-empty string")
    return result


def _finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _bounded_float(
    value: Any, label: str, *, minimum: float, maximum: float
) -> float:
    result = _finite_float(value, label)
    if result < minimum or result > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return _q(result)


def _nonnegative_float(value: Any, label: str) -> float:
    result = _finite_float(value, label)
    if result < 0.0:
        raise ValueError(f"{label} must be non-negative")
    return _q(result)


def _vector(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must contain exactly three finite numbers")
    if len(value) != 3:
        raise ValueError(f"{label} must contain exactly three finite numbers")
    result = tuple(_finite_float(item, label) for item in value)
    return result[0], result[1], result[2]


def _q(value: float) -> float:
    result = round(float(value), _FLOAT_DIGITS)
    return 0.0 if result == 0.0 else result


def _sub(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return first[0] - second[0], first[1] - second[1], first[2] - second[2]


def _add(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return first[0] + second[0], first[1] + second[1], first[2] + second[2]


def _scale(
    value: tuple[float, float, float], factor: float
) -> tuple[float, float, float]:
    return value[0] * factor, value[1] * factor, value[2] * factor


def _dot(first: tuple[float, float, float], second: tuple[float, float, float]) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _norm(value: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(value, value))
