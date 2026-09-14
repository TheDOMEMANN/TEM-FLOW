"""Joint compositional allocation for evidence-conditioned TEM-FLOW states.

This module turns an observed remainder mass and a historical destination-share
vector into one joint ambiguity set on the simplex.  It is deliberately not a
point predictor.  The calibrated total-variation radius limits how far the
current share vector may depart from its historical reference, while the
simplex and non-negativity constraints preserve competition among branches.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Mapping, Sequence


TOLERANCE = 1e-10


def _finite_nonnegative(value: float, label: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return number


def _normalized_shares(values: Sequence[float]) -> tuple[float, ...]:
    shares = tuple(_finite_nonnegative(value, "share") for value in values)
    if not shares:
        raise ValueError("at least one destination share is required")
    total = sum(shares)
    if total <= 0:
        raise ValueError("destination shares must have a positive sum")
    if abs(total - 1.0) > 1e-8:
        raise ValueError("destination shares must sum to one")
    return tuple(value / total for value in shares)


def total_variation(left: Sequence[float], right: Sequence[float]) -> float:
    """Return one-half of the L1 distance between two share vectors."""

    a = _normalized_shares(left)
    b = _normalized_shares(right)
    if len(a) != len(b):
        raise ValueError("share vectors must have the same length")
    return 0.5 * sum(abs(x - y) for x, y in zip(a, b))


def finite_sample_radius(residuals: Iterable[float], coverage: float = 0.90) -> float:
    """Return the finite-sample order statistic used by the sealed validation."""

    target = float(coverage)
    if not math.isfinite(target) or not 0 < target <= 1:
        raise ValueError("coverage must be in (0, 1]")
    values = sorted(_finite_nonnegative(value, "residual") for value in residuals)
    if not values:
        raise ValueError("at least one calibration residual is required")
    if values[-1] > 1 + TOLERANCE:
        raise ValueError("total-variation residuals cannot exceed one")
    rank = min(len(values), max(1, math.ceil((len(values) + 1) * target)))
    return min(1.0, values[rank - 1])


@dataclass(frozen=True)
class CoordinateInterval:
    destination: str
    historical_share: float
    lower_mass: float
    upper_mass: float
    named_report_status: str


@dataclass(frozen=True)
class CompositionalAllocation:
    status: str
    remainder_mass: float
    epsilon: float
    coordinates: tuple[CoordinateInterval, ...]
    evidence_only_total_width: float
    joint_total_width: float
    width_contraction: float
    operational_point_allocation: None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def contains(self, observed: Mapping[str, float], *, tolerance: float = 1e-8) -> bool:
        """Check whether an observed full composition belongs to the joint set."""

        if self.remainder_mass == 0:
            return all(abs(float(observed.get(item.destination, 0.0))) <= tolerance for item in self.coordinates)
        names = {item.destination for item in self.coordinates}
        if set(observed) - names:
            return False
        values = []
        for item in self.coordinates:
            value = _finite_nonnegative(observed.get(item.destination, 0.0), "observed mass")
            values.append(value)
        if abs(sum(values) - self.remainder_mass) > tolerance:
            return False
        actual_shares = [value / self.remainder_mass for value in values]
        historical = [item.historical_share for item in self.coordinates]
        return total_variation(actual_shares, historical) <= self.epsilon + tolerance


def compositional_allocation(
    *,
    remainder_mass: float,
    destinations: Sequence[str],
    historical_shares: Sequence[float],
    epsilon: float,
    unresolved_destination: str = "UNRESOLVED_DESTINATION",
) -> CompositionalAllocation:
    """Construct sharp coordinate bounds for one total-variation simplex set."""

    remainder = _finite_nonnegative(remainder_mass, "remainder_mass")
    radius = _finite_nonnegative(epsilon, "epsilon")
    if radius > 1 + TOLERANCE:
        raise ValueError("epsilon cannot exceed one")
    radius = min(1.0, radius)
    names = tuple(str(name).strip() for name in destinations)
    if not names or any(not name for name in names):
        raise ValueError("every destination must have a non-empty name")
    if len(set(names)) != len(names):
        raise ValueError("destination names must be unique")
    shares = _normalized_shares(historical_shares)
    if len(names) != len(shares):
        raise ValueError("destinations and historical_shares must have the same length")

    coordinates = tuple(
        CoordinateInterval(
            destination=name,
            historical_share=share,
            lower_mass=(0.0 if remainder == 0 else max(0.0, share - radius) * remainder),
            upper_mass=(0.0 if remainder == 0 else min(1.0, share + radius) * remainder),
            named_report_status=(
                "blocked_unresolved_identity"
                if name == unresolved_destination
                else "eligible_fitted_destination"
            ),
        )
        for name, share in zip(names, shares)
    )
    lower_sum = sum(item.lower_mass for item in coordinates)
    upper_sum = sum(item.upper_mass for item in coordinates)
    if lower_sum > remainder + 1e-8 or upper_sum < remainder - 1e-8:
        raise AssertionError("coordinate bounds do not contain a conserving composition")
    evidence_width = len(coordinates) * remainder
    joint_width = sum(item.upper_mass - item.lower_mass for item in coordinates)
    contraction = 0.0 if evidence_width == 0 else 1.0 - joint_width / evidence_width
    return CompositionalAllocation(
        status="identified_interval_set",
        remainder_mass=remainder,
        epsilon=radius,
        coordinates=coordinates,
        evidence_only_total_width=evidence_width,
        joint_total_width=joint_width,
        width_contraction=contraction,
    )


def run_compositional_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Serializable interface used by the command and HTTP layers."""

    result = compositional_allocation(
        remainder_mass=float(payload["remainder_mass"]),
        destinations=tuple(str(value) for value in payload["destinations"]),
        historical_shares=tuple(float(value) for value in payload["historical_shares"]),
        epsilon=float(payload["epsilon"]),
        unresolved_destination=str(payload.get("unresolved_destination", "UNRESOLVED_DESTINATION")),
    )
    return result.to_dict()
