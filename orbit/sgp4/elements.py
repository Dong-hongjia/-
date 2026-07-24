"""Strict deterministic input models for SGP4-compatible mean elements."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SGP4_ELEMENT_BUNDLE_SCHEMA = "orbitserve.sgp4_element_bundle.v1"
SGP4_ELEMENT_SEMANTICS = "sgp4_mean_elements"
SGP4_GRAVITY_MODEL = "wgs72"
SGP4_OPS_MODE = "improved"
SGP4_TIME_SCALE = "utc"

_SOURCE_KINDS = {
    "observationally_fitted_general_perturbations": True,
    "synthetic_sgp4_mean_elements": False,
}
_BUNDLE_KEYS = {
    "element_semantics",
    "gravity_model",
    "ops_mode",
    "provenance",
    "satellites",
    "schema_version",
    "time_scale",
}
_SATELLITE_REQUIRED_KEYS = {
    "argument_of_perigee_deg",
    "bstar_inv_earth_radii",
    "classification",
    "eccentricity",
    "element_set_number",
    "ephemeris_type",
    "epoch_utc",
    "inclination_deg",
    "mean_anomaly_deg",
    "mean_motion_ddot_rev_per_day3",
    "mean_motion_dot_rev_per_day2",
    "mean_motion_rev_per_day",
    "raan_deg",
    "revolution_number_at_epoch",
    "satellite_id",
    "satnum",
}
_SATELLITE_OPTIONAL_KEYS = {"object_id"}
_PROVENANCE_KEYS = {
    "observationally_fitted",
    "source_kind",
    "source_name",
    "source_version",
}
_EPOCH_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d\.\d{6}Z"
)
_OBJECT_ID_PATTERN = re.compile(r"\d{4}-\d{3}[A-Z0-9]{1,3}")


@dataclass(frozen=True)
class Sgp4ElementProvenance:
    """Deterministic provenance for one SGP4 element bundle."""

    source_kind: str
    source_name: str
    source_version: str
    observationally_fitted: bool

    def __post_init__(self) -> None:
        source_kind = _require_string(self.source_kind, "provenance.source_kind")
        if source_kind not in _SOURCE_KINDS:
            raise ValueError(
                "provenance.source_kind must be synthetic_sgp4_mean_elements or "
                "observationally_fitted_general_perturbations"
            )
        if not isinstance(self.observationally_fitted, bool):
            raise TypeError("provenance.observationally_fitted must be a boolean")
        if self.observationally_fitted is not _SOURCE_KINDS[source_kind]:
            raise ValueError(
                "provenance.observationally_fitted is inconsistent with provenance.source_kind"
            )
        _require_string(self.source_name, "provenance.source_name")
        _require_string(self.source_version, "provenance.source_version")

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | "Sgp4ElementProvenance") -> "Sgp4ElementProvenance":
        if isinstance(value, cls):
            return value
        payload = _require_mapping(value, "provenance")
        _require_exact_keys(payload, _PROVENANCE_KEYS, label="provenance")
        source_kind = _require_string(payload["source_kind"], "provenance.source_kind")
        if source_kind not in _SOURCE_KINDS:
            raise ValueError(
                "provenance.source_kind must be synthetic_sgp4_mean_elements or "
                "observationally_fitted_general_perturbations"
            )
        observationally_fitted = payload["observationally_fitted"]
        if not isinstance(observationally_fitted, bool):
            raise TypeError("provenance.observationally_fitted must be a boolean")
        expected_fitted = _SOURCE_KINDS[source_kind]
        if observationally_fitted is not expected_fitted:
            raise ValueError(
                "provenance.observationally_fitted is inconsistent with provenance.source_kind"
            )
        return cls(
            source_kind=source_kind,
            source_name=_require_string(payload["source_name"], "provenance.source_name"),
            source_version=_require_string(
                payload["source_version"], "provenance.source_version"
            ),
            observationally_fitted=observationally_fitted,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_name": self.source_name,
            "source_version": self.source_version,
            "observationally_fitted": self.observationally_fitted,
        }


@dataclass(frozen=True)
class Sgp4SatelliteElements:
    """One validated, full-precision SGP4 mean-element record."""

    satellite_id: str
    satnum: int
    classification: str
    object_id: str | None
    epoch_utc: str
    inclination_deg: float
    raan_deg: float
    eccentricity: float
    argument_of_perigee_deg: float
    mean_anomaly_deg: float
    mean_motion_rev_per_day: float
    mean_motion_dot_rev_per_day2: float
    mean_motion_ddot_rev_per_day3: float
    bstar_inv_earth_radii: float
    ephemeris_type: int
    element_set_number: int
    revolution_number_at_epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "satellite_id", _require_string(self.satellite_id, "satellite_id"))
        object.__setattr__(
            self, "satnum", _require_integer(self.satnum, "satnum", minimum=1, maximum=339999)
        )
        classification = _require_string(self.classification, "classification")
        if classification not in {"U", "C", "S"}:
            raise ValueError("classification must be one of U, C, or S")
        object.__setattr__(self, "object_id", _require_object_id(self.object_id))
        object.__setattr__(self, "epoch_utc", _require_epoch(self.epoch_utc))
        object.__setattr__(
            self,
            "inclination_deg",
            _require_float_range(
                self.inclination_deg, "inclination_deg", minimum=0.0, maximum=180.0
            ),
        )
        for field_name in ("raan_deg", "argument_of_perigee_deg", "mean_anomaly_deg"):
            object.__setattr__(
                self,
                field_name,
                _require_float_range(
                    getattr(self, field_name),
                    field_name,
                    minimum=0.0,
                    maximum=360.0,
                    maximum_inclusive=False,
                ),
            )
        object.__setattr__(
            self,
            "eccentricity",
            _require_float_range(
                self.eccentricity,
                "eccentricity",
                minimum=0.0,
                maximum=1.0,
                maximum_inclusive=False,
            ),
        )
        object.__setattr__(
            self,
            "mean_motion_rev_per_day",
            _require_positive_float(self.mean_motion_rev_per_day, "mean_motion_rev_per_day"),
        )
        for field_name in (
            "mean_motion_dot_rev_per_day2",
            "mean_motion_ddot_rev_per_day3",
            "bstar_inv_earth_radii",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_finite_float(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "ephemeris_type",
            _require_integer(self.ephemeris_type, "ephemeris_type", minimum=0, maximum=0),
        )
        object.__setattr__(
            self,
            "element_set_number",
            _require_integer(
                self.element_set_number, "element_set_number", minimum=0, maximum=9999
            ),
        )
        object.__setattr__(
            self,
            "revolution_number_at_epoch",
            _require_integer(
                self.revolution_number_at_epoch,
                "revolution_number_at_epoch",
                minimum=0,
                maximum=99999,
            ),
        )

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | "Sgp4SatelliteElements") -> "Sgp4SatelliteElements":
        if isinstance(value, cls):
            return value
        payload = _require_mapping(value, "satellite element record")
        _require_exact_keys(
            payload,
            _SATELLITE_REQUIRED_KEYS,
            optional=_SATELLITE_OPTIONAL_KEYS,
            label="satellite element record",
        )
        satellite_id = _require_string(payload["satellite_id"], "satellite_id")
        satnum = _require_integer(payload["satnum"], "satnum", minimum=1, maximum=339999)
        classification = _require_string(payload["classification"], "classification")
        if classification not in {"U", "C", "S"}:
            raise ValueError("classification must be one of U, C, or S")
        object_id = _require_object_id(payload.get("object_id"))
        epoch_utc = _require_epoch(payload["epoch_utc"])

        ephemeris_type = _require_integer(
            payload["ephemeris_type"], "ephemeris_type", minimum=0, maximum=0
        )
        return cls(
            satellite_id=satellite_id,
            satnum=satnum,
            classification=classification,
            object_id=object_id,
            epoch_utc=epoch_utc,
            inclination_deg=_require_float_range(
                payload["inclination_deg"], "inclination_deg", minimum=0.0, maximum=180.0
            ),
            raan_deg=_require_float_range(
                payload["raan_deg"], "raan_deg", minimum=0.0, maximum=360.0, maximum_inclusive=False
            ),
            eccentricity=_require_float_range(
                payload["eccentricity"],
                "eccentricity",
                minimum=0.0,
                maximum=1.0,
                maximum_inclusive=False,
            ),
            argument_of_perigee_deg=_require_float_range(
                payload["argument_of_perigee_deg"],
                "argument_of_perigee_deg",
                minimum=0.0,
                maximum=360.0,
                maximum_inclusive=False,
            ),
            mean_anomaly_deg=_require_float_range(
                payload["mean_anomaly_deg"],
                "mean_anomaly_deg",
                minimum=0.0,
                maximum=360.0,
                maximum_inclusive=False,
            ),
            mean_motion_rev_per_day=_require_positive_float(
                payload["mean_motion_rev_per_day"], "mean_motion_rev_per_day"
            ),
            mean_motion_dot_rev_per_day2=_require_finite_float(
                payload["mean_motion_dot_rev_per_day2"], "mean_motion_dot_rev_per_day2"
            ),
            mean_motion_ddot_rev_per_day3=_require_finite_float(
                payload["mean_motion_ddot_rev_per_day3"], "mean_motion_ddot_rev_per_day3"
            ),
            bstar_inv_earth_radii=_require_finite_float(
                payload["bstar_inv_earth_radii"], "bstar_inv_earth_radii"
            ),
            ephemeris_type=ephemeris_type,
            element_set_number=_require_integer(
                payload["element_set_number"], "element_set_number", minimum=0, maximum=9999
            ),
            revolution_number_at_epoch=_require_integer(
                payload["revolution_number_at_epoch"],
                "revolution_number_at_epoch",
                minimum=0,
                maximum=99999,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "satellite_id": self.satellite_id,
            "satnum": self.satnum,
            "classification": self.classification,
            "object_id": self.object_id,
            "epoch_utc": self.epoch_utc,
            "inclination_deg": self.inclination_deg,
            "raan_deg": self.raan_deg,
            "eccentricity": self.eccentricity,
            "argument_of_perigee_deg": self.argument_of_perigee_deg,
            "mean_anomaly_deg": self.mean_anomaly_deg,
            "mean_motion_rev_per_day": self.mean_motion_rev_per_day,
            "mean_motion_dot_rev_per_day2": self.mean_motion_dot_rev_per_day2,
            "mean_motion_ddot_rev_per_day3": self.mean_motion_ddot_rev_per_day3,
            "bstar_inv_earth_radii": self.bstar_inv_earth_radii,
            "ephemeris_type": self.ephemeris_type,
            "element_set_number": self.element_set_number,
            "revolution_number_at_epoch": self.revolution_number_at_epoch,
        }


@dataclass(frozen=True)
class Sgp4ElementBundle:
    """Canonical SGP4 input bundle exposed by :mod:`orbitserve.orbit`."""

    satellites: tuple[Sgp4SatelliteElements, ...]
    provenance: Sgp4ElementProvenance
    schema_version: str = SGP4_ELEMENT_BUNDLE_SCHEMA
    element_semantics: str = SGP4_ELEMENT_SEMANTICS
    gravity_model: str = SGP4_GRAVITY_MODEL
    ops_mode: str = SGP4_OPS_MODE
    time_scale: str = SGP4_TIME_SCALE

    def __post_init__(self) -> None:
        for field_name, expected in (
            ("schema_version", SGP4_ELEMENT_BUNDLE_SCHEMA),
            ("element_semantics", SGP4_ELEMENT_SEMANTICS),
            ("gravity_model", SGP4_GRAVITY_MODEL),
            ("ops_mode", SGP4_OPS_MODE),
            ("time_scale", SGP4_TIME_SCALE),
        ):
            if getattr(self, field_name) != expected:
                raise ValueError(f"{field_name} must be exactly {expected!r}")
        if not isinstance(self.satellites, tuple) or not self.satellites:
            raise TypeError("satellites must be a non-empty tuple of Sgp4SatelliteElements")
        if not all(isinstance(item, Sgp4SatelliteElements) for item in self.satellites):
            raise TypeError("satellites must contain only Sgp4SatelliteElements")
        if not isinstance(self.provenance, Sgp4ElementProvenance):
            raise TypeError("provenance must be Sgp4ElementProvenance")
        satellite_ids = [item.satellite_id for item in self.satellites]
        satnums = [item.satnum for item in self.satellites]
        if len(set(satellite_ids)) != len(satellite_ids):
            raise ValueError("satellite_id values must be unique")
        if len(set(satnums)) != len(satnums):
            raise ValueError("satnum values must be unique")
        object.__setattr__(
            self, "satellites", tuple(sorted(self.satellites, key=lambda item: item.satellite_id))
        )

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | "Sgp4ElementBundle") -> "Sgp4ElementBundle":
        if isinstance(value, cls):
            return value
        payload = _require_mapping(value, "SGP4 element bundle")
        _require_exact_keys(payload, _BUNDLE_KEYS, label="SGP4 element bundle")
        _require_constant(payload, "schema_version", SGP4_ELEMENT_BUNDLE_SCHEMA)
        _require_constant(payload, "element_semantics", SGP4_ELEMENT_SEMANTICS)
        _require_constant(payload, "gravity_model", SGP4_GRAVITY_MODEL)
        _require_constant(payload, "ops_mode", SGP4_OPS_MODE)
        _require_constant(payload, "time_scale", SGP4_TIME_SCALE)

        raw_satellites = payload["satellites"]
        if not isinstance(raw_satellites, Sequence) or isinstance(
            raw_satellites, (str, bytes, bytearray)
        ):
            raise TypeError("satellites must be a JSON array")
        if not raw_satellites:
            raise ValueError("satellites must be non-empty")
        satellites = tuple(Sgp4SatelliteElements.from_value(item) for item in raw_satellites)
        satellite_ids = [item.satellite_id for item in satellites]
        satnums = [item.satnum for item in satellites]
        if len(set(satellite_ids)) != len(satellite_ids):
            raise ValueError("satellite_id values must be unique")
        if len(set(satnums)) != len(satnums):
            raise ValueError("satnum values must be unique")

        return cls(
            satellites=tuple(sorted(satellites, key=lambda item: item.satellite_id)),
            provenance=Sgp4ElementProvenance.from_value(payload["provenance"]),
        )

    @property
    def element_set_id(self) -> str:
        physical_payload = self.to_dict()
        physical_payload.pop("provenance")
        digest = hashlib.sha256(_canonical_json_bytes(physical_payload)).hexdigest()
        return f"sgp4-elements-v1-{digest}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "element_semantics": self.element_semantics,
            "gravity_model": self.gravity_model,
            "ops_mode": self.ops_mode,
            "time_scale": self.time_scale,
            "satellites": [item.to_dict() for item in self.satellites],
            "provenance": self.provenance.to_dict(),
        }

    def canonical_bytes(self) -> bytes:
        """Return deterministic contract JSON using UTF-8, LF, and one newline."""

        return _canonical_json_bytes(self.to_dict())


def load_sgp4_element_bundle(
    source: str | Path | Mapping[str, Any] | Sgp4ElementBundle,
) -> Sgp4ElementBundle:
    """Load and validate an SGP4 element bundle through the Orbit public API."""

    if isinstance(source, Sgp4ElementBundle):
        return source
    if isinstance(source, Mapping):
        return Sgp4ElementBundle.from_value(source)
    if not isinstance(source, (str, Path)):
        raise TypeError("SGP4 element bundle source must be a path, mapping, or bundle")
    path = Path(source)
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"SGP4 element bundle must be UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SGP4 element bundle JSON: {path}") from exc
    return Sgp4ElementBundle.from_value(payload)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{label} keys must be strings")
    return value


def _require_exact_keys(
    payload: Mapping[str, Any],
    required: set[str],
    *,
    optional: set[str] | None = None,
    label: str,
) -> None:
    optional = optional or set()
    missing = sorted(required - set(payload))
    unknown = sorted(set(payload) - required - optional)
    if missing:
        raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _require_constant(payload: Mapping[str, Any], key: str, expected: str) -> None:
    if payload[key] != expected:
        raise ValueError(f"{key} must be exactly {expected!r}")


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")
    return value


def _require_object_id(value: Any) -> str | None:
    if value is None:
        return None
    object_id = _require_string(value, "object_id")
    if _OBJECT_ID_PATTERN.fullmatch(object_id) is None:
        raise ValueError("object_id must use CCSDS form YYYY-NNNPPP or be null")
    return object_id


def _require_epoch(value: Any) -> str:
    epoch_utc = _require_string(value, "epoch_utc")
    if _EPOCH_PATTERN.fullmatch(epoch_utc) is None:
        raise ValueError("epoch_utc must use canonical form YYYY-MM-DDTHH:MM:SS.ffffffZ")
    try:
        datetime.strptime(epoch_utc, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValueError("epoch_utc is not a valid canonical UTC instant") from exc
    return epoch_utc


def _require_integer(value: Any, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be in [{minimum}, {maximum}]")
    return value


def _require_finite_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{label} must be finite")
    if normalized == 0.0:
        return 0.0
    return float(format(normalized, ".15g"))


def _require_positive_float(value: Any, label: str) -> float:
    normalized = _require_finite_float(value, label)
    if normalized <= 0.0:
        raise ValueError(f"{label} must be strictly positive")
    return normalized


def _require_float_range(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float,
    maximum_inclusive: bool = True,
) -> float:
    normalized = _require_finite_float(value, label)
    maximum_ok = normalized <= maximum if maximum_inclusive else normalized < maximum
    if normalized < minimum or not maximum_ok:
        closing = "]" if maximum_inclusive else ")"
        raise ValueError(f"{label} must be in [{minimum}, {maximum}{closing}")
    return normalized


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is not allowed: {value}")
