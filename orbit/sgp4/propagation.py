"""Deterministic direct-element SGP4 propagation in the TEME frame."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .elements import (
    SGP4_GRAVITY_MODEL,
    SGP4_OPS_MODE,
    Sgp4ElementBundle,
    Sgp4SatelliteElements,
    _require_epoch,
    load_sgp4_element_bundle,
)


SGP4_PROPAGATION_ALGORITHM_VERSION = "sgp4-direct-teme-v1"
SGP4_ENGINE_NAME = "python-sgp4"
SGP4_ENGINE_VERSION = "2.27"
SGP4_REFERENCE_FRAME = "TEME"

_MINUTES_PER_DAY = 1440.0
_SECONDS_PER_DAY = 86400.0
_SGP4_EPOCH_JD = 2433281.5


@dataclass(frozen=True)
class Sgp4TemeSample:
    """One successful SGP4 state sample in TEME coordinates."""

    time_s: float
    satellite_id: str
    position_teme_km: tuple[float, float, float]
    velocity_teme_km_s: tuple[float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "satellite_id": self.satellite_id,
            "position_teme_km": list(self.position_teme_km),
            "velocity_teme_km_s": list(self.velocity_teme_km_s),
        }


@dataclass(frozen=True)
class Sgp4PropagationResult:
    """Complete fail-closed result for one bundle and sample grid."""

    element_set_id: str
    simulation_epoch_utc: str
    samples: tuple[Sgp4TemeSample, ...]
    algorithm_version: str = SGP4_PROPAGATION_ALGORITHM_VERSION
    engine_name: str = SGP4_ENGINE_NAME
    engine_version: str = SGP4_ENGINE_VERSION
    gravity_model: str = SGP4_GRAVITY_MODEL
    ops_mode: str = SGP4_OPS_MODE
    reference_frame: str = SGP4_REFERENCE_FRAME
    position_unit: str = "km"
    velocity_unit: str = "km/s"

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_set_id": self.element_set_id,
            "simulation_epoch_utc": self.simulation_epoch_utc,
            "algorithm_version": self.algorithm_version,
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "gravity_model": self.gravity_model,
            "ops_mode": self.ops_mode,
            "reference_frame": self.reference_frame,
            "position_unit": self.position_unit,
            "velocity_unit": self.velocity_unit,
            "samples": [sample.to_dict() for sample in self.samples],
        }


class Sgp4PropagationError(RuntimeError):
    """A fail-closed SGP4 initialization or propagation error."""

    def __init__(
        self,
        *,
        satellite_id: str,
        error_code: int,
        error_message: str,
        time_s: float | None,
    ) -> None:
        self.satellite_id = satellite_id
        self.error_code = int(error_code)
        self.error_message = str(error_message)
        self.time_s = time_s
        at_time = " during initialization" if time_s is None else f" at time_s={time_s}"
        super().__init__(
            f"SGP4 failed for satellite_id={satellite_id!r}{at_time}: "
            f"error_code={error_code}, {error_message}"
        )


@dataclass(frozen=True)
class _Sgp4Api:
    Satrec: Any
    WGS72: Any
    errors: Mapping[int, str]
    check_satrec: Any


def propagate_sgp4_teme(
    elements: str | Path | Mapping[str, Any] | Sgp4ElementBundle,
    *,
    simulation_epoch_utc: str,
    sample_times_s: Sequence[int | float],
) -> Sgp4PropagationResult:
    """Propagate validated mean elements on a deterministic relative-time grid.

    The complete call fails if any satellite initialization or sample fails.
    Successful samples are ordered by ``(time_s, satellite_id)``.
    """

    bundle = load_sgp4_element_bundle(elements)
    canonical_epoch = _require_epoch(simulation_epoch_utc)
    canonical_times = _prepare_sample_times(sample_times_s)
    api = _load_sgp4_api()
    satellites = {
        element.satellite_id: _initialize_satellite(api, element)
        for element in bundle.satellites
    }
    start_jd, start_fr = _utc_to_julian(canonical_epoch)
    samples: list[Sgp4TemeSample] = []
    for time_s in canonical_times:
        jd, fr = _offset_julian(start_jd, start_fr, time_s)
        for satellite_id in sorted(satellites):
            satrec = satellites[satellite_id]
            try:
                error_code, position, velocity = satrec.sgp4(jd, fr)
            except Exception as exc:
                raise Sgp4PropagationError(
                    satellite_id=satellite_id,
                    time_s=time_s,
                    error_code=-1,
                    error_message=f"SGP4 engine exception: {exc}",
                ) from exc
            error_code = int(error_code)
            if error_code:
                raise Sgp4PropagationError(
                    satellite_id=satellite_id,
                    time_s=time_s,
                    error_code=error_code,
                    error_message=api.errors.get(error_code, "unknown SGP4 error"),
                )
            try:
                canonical_position = _state_vector(position, "position_teme_km")
                canonical_velocity = _state_vector(velocity, "velocity_teme_km_s")
            except (TypeError, ValueError, RuntimeError) as exc:
                raise Sgp4PropagationError(
                    satellite_id=satellite_id,
                    time_s=time_s,
                    error_code=-2,
                    error_message=str(exc),
                ) from exc
            samples.append(
                Sgp4TemeSample(
                    time_s=time_s,
                    satellite_id=satellite_id,
                    position_teme_km=canonical_position,
                    velocity_teme_km_s=canonical_velocity,
                )
            )
    return Sgp4PropagationResult(
        element_set_id=bundle.element_set_id,
        simulation_epoch_utc=canonical_epoch,
        samples=tuple(samples),
    )


def _load_sgp4_api() -> _Sgp4Api:
    try:
        installed_version = version("sgp4")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            "SGP4 propagation requires the optional dependency sgp4==2.27"
        ) from exc
    if installed_version != SGP4_ENGINE_VERSION:
        raise RuntimeError(
            f"SGP4 propagation requires sgp4=={SGP4_ENGINE_VERSION}; "
            f"found {installed_version}"
        )
    try:
        from sgp4.api import SGP4_ERRORS, WGS72, Satrec
        from sgp4.conveniences import check_satrec
    except ImportError as exc:
        raise RuntimeError(
            "SGP4 propagation requires a complete sgp4==2.27 installation"
        ) from exc
    return _Sgp4Api(Satrec=Satrec, WGS72=WGS72, errors=SGP4_ERRORS, check_satrec=check_satrec)


def _initialize_satellite(api: _Sgp4Api, element: Sgp4SatelliteElements) -> Any:
    epoch_jd, epoch_fr = _utc_to_julian(element.epoch_utc)
    epoch_days = (epoch_jd - _SGP4_EPOCH_JD) + epoch_fr
    radians_per_degree = math.pi / 180.0
    radians_per_revolution = 2.0 * math.pi
    satrec = api.Satrec()
    try:
        satrec.sgp4init(
            api.WGS72,
            "i",
            element.satnum,
            epoch_days,
            element.bstar_inv_earth_radii,
            element.mean_motion_dot_rev_per_day2
            * radians_per_revolution
            / (_MINUTES_PER_DAY**2),
            element.mean_motion_ddot_rev_per_day3
            * radians_per_revolution
            / (_MINUTES_PER_DAY**3),
            element.eccentricity,
            element.argument_of_perigee_deg * radians_per_degree,
            element.inclination_deg * radians_per_degree,
            element.mean_anomaly_deg * radians_per_degree,
            element.mean_motion_rev_per_day * radians_per_revolution / _MINUTES_PER_DAY,
            element.raan_deg * radians_per_degree,
        )
    except Exception as exc:
        raise Sgp4PropagationError(
            satellite_id=element.satellite_id,
            time_s=None,
            error_code=-1,
            error_message=f"SGP4 initialization exception: {exc}",
        ) from exc
    satrec.classification = element.classification
    satrec.elnum = element.element_set_number
    satrec.revnum = element.revolution_number_at_epoch
    satrec.intldesg = _tle_international_designator(element.object_id)
    # sgp4init() receives a single epoch float. Restore the canonical split
    # epoch so later propagation retains the full precision of the input UTC.
    satrec.jdsatepoch = epoch_jd
    satrec.jdsatepochF = epoch_fr
    try:
        api.check_satrec(satrec)
    except ValueError as exc:
        raise Sgp4PropagationError(
            satellite_id=element.satellite_id,
            time_s=None,
            error_code=int(getattr(satrec, "error", 0)),
            error_message=str(exc),
        ) from exc
    error_code = int(getattr(satrec, "error", 0))
    if error_code:
        raise Sgp4PropagationError(
            satellite_id=element.satellite_id,
            time_s=None,
            error_code=error_code,
            error_message=api.errors.get(error_code, "unknown SGP4 initialization error"),
        )
    return satrec


def _prepare_sample_times(values: Sequence[int | float]) -> tuple[float, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise TypeError("sample_times_s must be a non-empty sequence of finite numbers")
    if not values:
        raise ValueError("sample_times_s must be non-empty")
    normalized: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("sample_times_s values must be finite numbers")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("sample_times_s values must be finite")
        number = round(number, 9)
        if number == 0.0:
            number = 0.0
        if number < 0.0:
            raise ValueError("sample_times_s values must be non-negative")
        normalized.append(number)
    if len(set(normalized)) != len(normalized):
        raise ValueError("sample_times_s values must be unique after 9-decimal normalization")
    return tuple(sorted(normalized))


def _utc_to_julian(epoch_utc: str) -> tuple[float, float]:
    timestamp = datetime.strptime(epoch_utc, "%Y-%m-%dT%H:%M:%S.%fZ")
    year = timestamp.year
    month = timestamp.month
    day = timestamp.day
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    julian_day_number = (
        day
        + (153 * m + 2) // 5
        + 365 * y
        + y // 4
        - y // 100
        + y // 400
        - 32045
    )
    seconds = (
        timestamp.hour * 3600
        + timestamp.minute * 60
        + timestamp.second
        + timestamp.microsecond / 1_000_000.0
    )
    return float(julian_day_number) - 0.5, seconds / _SECONDS_PER_DAY


def _offset_julian(jd: float, fr: float, time_s: float) -> tuple[float, float]:
    fraction = fr + time_s / _SECONDS_PER_DAY
    whole_days = math.floor(fraction)
    return jd + whole_days, fraction - whole_days


def _state_vector(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, Sequence) or len(value) != 3:
        raise RuntimeError(f"SGP4 returned an invalid {label}")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result):
        raise RuntimeError(f"SGP4 returned a non-finite {label}")
    return result[0], result[1], result[2]


def _tle_international_designator(object_id: str | None) -> str:
    if object_id is None:
        return ""
    return object_id[2:4] + object_id[5:]
