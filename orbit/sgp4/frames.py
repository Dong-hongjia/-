"""Pinned-data TEME to ITRS transformation for SGP4 state samples."""

from __future__ import annotations

import hashlib
import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import RLock
from typing import Any

from .propagation import (
    SGP4_PROPAGATION_ALGORITHM_VERSION,
    SGP4_REFERENCE_FRAME,
    Sgp4PropagationResult,
    Sgp4TemeSample,
    _offset_julian,
    _utc_to_julian,
)


SGP4_FRAME_TRANSFORM_ALGORITHM_VERSION = "astropy-teme-itrs-v1"
SGP4_SUN_POSITION_ALGORITHM_VERSION = "astropy-get-sun-itrs-v1"
ASTROPY_ENGINE_NAME = "astropy"
ASTROPY_ENGINE_VERSION = "6.1.3"
SGP4_EARTH_FIXED_REFERENCE_FRAME = "ITRS"
PINNED_IERS_DATA_RELEASE = "astropy-iers-data-0.2026.5.11.1.8.52"
PINNED_IERS_A_SHA256 = "eeb76193cd43c065b763d78923f8a8ce2f8a62df5d3e1519a3217fac433bdaa6"
PINNED_IERS_README_SHA256 = "7c6182cc0fd0cbece39711f648d15e48b49168925602e360a5709c5ccc8d5a12"
PINNED_LEAP_SECONDS_SHA256 = "6f7bc6a25841bc394f82bdfd5d7bb22ffcd4548ee28e9822f2927a909e4f912f"

_PINNED_IERS_ROOT = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "iers"
    / "0.2026.5.11.1.8.52"
)
_PINNED_IERS_A_PATH = _PINNED_IERS_ROOT / "finals2000A.all"
_PINNED_IERS_README_PATH = _PINNED_IERS_ROOT / "ReadMe.finals2000A"
_PINNED_LEAP_SECONDS_PATH = _PINNED_IERS_ROOT / "Leap_Second.dat"

_TRANSFORM_LOCK = RLock()


@dataclass(frozen=True)
class Sgp4ItrsSample:
    """One Earth-fixed SGP4 state in ITRS coordinates."""

    time_s: float
    satellite_id: str
    position_itrs_km: tuple[float, float, float]
    velocity_itrs_km_s: tuple[float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "satellite_id": self.satellite_id,
            "position_itrs_km": list(self.position_itrs_km),
            "velocity_itrs_km_s": list(self.velocity_itrs_km_s),
        }


@dataclass(frozen=True)
class Sgp4EarthFixedResult:
    """Complete ITRS transformation result with immutable data provenance."""

    element_set_id: str
    simulation_epoch_utc: str
    samples: tuple[Sgp4ItrsSample, ...]
    iers_a_sha256: str
    iers_readme_sha256: str
    leap_seconds_sha256: str
    earth_orientation_quality: str
    iers_data_release: str
    astropy_iers_data_version: str
    algorithm_version: str = SGP4_FRAME_TRANSFORM_ALGORITHM_VERSION
    source_algorithm_version: str = SGP4_PROPAGATION_ALGORITHM_VERSION
    engine_name: str = ASTROPY_ENGINE_NAME
    engine_version: str = ASTROPY_ENGINE_VERSION
    source_reference_frame: str = SGP4_REFERENCE_FRAME
    reference_frame: str = SGP4_EARTH_FIXED_REFERENCE_FRAME
    position_unit: str = "km"
    velocity_unit: str = "km/s"
    network_access: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_set_id": self.element_set_id,
            "simulation_epoch_utc": self.simulation_epoch_utc,
            "algorithm_version": self.algorithm_version,
            "source_algorithm_version": self.source_algorithm_version,
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "astropy_iers_data_version": self.astropy_iers_data_version,
            "iers_data_release": self.iers_data_release,
            "source_reference_frame": self.source_reference_frame,
            "reference_frame": self.reference_frame,
            "position_unit": self.position_unit,
            "velocity_unit": self.velocity_unit,
            "iers_a_sha256": self.iers_a_sha256,
            "iers_readme_sha256": self.iers_readme_sha256,
            "leap_seconds_sha256": self.leap_seconds_sha256,
            "earth_orientation_quality": self.earth_orientation_quality,
            "network_access": self.network_access,
            "samples": [sample.to_dict() for sample in self.samples],
        }


@dataclass(frozen=True)
class Sgp4SunPositionSample:
    """One geocentric Sun position in the ITRS frame."""

    time_s: float
    position_itrs_km: tuple[float, float, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "time_s": self.time_s,
            "position_itrs_km": list(self.position_itrs_km),
        }


@dataclass(frozen=True)
class Sgp4SunPositionResult:
    """Sun positions evaluated on an Earth-fixed result's sample grid."""

    element_set_id: str
    simulation_epoch_utc: str
    samples: tuple[Sgp4SunPositionSample, ...]
    iers_a_sha256: str
    iers_readme_sha256: str
    leap_seconds_sha256: str
    earth_orientation_quality: str
    iers_data_release: str
    astropy_iers_data_version: str
    algorithm_version: str = SGP4_SUN_POSITION_ALGORITHM_VERSION
    engine_name: str = ASTROPY_ENGINE_NAME
    engine_version: str = ASTROPY_ENGINE_VERSION
    reference_frame: str = SGP4_EARTH_FIXED_REFERENCE_FRAME
    position_unit: str = "km"
    network_access: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_set_id": self.element_set_id,
            "simulation_epoch_utc": self.simulation_epoch_utc,
            "algorithm_version": self.algorithm_version,
            "engine_name": self.engine_name,
            "engine_version": self.engine_version,
            "astropy_iers_data_version": self.astropy_iers_data_version,
            "iers_data_release": self.iers_data_release,
            "reference_frame": self.reference_frame,
            "position_unit": self.position_unit,
            "iers_a_sha256": self.iers_a_sha256,
            "iers_readme_sha256": self.iers_readme_sha256,
            "leap_seconds_sha256": self.leap_seconds_sha256,
            "earth_orientation_quality": self.earth_orientation_quality,
            "network_access": self.network_access,
            "samples": [sample.to_dict() for sample in self.samples],
        }


class Sgp4FrameTransformError(RuntimeError):
    """A fail-closed coordinate transformation or pinned-data error."""

    def __init__(
        self,
        message: str,
        *,
        time_s: float | None = None,
        satellite_id: str | None = None,
    ) -> None:
        self.time_s = time_s
        self.satellite_id = satellite_id
        context = []
        if time_s is not None:
            context.append(f"time_s={time_s}")
        if satellite_id is not None:
            context.append(f"satellite_id={satellite_id!r}")
        suffix = f" ({', '.join(context)})" if context else ""
        super().__init__(f"{message}{suffix}")


@dataclass(frozen=True)
class _AstropyApi:
    Time: Any
    TEME: Any
    ITRS: Any
    CartesianRepresentation: Any
    CartesianDifferential: Any
    units: Any
    iers: Any
    erfa: Any
    time_core: Any
    get_sun: Any
    iers_data_version: str


def transform_sgp4_teme_to_itrs(
    propagation: Sgp4PropagationResult,
    *,
    iers_a_path: str | Path | None = None,
    leap_seconds_path: str | Path | None = None,
) -> Sgp4EarthFixedResult:
    """Transform one canonical TEME result to ITRS using pinned local data.

    No network update or cache-selected Earth-orientation table is allowed.
    The complete call fails if a sample falls outside either pinned data file.
    """

    _validate_propagation_result(propagation)
    api = _load_astropy_api()
    use_default_iers = iers_a_path is None
    use_default_leap = leap_seconds_path is None
    iers_path = _resolve_data_path(iers_a_path or _PINNED_IERS_A_PATH, "IERS-A")
    leap_path = _resolve_data_path(
        leap_seconds_path or _PINNED_LEAP_SECONDS_PATH, "leap-second"
    )
    iers_sha256 = _file_sha256(iers_path)
    iers_readme_path = _resolve_data_path(_PINNED_IERS_README_PATH, "IERS-A ReadMe")
    iers_readme_sha256 = _file_sha256(iers_readme_path)
    leap_sha256 = _file_sha256(leap_path)
    if use_default_iers and iers_sha256 != PINNED_IERS_A_SHA256:
        raise Sgp4FrameTransformError("bundled IERS-A file SHA-256 mismatch")
    if use_default_leap and leap_sha256 != PINNED_LEAP_SECONDS_SHA256:
        raise Sgp4FrameTransformError("bundled leap-second file SHA-256 mismatch")
    if iers_readme_sha256 != PINNED_IERS_README_SHA256:
        raise Sgp4FrameTransformError("bundled IERS-A ReadMe SHA-256 mismatch")
    data_release = _data_release(iers_sha256, leap_sha256)

    try:
        with (
            api.iers.conf.set_temp("auto_download", False),
            warnings.catch_warnings(),
        ):
            warnings.filterwarnings("ignore", category=api.iers.IERSStaleWarning)
            iers_table = api.iers.IERS_A.open(
                str(iers_path), readme=str(iers_readme_path)
            )
            leap_table = api.iers.LeapSeconds.open(str(leap_path))
    except Exception as exc:
        raise Sgp4FrameTransformError(
            f"failed to load pinned Earth-orientation data: {exc}"
        ) from exc

    start_jd, start_fr = _utc_to_julian(propagation.simulation_epoch_utc)
    unique_times = sorted({sample.time_s for sample in propagation.samples})
    astropy_times = {
        time_s: _astropy_time(api, start_jd, start_fr, time_s) for time_s in unique_times
    }
    quality = _validate_data_coverage(api, iers_table, leap_table, astropy_times)

    samples: list[Sgp4ItrsSample] = []
    with _TRANSFORM_LOCK:
        saved_leap_seconds = api.erfa.leap_seconds.get().copy()
        saved_leap_check = api.time_core._LEAP_SECONDS_CHECK
        try:
            api.time_core._LEAP_SECONDS_CHECK = api.time_core._LeapSecondsCheck.DONE
            api.erfa.leap_seconds.set(leap_table)
            with (
                api.iers.conf.set_temp("auto_download", False),
                api.iers.conf.set_temp("iers_degraded_accuracy", "error"),
                api.iers.earth_orientation_table.set(iers_table),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("error")
                warnings.filterwarnings("ignore", category=api.iers.IERSStaleWarning)
                for sample in propagation.samples:
                    try:
                        transformed = _transform_sample(
                            api, sample, astropy_times[sample.time_s]
                        )
                    except Warning as exc:
                        raise Sgp4FrameTransformError(
                            f"Astropy transformation warning: {exc}",
                            time_s=sample.time_s,
                            satellite_id=sample.satellite_id,
                        ) from exc
                    except Exception as exc:
                        raise Sgp4FrameTransformError(
                            f"Astropy transformation failed: {exc}",
                            time_s=sample.time_s,
                            satellite_id=sample.satellite_id,
                        ) from exc
                    samples.append(transformed)
        except Sgp4FrameTransformError:
            raise
        except Warning as exc:
            raise Sgp4FrameTransformError(f"Astropy transformation warning: {exc}") from exc
        except Exception as exc:
            raise Sgp4FrameTransformError(f"Astropy transformation failed: {exc}") from exc
        finally:
            api.erfa.leap_seconds.set(saved_leap_seconds)
            api.time_core._LEAP_SECONDS_CHECK = saved_leap_check

    return Sgp4EarthFixedResult(
        element_set_id=propagation.element_set_id,
        simulation_epoch_utc=propagation.simulation_epoch_utc,
        samples=tuple(samples),
        iers_a_sha256=iers_sha256,
        iers_readme_sha256=iers_readme_sha256,
        leap_seconds_sha256=leap_sha256,
        earth_orientation_quality=quality,
        iers_data_release=data_release,
        astropy_iers_data_version=api.iers_data_version,
        source_algorithm_version=propagation.algorithm_version,
    )


def compute_sgp4_sun_positions_itrs(
    earth_fixed: Sgp4EarthFixedResult,
    *,
    iers_a_path: str | Path | None = None,
    leap_seconds_path: str | Path | None = None,
) -> Sgp4SunPositionResult:
    """Evaluate deterministic ITRS Sun positions on an SGP4 sample grid.

    The Earth-orientation inputs must have the same hashes and provenance as
    ``earth_fixed``. The complete call fails on any mismatch or warning.
    """

    _validate_earth_fixed_result(earth_fixed)
    api = _load_astropy_api()
    iers_path = _resolve_data_path(iers_a_path or _PINNED_IERS_A_PATH, "IERS-A")
    leap_path = _resolve_data_path(
        leap_seconds_path or _PINNED_LEAP_SECONDS_PATH, "leap-second"
    )
    readme_path = _resolve_data_path(_PINNED_IERS_README_PATH, "IERS-A ReadMe")
    iers_sha256 = _file_sha256(iers_path)
    readme_sha256 = _file_sha256(readme_path)
    leap_sha256 = _file_sha256(leap_path)
    provenance = (
        ("IERS-A", iers_sha256, earth_fixed.iers_a_sha256),
        ("IERS-A ReadMe", readme_sha256, earth_fixed.iers_readme_sha256),
        ("leap-second", leap_sha256, earth_fixed.leap_seconds_sha256),
    )
    for label, actual, expected in provenance:
        if actual != expected:
            raise Sgp4FrameTransformError(
                f"{label} SHA-256 does not match the Earth-fixed result"
            )
    if api.iers_data_version != earth_fixed.astropy_iers_data_version:
        raise Sgp4FrameTransformError(
            "installed astropy-iers-data version does not match the Earth-fixed result"
        )

    try:
        with api.iers.conf.set_temp("auto_download", False), warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=api.iers.IERSStaleWarning)
            iers_table = api.iers.IERS_A.open(str(iers_path), readme=str(readme_path))
            leap_table = api.iers.LeapSeconds.open(str(leap_path))
    except Exception as exc:
        raise Sgp4FrameTransformError(
            f"failed to load pinned Earth-orientation data: {exc}"
        ) from exc

    start_jd, start_fr = _utc_to_julian(earth_fixed.simulation_epoch_utc)
    unique_times = sorted({sample.time_s for sample in earth_fixed.samples})
    astropy_times = {
        time_s: _astropy_time(api, start_jd, start_fr, time_s) for time_s in unique_times
    }
    quality = _validate_data_coverage(api, iers_table, leap_table, astropy_times)
    if quality != earth_fixed.earth_orientation_quality:
        raise Sgp4FrameTransformError(
            "Earth-orientation quality does not match the Earth-fixed result"
        )

    samples: list[Sgp4SunPositionSample] = []
    with _TRANSFORM_LOCK:
        saved_leap_seconds = api.erfa.leap_seconds.get().copy()
        saved_leap_check = api.time_core._LEAP_SECONDS_CHECK
        try:
            api.time_core._LEAP_SECONDS_CHECK = api.time_core._LeapSecondsCheck.DONE
            api.erfa.leap_seconds.set(leap_table)
            with (
                api.iers.conf.set_temp("auto_download", False),
                api.iers.conf.set_temp("iers_degraded_accuracy", "error"),
                api.iers.earth_orientation_table.set(iers_table),
                warnings.catch_warnings(),
            ):
                warnings.simplefilter("error")
                warnings.filterwarnings("ignore", category=api.iers.IERSStaleWarning)
                for time_s in unique_times:
                    try:
                        sun = api.get_sun(astropy_times[time_s]).transform_to(
                            api.ITRS(obstime=astropy_times[time_s])
                        )
                        position = _validated_vector(
                            sun.cartesian.xyz.to_value(api.units.km),
                            "sun_position_itrs_km",
                        )
                    except Warning as exc:
                        raise Sgp4FrameTransformError(
                            f"Astropy Sun-position warning: {exc}", time_s=time_s
                        ) from exc
                    except Exception as exc:
                        raise Sgp4FrameTransformError(
                            f"Astropy Sun-position calculation failed: {exc}",
                            time_s=time_s,
                        ) from exc
                    samples.append(
                        Sgp4SunPositionSample(
                            time_s=time_s,
                            position_itrs_km=position,
                        )
                    )
        finally:
            api.erfa.leap_seconds.set(saved_leap_seconds)
            api.time_core._LEAP_SECONDS_CHECK = saved_leap_check

    return Sgp4SunPositionResult(
        element_set_id=earth_fixed.element_set_id,
        simulation_epoch_utc=earth_fixed.simulation_epoch_utc,
        samples=tuple(samples),
        iers_a_sha256=iers_sha256,
        iers_readme_sha256=readme_sha256,
        leap_seconds_sha256=leap_sha256,
        earth_orientation_quality=quality,
        iers_data_release=earth_fixed.iers_data_release,
        astropy_iers_data_version=api.iers_data_version,
    )


def _load_astropy_api() -> _AstropyApi:
    try:
        installed_version = version("astropy")
    except PackageNotFoundError as exc:
        raise RuntimeError(
            f"TEME to ITRS conversion requires astropy=={ASTROPY_ENGINE_VERSION}"
        ) from exc
    if installed_version != ASTROPY_ENGINE_VERSION:
        raise RuntimeError(
            f"TEME to ITRS conversion requires astropy=={ASTROPY_ENGINE_VERSION}; "
            f"found {installed_version}"
        )
    try:
        iers_data_version = version("astropy-iers-data")
        import erfa
        from astropy import units
        from astropy.coordinates import (
            ITRS,
            TEME,
            CartesianDifferential,
            CartesianRepresentation,
            get_sun,
        )
        from astropy.time import Time
        from astropy.time import core as time_core
        from astropy.utils import iers
    except (ImportError, PackageNotFoundError) as exc:
        raise RuntimeError(
            "TEME to ITRS conversion requires astropy==6.1.3 and astropy-iers-data"
        ) from exc
    return _AstropyApi(
        Time=Time,
        TEME=TEME,
        ITRS=ITRS,
        CartesianRepresentation=CartesianRepresentation,
        CartesianDifferential=CartesianDifferential,
        units=units,
        iers=iers,
        erfa=erfa,
        time_core=time_core,
        get_sun=get_sun,
        iers_data_version=iers_data_version,
    )


def _validate_propagation_result(propagation: Any) -> None:
    if not isinstance(propagation, Sgp4PropagationResult):
        raise TypeError("propagation must be Sgp4PropagationResult")
    if propagation.reference_frame != SGP4_REFERENCE_FRAME:
        raise ValueError(f"propagation.reference_frame must be {SGP4_REFERENCE_FRAME}")
    if not propagation.samples:
        raise ValueError("propagation.samples must be non-empty")
    keys = [(sample.time_s, sample.satellite_id) for sample in propagation.samples]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError("propagation.samples must be unique and ordered by (time_s, satellite_id)")
    for sample in propagation.samples:
        if not isinstance(sample, Sgp4TemeSample):
            raise TypeError("propagation.samples must contain Sgp4TemeSample values")
        _validated_vector(sample.position_teme_km, "position_teme_km")
        _validated_vector(sample.velocity_teme_km_s, "velocity_teme_km_s")


def _validate_earth_fixed_result(earth_fixed: Any) -> None:
    if not isinstance(earth_fixed, Sgp4EarthFixedResult):
        raise TypeError("earth_fixed must be Sgp4EarthFixedResult")
    if earth_fixed.reference_frame != SGP4_EARTH_FIXED_REFERENCE_FRAME:
        raise ValueError(
            f"earth_fixed.reference_frame must be {SGP4_EARTH_FIXED_REFERENCE_FRAME}"
        )
    if earth_fixed.engine_name != ASTROPY_ENGINE_NAME:
        raise ValueError(f"earth_fixed.engine_name must be {ASTROPY_ENGINE_NAME}")
    if earth_fixed.engine_version != ASTROPY_ENGINE_VERSION:
        raise ValueError(f"earth_fixed.engine_version must be {ASTROPY_ENGINE_VERSION}")
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
    for sample in earth_fixed.samples:
        if not isinstance(sample, Sgp4ItrsSample):
            raise TypeError("earth_fixed.samples must contain Sgp4ItrsSample values")
        _validated_vector(sample.position_itrs_km, "position_itrs_km")
        _validated_vector(sample.velocity_itrs_km_s, "velocity_itrs_km_s")


def _resolve_data_path(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise Sgp4FrameTransformError(f"pinned {label} file does not exist: {path}")
    return path


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _data_release(iers_sha256: str, leap_sha256: str) -> str:
    if (
        iers_sha256 == PINNED_IERS_A_SHA256
        and leap_sha256 == PINNED_LEAP_SECONDS_SHA256
    ):
        return PINNED_IERS_DATA_RELEASE
    return f"external-sha256-{iers_sha256[:16]}-{leap_sha256[:16]}"


def _astropy_time(api: _AstropyApi, jd: float, fr: float, time_s: float) -> Any:
    sample_jd, sample_fr = _offset_julian(jd, fr, time_s)
    return api.Time(sample_jd, sample_fr, format="jd", scale="utc")


def _validate_data_coverage(
    api: _AstropyApi,
    iers_table: Any,
    leap_table: Any,
    astropy_times: Mapping[float, Any],
) -> str:
    predictive = False
    if leap_table.expires is None:
        raise Sgp4FrameTransformError("pinned leap-second file has no validity expiry")
    leap_expiry_jd = float(leap_table.expires.jd)
    for time_s, obstime in astropy_times.items():
        if float(obstime.utc.jd) >= leap_expiry_jd:
            raise Sgp4FrameTransformError(
                "sample is outside the pinned leap-second file validity",
                time_s=time_s,
            )
        _, ut1_status = iers_table.ut1_utc(obstime, return_status=True)
        _, _, polar_status = iers_table.pm_xy(obstime, return_status=True)
        statuses = (int(ut1_status), int(polar_status))
        if api.iers.TIME_BEYOND_IERS_RANGE in statuses:
            raise Sgp4FrameTransformError(
                "sample is outside the pinned IERS-A table coverage",
                time_s=time_s,
            )
        if api.iers.FROM_IERS_A_PREDICTION in statuses:
            predictive = True
    return "predictive" if predictive else "definitive"


def _transform_sample(api: _AstropyApi, sample: Sgp4TemeSample, obstime: Any) -> Sgp4ItrsSample:
    units = api.units
    position = api.CartesianRepresentation(sample.position_teme_km * units.km)
    velocity = api.CartesianDifferential(sample.velocity_teme_km_s * units.km / units.s)
    teme = api.TEME(position.with_differentials(velocity), obstime=obstime)
    itrs = teme.transform_to(api.ITRS(obstime=obstime))
    position_itrs = _validated_vector(
        itrs.cartesian.xyz.to_value(units.km), "position_itrs_km"
    )
    velocity_itrs = _validated_vector(
        itrs.cartesian.differentials["s"].d_xyz.to_value(units.km / units.s),
        "velocity_itrs_km_s",
    )
    return Sgp4ItrsSample(
        time_s=sample.time_s,
        satellite_id=sample.satellite_id,
        position_itrs_km=position_itrs,
        velocity_itrs_km_s=velocity_itrs,
    )


def _validated_vector(value: Any, label: str) -> tuple[float, float, float]:
    try:
        result = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain exactly three finite numbers") from exc
    if len(result) != 3:
        raise ValueError(f"{label} must contain exactly three finite numbers")
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{label} must contain exactly three finite numbers")
    return result[0], result[1], result[2]
