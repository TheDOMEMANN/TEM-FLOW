"""Typed evidential measure-flow calculus used by the TEM-FLOW engine.

The primitive output is a claim with a dependency witness, not an anonymous
number.  Scalar arithmetic is deliberately small and transparent; admissibility
is decided before a quantity is allowed to participate in a scientific claim.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from calendar import monthrange
import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping


MISSING = {None, ""}


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _finite_nonnegative(value: object, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return number


def _claim_id(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "TEM-CLAIM-" + hashlib.sha256(encoded).hexdigest()[:20].upper()


@dataclass(frozen=True)
class IdentitySignature:
    """Scientific identity carried by a quantity or claim."""

    country: str = ""
    food_domain: str = ""
    commodity: str = ""
    product_form: str = ""
    material: str = ""
    origin: str = ""
    transient: str = ""
    destination: str = ""
    period: str = ""
    denominator: str = ""
    unit: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "IdentitySignature":
        domains = value.get("food_domains") or value.get("food_domain") or ""
        commodities = value.get("commodities") or value.get("commodity") or value.get("commodity_or_species") or ""
        if isinstance(domains, (list, tuple, set)):
            domains = "|".join(sorted(str(item) for item in domains if item))
        if isinstance(commodities, (list, tuple, set)):
            commodities = "|".join(sorted(str(item) for item in commodities if item))
        return cls(
            country=str(value.get("iso3") or value.get("country") or ""),
            food_domain=str(domains),
            commodity=str(commodities),
            product_form=str(value.get("product_form") or value.get("product") or ""),
            material=str(value.get("matrix") or value.get("material") or ""),
            origin=str(value.get("origin") or value.get("source_node") or value.get("from_node_id") or ""),
            transient=str(value.get("transient") or value.get("transient_node") or value.get("data_collection_name") or ""),
            destination=str(value.get("destination") or value.get("destination_node") or value.get("to_node_id") or ""),
            period=str(value.get("period") or value.get("observed_at") or value.get("quantity_period") or ""),
            denominator=str(value.get("denominator") or ""),
            unit=str(value.get("unit") or value.get("mass_unit_period") or ""),
        )

    def compatibility(self, other: "IdentitySignature") -> dict[str, object]:
        fields = (
            "country", "food_domain", "commodity", "product_form", "material",
            "origin", "transient", "destination", "period", "denominator", "unit",
        )
        mismatches: list[str] = []
        unresolved: list[str] = []
        for name in fields:
            left, right = _text(getattr(self, name)), _text(getattr(other, name))
            if left and right and left != right:
                mismatches.append(name)
            elif not left or not right:
                unresolved.append(name)
        status = "incompatible" if mismatches else "indeterminate" if unresolved else "compatible"
        return {"status": status, "mismatches": mismatches, "unresolved": unresolved}


def _temporal_key(value: object, name: str) -> date:
    """Parse an evidence-cutoff key without implying date contemporaneousness."""
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 12, 31)
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, monthrange(year, month)[1])
    if re.fullmatch(r"\d{4}-\d{4}", text):
        return date(int(text[-4:]), 12, 31)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date, year-month, year, or year range") from exc


def _temporal_interval(value: object, name: str) -> tuple[date, date, str]:
    """Parse dated evidence without manufacturing day-level precision.

    A year or year range is retained as an interval.  Nearest-time matching then
    measures the gap between temporal intervals rather than pretending that an
    annual observation occurred on an arbitrary single day.
    """
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        return date(year, 1, 1), date(year, 12, 31), "year"
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1), date(year, month, monthrange(year, month)[1]), "month"
    if re.fullmatch(r"\d{4}-\d{4}", text):
        start_year, end_year = (int(part) for part in text.split("-"))
        if start_year > end_year:
            raise ValueError(f"{name} year range is reversed")
        return date(start_year, 1, 1), date(end_year, 12, 31), "year_range"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date, year-month, year, or year range") from exc
    return parsed, parsed, "day"


def _temporal_distance(target: tuple[date, date, str], candidate: tuple[date, date, str]) -> tuple[int, str]:
    target_start, target_end, _ = target
    candidate_start, candidate_end, _ = candidate
    if candidate_end < target_start:
        return (target_start - candidate_end).days, "before"
    if candidate_start > target_end:
        return (candidate_start - target_end).days, "after"
    return 0, "overlapping_period"


def nearest_compatible_evidence(
    records: Iterable[Mapping[str, object]],
    *,
    target_date: str,
    required_signature: IdentitySignature,
    date_fields: tuple[str, ...] = ("observed_at", "period", "reference_date", "reported_at", "evidence_date"),
    direction_policy: str = "nearest",
    max_gap_days: int | None = None,
    require_certified: bool = False,
) -> dict[str, object]:
    """Select the closest dated identity-compatible evidence record.

    Selection is performed independently for each predictor stream.  The
    default permits the closest record before or after the target date and
    prefers the earlier record only when temporal distances are exactly tied.
    ``past_only`` and ``future_only`` are available for sensitivity analysis.
    """
    policy = _text(direction_policy).replace(" ", "_")
    if policy not in {"nearest", "past_only", "future_only"}:
        raise ValueError("direction_policy must be nearest, past_only, or future_only")
    if max_gap_days is not None and max_gap_days < 0:
        raise ValueError("max_gap_days must be non-negative")
    target_interval = _temporal_interval(target_date, "target_date")
    scope_fields = (
        "country", "food_domain", "commodity", "product_form", "material",
        "origin", "transient", "destination", "denominator", "unit",
    )
    eligible: list[tuple[tuple[float, ...], dict[str, object], str, tuple[date, date, str], int, str]] = []
    target_midpoint = (target_interval[0].toordinal() + target_interval[1].toordinal()) / 2.0
    for index, raw_record in enumerate(records):
        record = dict(raw_record)
        if require_certified and _text(record.get("status") or record.get("certificate_status")) not in {"certified", "approved"}:
            continue
        raw_signature = record.get("signature")
        signature = IdentitySignature.from_mapping(raw_signature if isinstance(raw_signature, Mapping) else record)
        if any(
            _text(getattr(required_signature, field_name))
            and _text(getattr(signature, field_name)) != _text(getattr(required_signature, field_name))
            for field_name in scope_fields
        ):
            continue
        raw_date = next((record.get(field_name) for field_name in date_fields if record.get(field_name) not in MISSING), None)
        if raw_date in MISSING:
            continue
        candidate_interval = _temporal_interval(raw_date, "evidence date")
        gap_days, direction = _temporal_distance(target_interval, candidate_interval)
        if policy == "past_only" and direction == "after":
            continue
        if policy == "future_only" and direction == "before":
            continue
        if max_gap_days is not None and gap_days > max_gap_days:
            continue
        candidate_midpoint = (candidate_interval[0].toordinal() + candidate_interval[1].toordinal()) / 2.0
        future_tie_penalty = 1.0 if direction == "after" else 0.0
        rank = (
            float(gap_days),
            abs(candidate_midpoint - target_midpoint),
            future_tie_penalty,
            float(candidate_interval[0].toordinal()),
            float(-index),
        )
        eligible.append((rank, record, str(raw_date), candidate_interval, gap_days, direction))
    if not eligible:
        gap_boundary = f" within {max_gap_days} days" if max_gap_days is not None else ""
        raise ValueError(f"no certified identity-compatible evidence record is available{gap_boundary} of target date {target_date}")
    _, selected, selected_label, selected_interval, gap_days, direction = min(eligible, key=lambda item: item[0])
    return {
        "record": selected,
        "target_date": str(target_date),
        "selected_evidence_date": selected_label,
        "selected_interval_start": selected_interval[0].isoformat(),
        "selected_interval_end": selected_interval[1].isoformat(),
        "date_precision": selected_interval[2],
        "temporal_gap_days": gap_days,
        "temporal_direction": direction,
        "direction_policy": policy,
        "max_gap_days": max_gap_days,
        "selection_rule": "nearest certified identity-compatible record in this predictor stream; earlier record wins an exact tie",
        "contemporaneousness_required": False,
    }


def latest_eligible_evidence(
    records: Iterable[Mapping[str, object]],
    *,
    evidence_cutoff: str,
    required_signature: IdentitySignature,
    date_fields: tuple[str, ...] = ("evidence_date", "observed_at", "reported_at", "period"),
) -> dict[str, object]:
    """Select the latest compatible record available by an evidence cutoff.

    The record period is deliberately excluded from the scope match.  CPC,
    mass, population and chemistry streams are selected independently, so their
    evidence dates may differ.  ``evidence_cutoff`` controls availability; it
    is not a requirement that the selected record date equal the flow-analysis
    date.
    """
    cutoff = _temporal_key(evidence_cutoff, "evidence_cutoff")
    scope_fields = (
        "country", "food_domain", "commodity", "product_form", "material",
        "origin", "transient", "destination", "denominator", "unit",
    )
    eligible: list[tuple[date, int, dict[str, object]]] = []
    for index, raw_record in enumerate(records):
        record = dict(raw_record)
        raw_signature = record.get("signature")
        signature = IdentitySignature.from_mapping(raw_signature if isinstance(raw_signature, Mapping) else record)
        if any(
            _text(getattr(required_signature, field_name))
            and _text(getattr(signature, field_name)) != _text(getattr(required_signature, field_name))
            for field_name in scope_fields
        ):
            continue
        evidence_date_value = next((record.get(field_name) for field_name in date_fields if record.get(field_name) not in MISSING), None)
        if evidence_date_value in MISSING:
            continue
        evidence_date = _temporal_key(evidence_date_value, "evidence date")
        if evidence_date <= cutoff:
            eligible.append((evidence_date, index, record))
    if not eligible:
        raise ValueError("no identity-compatible evidence record is available by the requested evidence cutoff")
    selected_date, _, selected = max(eligible, key=lambda item: (item[0], item[1]))
    return {
        "record": selected,
        "selected_evidence_date": selected_date.isoformat(),
        "evidence_cutoff": cutoff.isoformat(),
        "selection_rule": "latest identity-compatible record available by the evidence cutoff",
        "contemporaneousness_required": False,
    }


@dataclass(frozen=True)
class EvidentialMeasure:
    """A finite non-negative measure over scientific identity labels."""

    atoms: Mapping[IdentitySignature, float] = field(default_factory=dict)
    evidence_ids: Mapping[IdentitySignature, tuple[str, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for signature, amount in self.atoms.items():
            if not isinstance(signature, IdentitySignature):
                raise TypeError("measure labels must be IdentitySignature values")
            _finite_nonnegative(amount, "measure atom")

    @property
    def total(self) -> float:
        return float(sum(self.atoms.values()))

    def add(self, other: "EvidentialMeasure") -> "EvidentialMeasure":
        amounts = dict(self.atoms)
        witnesses = {key: tuple(value) for key, value in self.evidence_ids.items()}
        for signature, amount in other.atoms.items():
            amounts[signature] = amounts.get(signature, 0.0) + float(amount)
            witnesses[signature] = tuple(dict.fromkeys((*witnesses.get(signature, ()), *other.evidence_ids.get(signature, ()))))
        return EvidentialMeasure(amounts, witnesses)


@dataclass(frozen=True)
class TransformationCertificate:
    certificate_id: str
    input_signature: IdentitySignature
    output_signature: IdentitySignature
    yield_lower: float
    yield_upper: float
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        lower = _finite_nonnegative(self.yield_lower, "yield_lower")
        upper = _finite_nonnegative(self.yield_upper, "yield_upper")
        if lower > upper:
            raise ValueError("yield_lower cannot exceed yield_upper")
        if not self.certificate_id or not self.evidence_ids:
            raise ValueError("a transformation certificate needs an id and evidence")


@dataclass(frozen=True)
class RouteCertificate:
    """Evidence-bearing authorization for one exact route identity."""

    certificate_id: str
    signature: IdentitySignature
    evidence_ids: tuple[str, ...]
    boundary: str

    def __post_init__(self) -> None:
        if not self.certificate_id or not self.evidence_ids or not self.boundary:
            raise ValueError("a route certificate needs an id, evidence and claim boundary")


@dataclass(frozen=True)
class PathCertificate:
    """Evidence-bearing authorization for one exact source-transient-destination path."""

    certificate_id: str
    signature: IdentitySignature
    evidence_ids: tuple[str, ...]
    boundary: str

    def __post_init__(self) -> None:
        if not self.signature.origin or not self.signature.transient or not self.signature.destination:
            raise ValueError("a path certificate requires source, transient and destination identities")
        if not self.certificate_id or not self.evidence_ids or not self.boundary:
            raise ValueError("a path certificate needs an id, evidence and claim boundary")


@dataclass(frozen=True)
class CPCAllocationCertificate:
    """Authorize one mass/population join and edible-yield conversion into CPC."""

    certificate_id: str
    mass_signature: IdentitySignature
    population_signature: IdentitySignature
    output_signature: IdentitySignature
    edible_yield_lower: float
    edible_yield_upper: float
    evidence_ids: tuple[str, ...]
    boundary: str

    def __post_init__(self) -> None:
        lower = _finite_nonnegative(self.edible_yield_lower, "edible_yield_lower")
        upper = _finite_nonnegative(self.edible_yield_upper, "edible_yield_upper")
        if lower > upper or upper > 1:
            raise ValueError("edible-yield bounds must satisfy 0 <= lower <= upper <= 1")
        if not self.certificate_id or not self.evidence_ids or not self.boundary:
            raise ValueError("a CPC allocation certificate needs an id, evidence and claim boundary")


@dataclass(frozen=True)
class PopulationProjectionCertificate:
    """Bind a population claim to one current named projection scenario and node."""

    certificate_id: str
    signature: IdentitySignature
    projection_scenario: str
    geographic_level: str
    projection_as_of: str
    evidence_ids: tuple[str, ...]
    boundary: str

    def __post_init__(self) -> None:
        allowed_levels = {"country", "city", "town", "village"}
        if self.geographic_level.casefold() not in allowed_levels:
            raise ValueError(f"population geographic_level must be one of {sorted(allowed_levels)}")
        if not self.signature.destination:
            raise ValueError("a population projection certificate requires an exact destination node")
        if not self.projection_scenario or not self.projection_as_of:
            raise ValueError("a population projection certificate requires scenario and as-of labels")
        if not self.certificate_id or not self.evidence_ids or not self.boundary:
            raise ValueError("a population projection certificate needs an id, evidence and claim boundary")


@dataclass(frozen=True)
class DirectCPCCertificate:
    """Authorize one explicitly reported/calculated CPC for an exact node identity."""

    certificate_id: str
    signature: IdentitySignature
    evidence_ids: tuple[str, ...]
    boundary: str

    def __post_init__(self) -> None:
        if not self.signature.destination or not self.signature.period or not self.signature.denominator or not self.signature.unit:
            raise ValueError("a direct CPC certificate requires node, period, denominator and unit")
        if not self.certificate_id or not self.evidence_ids or not self.boundary:
            raise ValueError("a direct CPC certificate needs an id, evidence and claim boundary")


@dataclass(frozen=True)
class ExposureCertificate:
    """Authorize an exact CPC-chemistry-body-weight-reference-dose join."""

    certificate_id: str
    cpc_signature: IdentitySignature
    concentration_signature: IdentitySignature
    body_weight_signature: IdentitySignature
    reference_dose_signature: IdentitySignature
    intake_signature: IdentitySignature
    hazard_signature: IdentitySignature
    days_per_period: float
    evidence_ids: tuple[str, ...]
    boundary: str

    def __post_init__(self) -> None:
        days = _finite_nonnegative(self.days_per_period, "days_per_period")
        if days <= 0:
            raise ValueError("days_per_period must be positive")
        if not self.certificate_id or not self.evidence_ids or not self.boundary:
            raise ValueError("an exposure certificate needs an id, evidence and claim boundary")


@dataclass(frozen=True)
class IntervalMeasureClaim:
    """A proof-carrying interval over one fully typed identity."""

    signature: IdentitySignature
    lower: float
    upper: float
    evidence_ids: tuple[str, ...]
    certificate_ids: tuple[str, ...] = ()
    expression: str = "observed interval"

    def __post_init__(self) -> None:
        lower = _finite_nonnegative(self.lower, "claim lower")
        upper = _finite_nonnegative(self.upper, "claim upper")
        if lower > upper:
            raise ValueError("claim lower cannot exceed claim upper")
        if not self.evidence_ids:
            raise ValueError("a measure claim needs evidence")

    @property
    def claim_id(self) -> str:
        return _claim_id(asdict(self))

    def apply(self, certificate: TransformationCertificate) -> "IntervalMeasureClaim":
        compatibility = self.signature.compatibility(certificate.input_signature)
        if compatibility["status"] == "incompatible":
            raise ValueError(f"certificate input identity mismatch: {compatibility['mismatches']}")
        return IntervalMeasureClaim(
            signature=certificate.output_signature,
            lower=self.lower * certificate.yield_lower,
            upper=self.upper * certificate.yield_upper,
            evidence_ids=tuple(dict.fromkeys((*self.evidence_ids, *certificate.evidence_ids))),
            certificate_ids=tuple(dict.fromkeys((*self.certificate_ids, certificate.certificate_id))),
            expression=f"pushforward({self.claim_id}, {certificate.certificate_id})",
        )


@dataclass(frozen=True)
class TransformationChain:
    """A composable chain of primitive, evidence-bearing certificates.

    Exact endpoint equality is required between adjacent certificates.  This
    stronger rule is used by the formal safety theorems; the more permissive
    single-certificate ``apply`` method remains available for explicitly
    incomplete legacy identities.
    """

    certificates: tuple[TransformationCertificate, ...]

    def __post_init__(self) -> None:
        if not self.certificates:
            raise ValueError("a transformation chain cannot be empty")
        for left, right in zip(self.certificates, self.certificates[1:]):
            if left.output_signature != right.input_signature:
                raise ValueError("adjacent certificate identities do not match exactly")

    @property
    def input_signature(self) -> IdentitySignature:
        return self.certificates[0].input_signature

    @property
    def output_signature(self) -> IdentitySignature:
        return self.certificates[-1].output_signature

    @property
    def yield_interval(self) -> tuple[float, float]:
        return (
            math.prod(certificate.yield_lower for certificate in self.certificates),
            math.prod(certificate.yield_upper for certificate in self.certificates),
        )

    def compose(self, other: "TransformationChain") -> "TransformationChain":
        if self.output_signature != other.input_signature:
            raise ValueError("certificate chains are not composable")
        return TransformationChain(self.certificates + other.certificates)

    def apply(self, claim: IntervalMeasureClaim) -> IntervalMeasureClaim:
        if claim.signature != self.input_signature:
            raise ValueError("claim identity does not equal the chain input identity")
        output = claim
        for certificate in self.certificates:
            output = output.apply(certificate)
        return output


def scalar_projection(claim: IntervalMeasureClaim) -> tuple[float, float]:
    """Forget identity and provenance while retaining the numerical interval."""
    return claim.lower, claim.upper


def certified_marginal_flow_claim(
    *,
    row_total: float,
    column_total: float,
    network_total: float,
    signature: IdentitySignature,
    evidence_ids: tuple[str, ...],
    route_certificate: RouteCertificate | None,
) -> IntervalMeasureClaim:
    """Return the sharp non-negative cell bounds implied by two margins.

    The certificate list controls whether the cell is an admissible scientific
    claim.  The bounds themselves are the closed-form two-margin projection;
    no point allocation is manufactured.
    """
    row = _finite_nonnegative(row_total, "row_total")
    column = _finite_nonnegative(column_total, "column_total")
    total = _finite_nonnegative(network_total, "network_total")
    if row > total or column > total:
        raise ValueError("a row or column margin cannot exceed the network total")
    if route_certificate is None:
        raise ValueError("a marginal flow claim requires a route certificate")
    if route_certificate.signature != signature:
        comparison = signature.compatibility(route_certificate.signature)
        differences = comparison["mismatches"] or comparison["unresolved"]
        raise ValueError(f"route certificate identity mismatch: {differences}")
    return IntervalMeasureClaim(
        signature=signature,
        lower=max(0.0, row + column - total),
        upper=min(row, column),
        evidence_ids=tuple(dict.fromkeys((*evidence_ids, *route_certificate.evidence_ids))),
        certificate_ids=(route_certificate.certificate_id,),
        expression="certificate-gated two-margin closure",
    )


def certified_path_flow_claim(
    *,
    source_total: float,
    transient_total: float,
    destination_total: float,
    network_total: float,
    signature: IdentitySignature,
    evidence_ids: tuple[str, ...],
    path_certificate: PathCertificate | None,
) -> IntervalMeasureClaim:
    """Return sharp bounds for one source-transient-destination tensor cell.

    Only the three one-dimensional margins and non-negativity are assumed.  A
    matching path certificate controls scientific admissibility; it does not
    assert that the held-out or future path mass is positive.
    """
    source = _finite_nonnegative(source_total, "source_total")
    transient = _finite_nonnegative(transient_total, "transient_total")
    destination = _finite_nonnegative(destination_total, "destination_total")
    total = _finite_nonnegative(network_total, "network_total")
    if source > total or transient > total or destination > total:
        raise ValueError("a source, transient or destination margin cannot exceed the network total")
    if path_certificate is None:
        raise ValueError("a path flow claim requires a path certificate")
    if path_certificate.signature != signature:
        comparison = signature.compatibility(path_certificate.signature)
        differences = comparison["mismatches"] or comparison["unresolved"]
        raise ValueError(f"path certificate identity mismatch: {differences}")
    return IntervalMeasureClaim(
        signature=signature,
        lower=max(0.0, source + transient + destination - 2.0 * total),
        upper=min(source, transient, destination),
        evidence_ids=tuple(dict.fromkeys((*evidence_ids, *path_certificate.evidence_ids))),
        certificate_ids=(path_certificate.certificate_id,),
        expression="certificate-gated three-margin path closure",
    )


def derive_node_cpc_claim(
    *,
    allocated_mass: IntervalMeasureClaim,
    consumer_population: IntervalMeasureClaim,
    population_certificate: PopulationProjectionCertificate | None,
    certificate: CPCAllocationCertificate | None,
) -> IntervalMeasureClaim:
    """Propagate a certified node allocation into edible CPC.

    The population interval is used as a divisor, so a strictly positive lower
    endpoint is required. The mass-observation period, projection vintage and
    projection target period may differ; each is retained in its own typed
    signature and certificate. The result remains an interval and retains every
    mass, population, and certificate dependency.
    """
    if certificate is None:
        raise ValueError("a node CPC claim requires a CPC allocation certificate")
    if population_certificate is None:
        raise ValueError("derived node CPC requires a population projection certificate")
    mismatches: list[str] = []
    if allocated_mass.signature != certificate.mass_signature:
        mismatches.append("mass_signature")
    if consumer_population.signature != certificate.population_signature:
        mismatches.append("population_signature")
    if consumer_population.signature != population_certificate.signature:
        mismatches.append("population_projection_signature")
    if mismatches:
        raise ValueError(f"CPC allocation certificate identity mismatch: {mismatches}")
    if consumer_population.lower <= 0:
        raise ValueError("consumer population lower bound must be positive")
    return IntervalMeasureClaim(
        signature=certificate.output_signature,
        lower=allocated_mass.lower * certificate.edible_yield_lower / consumer_population.upper,
        upper=allocated_mass.upper * certificate.edible_yield_upper / consumer_population.lower,
        evidence_ids=tuple(dict.fromkeys((*allocated_mass.evidence_ids, *consumer_population.evidence_ids, *population_certificate.evidence_ids, *certificate.evidence_ids))),
        certificate_ids=tuple(dict.fromkeys((*allocated_mass.certificate_ids, *consumer_population.certificate_ids, population_certificate.certificate_id, certificate.certificate_id))),
        expression=f"certified edible node CPC({allocated_mass.claim_id}, {consumer_population.claim_id})",
    )


def resolve_node_cpc_claim(
    *,
    explicit_cpc: IntervalMeasureClaim | None = None,
    direct_cpc_certificate: DirectCPCCertificate | None = None,
    allocated_mass: IntervalMeasureClaim | None = None,
    consumer_population: IntervalMeasureClaim | None = None,
    population_certificate: PopulationProjectionCertificate | None = None,
    allocation_certificate: CPCAllocationCertificate | None = None,
) -> IntervalMeasureClaim:
    """Use exact reported node CPC when certified; otherwise derive from mass/population.

    Explicit CPC has precedence only when it is node-, product-, period-,
    denominator-, and unit-specific.  Otherwise the population must be drawn
    from a named current projection scenario for the exact destination node.
    """
    if explicit_cpc is not None:
        if direct_cpc_certificate is None:
            raise ValueError("explicit node CPC requires a direct CPC certificate")
        if explicit_cpc.signature != direct_cpc_certificate.signature:
            comparison = explicit_cpc.signature.compatibility(direct_cpc_certificate.signature)
            differences = comparison["mismatches"] or comparison["unresolved"]
            raise ValueError(f"direct CPC certificate identity mismatch: {differences}")
        return IntervalMeasureClaim(
            signature=explicit_cpc.signature,
            lower=explicit_cpc.lower,
            upper=explicit_cpc.upper,
            evidence_ids=tuple(dict.fromkeys((*explicit_cpc.evidence_ids, *direct_cpc_certificate.evidence_ids))),
            certificate_ids=tuple(dict.fromkeys((*explicit_cpc.certificate_ids, direct_cpc_certificate.certificate_id))),
            expression=f"certified explicit node CPC({explicit_cpc.claim_id})",
        )
    if allocated_mass is None or consumer_population is None:
        raise ValueError("derived node CPC requires allocated mass and projected population")
    return derive_node_cpc_claim(
        allocated_mass=allocated_mass,
        consumer_population=consumer_population,
        population_certificate=population_certificate,
        certificate=allocation_certificate,
    )


def propagate_contaminant_exposure(
    *,
    cpc: IntervalMeasureClaim,
    concentration: IntervalMeasureClaim,
    body_weight: IntervalMeasureClaim,
    reference_dose: IntervalMeasureClaim,
    certificate: ExposureCertificate | None,
) -> dict[str, IntervalMeasureClaim]:
    """Propagate compatible CPC and chemistry to EDI and hazard quotient.

    For non-negative intervals, endpoint propagation is monotone.  Concentration
    is multiplied by CPC, then divided by days and body weight; HQ additionally
    divides by the reference dose.  Exact typed equality is required for every
    input. CPC and chemistry periods are not required to be equal: each stream
    may use its latest eligible compatible record, with its own date retained
    in the certificate. Chemistry still cannot leak across commodity, tissue,
    node, analyte scope, or an uncertified temporal selection.
    """
    if certificate is None:
        raise ValueError("contaminant exposure requires an exposure certificate")
    inputs = {
        "cpc_signature": (cpc.signature, certificate.cpc_signature),
        "concentration_signature": (concentration.signature, certificate.concentration_signature),
        "body_weight_signature": (body_weight.signature, certificate.body_weight_signature),
        "reference_dose_signature": (reference_dose.signature, certificate.reference_dose_signature),
    }
    mismatches = [name for name, (actual, expected) in inputs.items() if actual != expected]
    if mismatches:
        raise ValueError(f"exposure certificate identity mismatch: {mismatches}")
    if body_weight.lower <= 0 or reference_dose.lower <= 0:
        raise ValueError("body-weight and reference-dose lower bounds must be positive")
    evidence_ids = tuple(dict.fromkeys((
        *cpc.evidence_ids,
        *concentration.evidence_ids,
        *body_weight.evidence_ids,
        *reference_dose.evidence_ids,
        *certificate.evidence_ids,
    )))
    certificate_ids = tuple(dict.fromkeys((
        *cpc.certificate_ids,
        *concentration.certificate_ids,
        *body_weight.certificate_ids,
        *reference_dose.certificate_ids,
        certificate.certificate_id,
    )))
    days = certificate.days_per_period
    intake = IntervalMeasureClaim(
        signature=certificate.intake_signature,
        lower=cpc.lower * concentration.lower / (days * body_weight.upper),
        upper=cpc.upper * concentration.upper / (days * body_weight.lower),
        evidence_ids=evidence_ids,
        certificate_ids=certificate_ids,
        expression=f"certified EDI({cpc.claim_id}, {concentration.claim_id})",
    )
    hazard = IntervalMeasureClaim(
        signature=certificate.hazard_signature,
        lower=intake.lower / reference_dose.upper,
        upper=intake.upper / reference_dose.lower,
        evidence_ids=evidence_ids,
        certificate_ids=certificate_ids,
        expression=f"certified HQ({intake.claim_id}, {reference_dose.claim_id})",
    )
    return {"estimated_daily_intake": intake, "hazard_quotient": hazard}


def multiply_claims(left: IntervalMeasureClaim, right: IntervalMeasureClaim, *, output_signature: IdentitySignature, expression: str) -> IntervalMeasureClaim:
    """Monotone interval product with dependency union.

    The caller supplies the output identity explicitly, making a hidden unit or
    denominator conversion impossible.
    """
    return IntervalMeasureClaim(
        signature=output_signature,
        lower=left.lower * right.lower,
        upper=left.upper * right.upper,
        evidence_ids=tuple(dict.fromkeys((*left.evidence_ids, *right.evidence_ids))),
        certificate_ids=tuple(dict.fromkeys((*left.certificate_ids, *right.certificate_ids))),
        expression=expression,
    )


def ziway_addis_mass_claim() -> IntervalMeasureClaim:
    """Reproduce the documented Ziway-to-Addis mass interval without allocation."""
    production = IntervalMeasureClaim(
        IdentitySignature(country="ETH", food_domain="fish", commodity="fish", product_form="whole fishery as reported", origin="Lake Ziway", period="2018", unit="t/year"),
        488.9,
        488.9,
        ("ZIWAY_PRODUCTION_2018_MARKET_STUDY",),
    )
    share = IntervalMeasureClaim(
        IdentitySignature(country="ETH", food_domain="fish", commodity="fish", product_form="gutted, filleted and whole fish", origin="Lake Ziway", destination="Addis Ababa", period="2018", denominator="total source production", unit="share"),
        0.4067293925,
        0.4147064839,
        ("ZIWAY_ADDIS_TOTAL_SHARE_2018",),
        ("TEM-CERT-ZIWAY-ADDIS-DENOMINATOR-2018",),
        "reported channel share × documented marketed/production coverage",
    )
    return multiply_claims(
        production,
        share,
        output_signature=IdentitySignature(country="ETH", food_domain="fish", commodity="fish", product_form="gutted, filleted and whole fish", origin="Lake Ziway", destination="Addis Ababa", period="2018", unit="t/year"),
        expression="488.9 t/year × denominator-corrected Addis share interval",
    )


def classify_atlas_record(record: Mapping[str, object]) -> dict[str, str]:
    """Conservatively classify a frozen continental atlas row."""
    decision = _text(record.get("decision_status"))
    boundary = _text(record.get("claim_boundary"))
    chemistry = _text(record.get("chemistry_or_contaminants"))
    pipeline_terms = (
        "ed-flow", "fixed-rule", "recompute", "national-comparator", "validation case",
        "aggregation failure", "scenario alarm", "source_scenario_validation",
    )
    if any(term in f"{decision} {boundary}" for term in pipeline_terms):
        epistemic_origin = "pipeline_adjudication_summary"
        derived_by = "ED-FLOW evidence-adjudication pipeline or retained audit"
    elif re.search(r"\b(hq|hi|thq|edi|ewi|cr|risk|alarm)\b", f"{decision} {chemistry}"):
        epistemic_origin = "source_reported_result_summary"
        derived_by = "source publication; raw observations absent from this ledger row"
    else:
        epistemic_origin = "source_context_summary"
        derived_by = "source publication or inherited audit"
    route_text = _text(record.get("route_as_reported"))
    evidence_role = "topology_context" if route_text else "provenance_context"
    if "pending" in decision or "unresolved" in boundary or "gate" in boundary:
        evidence_role = "blocked_pending_resolution"
    return {
        "epistemic_origin": epistemic_origin,
        "measurement_status": "not_a_direct_machine_readable_measurement",
        "numeric_status": "no_numeric_value_column_in_frozen_atlas_ledger",
        "derived_by": derived_by,
        "evidence_role": evidence_role,
        "compatibility_state": "requires_typed_join",
        "transformation_required": "yes_if_identity_or_material_changes",
    }


def classify_temporal_record(record: Mapping[str, object]) -> dict[str, str]:
    """Classify a numeric/structural record embedded in the ED-FLOW dashboard."""
    record_id = str(record.get("record_id") or "")
    evidence_type = _text(record.get("evidence_type"))
    model_use = _text((record.get("metadata") or {}).get("model_use") if isinstance(record.get("metadata"), Mapping) else "")
    value_present = record.get("value") not in MISSING
    if record_id == "ZIWAY_ADDIS_TOTAL_SHARE_2018":
        origin = "pipeline_derived_interval_summary"
        status = "derived_from_reported_channel_share_and_mass_denominators"
        role = "quantitative_constraint"
    elif evidence_type == "contaminant" and value_present:
        origin = "reported_laboratory_measurement"
        status = "numeric_measurement_with_provisional_record_date"
        role = "dose_candidate"
    elif evidence_type == "production" and "prior" in model_use:
        origin = "reported_or_secondary_prior"
        status = "numeric_context_not_a_hard_measurement"
        role = "prior_context"
    elif evidence_type == "production" and "observation" in model_use:
        origin = "reported_source_mass_measurement"
        status = "numeric_reported_measurement"
        role = "quantitative_constraint"
    elif evidence_type == "share" and value_present:
        origin = "reported_channel_statistic"
        status = "numeric_reported_statistic"
        role = "quantitative_constraint"
    elif evidence_type == "consumption" and value_present:
        origin = "reported_consumption_statistic"
        status = "numeric_reported_statistic_not_raw_microdata"
        role = "context_or_constraint_if_identity_matches"
    elif evidence_type == "route":
        origin = "reported_structural_observation"
        status = "topology_observation_without_quantity"
        role = "topology_context"
    else:
        origin = "unresolved_reported_record"
        status = "requires_manual_adjudication"
        role = "blocked_pending_resolution"
    return {
        "epistemic_origin": origin,
        "measurement_status": status,
        "numeric_status": "machine_readable_numeric_value" if value_present else "no_numeric_value",
        "derived_by": "ED-FLOW pipeline" if origin.startswith("pipeline_") else "source record",
        "evidence_role": role,
        "compatibility_state": "identity_check_required",
        "transformation_required": "yes_if_identity_or_material_changes",
    }


def _compare_intervals(identified: tuple[float, float], measured: tuple[float, float]) -> dict[str, object]:
    lower, upper = identified
    measured_lower, measured_upper = measured
    if measured_lower > upper:
        status, gap = "upper_envelope_miss", measured_lower - upper
        overlap_lower = overlap_upper = None
        matched_lower, matched_upper = lower, upper
        unmatched_lower = max(0.0, measured_lower - upper)
        unmatched_upper = max(0.0, measured_upper - lower)
        rule = "The identified identity-compatible interval is retained; excess CPC remains an unmatched state."
    elif measured_upper < lower:
        status, gap = "lower_envelope_miss", lower - measured_upper
        overlap_lower = overlap_upper = matched_lower = matched_upper = None
        unmatched_lower = unmatched_upper = 0.0
        rule = "A lower-envelope miss cannot be repaired by inventing an influx or identity transformation."
    else:
        status, gap = "covered", 0.0
        overlap_lower, overlap_upper = max(lower, measured_lower), min(upper, measured_upper)
        matched_lower, matched_upper = overlap_lower, overlap_upper
        unmatched_lower = unmatched_upper = 0.0
        rule = "The measured and identified intervals overlap within the same certified identity."
    return {
        "identified_lower": lower,
        "identified_upper": upper,
        "measured_lower": measured_lower,
        "measured_upper": measured_upper,
        "status": status,
        "gap": gap,
        "overlap_lower": overlap_lower,
        "overlap_upper": overlap_upper,
        "matched_cpc_lower": matched_lower,
        "matched_cpc_upper": matched_upper,
        "unmatched_cpc_lower": unmatched_lower,
        "unmatched_cpc_upper": unmatched_upper,
        "chemistry_rule": rule,
    }


def _chemistry_certificate(payload: Mapping[str, object], trace_records: Iterable[Mapping[str, object]]) -> dict[str, object]:
    certificates = payload.get("certificates")
    certificate = certificates.get("chemistry") if isinstance(certificates, Mapping) else None
    records = list(trace_records)
    trace_ids = {str(record.get("evidence_id") or record.get("record_id") or "") for record in records}
    if isinstance(certificate, Mapping) and _text(certificate.get("status")) == "certified":
        evidence_id = str(certificate.get("evidence_id") or "")
        if evidence_id and (evidence_id in trace_ids or bool(certificate.get("external_evidence_uri"))):
            return {"certified": True, "certificate": dict(certificate), "reason": "explicit chemistry identity certificate accepted"}
    numeric_trace = [record for record in records if record.get("value") not in MISSING and record.get("unit") not in MISSING]
    if numeric_trace:
        return {"certified": True, "certificate": {"mode": "numeric_typed_trace", "evidence_ids": [record.get("evidence_id") for record in numeric_trace]}, "reason": "numeric typed chemistry record is explicitly linked"}
    return {
        "certified": False,
        "certificate": None,
        "reason": "no numeric, identity-compatible chemistry record or explicit transformation certificate is linked",
    }


def _record_evidence_ids(record: Mapping[str, object]) -> tuple[str, ...]:
    raw = record.get("evidence_ids")
    if isinstance(raw, (list, tuple, set)):
        identifiers = [str(item) for item in raw if str(item)]
    elif raw not in MISSING:
        identifiers = [str(raw)]
    else:
        identifiers = []
    single = str(record.get("evidence_id") or record.get("record_id") or "")
    if single:
        identifiers.append(single)
    return tuple(dict.fromkeys(identifiers))


def _record_interval(
    record: Mapping[str, object],
    *,
    lower_fields: tuple[str, ...],
    upper_fields: tuple[str, ...],
    name: str,
    positive: bool = False,
) -> tuple[float, float]:
    lower_raw = next((record.get(field_name) for field_name in lower_fields if record.get(field_name) not in MISSING), None)
    if lower_raw in MISSING:
        raise ValueError(f"{name} record has no numeric lower/value field")
    upper_raw = next((record.get(field_name) for field_name in upper_fields if record.get(field_name) not in MISSING), lower_raw)
    lower = _finite_nonnegative(lower_raw, f"{name} lower")
    upper = _finite_nonnegative(upper_raw, f"{name} upper")
    if lower > upper:
        raise ValueError(f"{name} interval endpoints are inconsistent")
    if positive and lower <= 0:
        raise ValueError(f"{name} lower bound must be positive")
    return lower, upper


def _trend_signature(config: Mapping[str, object], stream_name: str) -> IdentitySignature:
    raw_signatures = config.get("required_signatures")
    stream_signature = raw_signatures.get(stream_name) if isinstance(raw_signatures, Mapping) else None
    if isinstance(stream_signature, Mapping):
        return IdentitySignature.from_mapping(stream_signature)
    raw_common = config.get("required_signature")
    common = IdentitySignature.from_mapping(raw_common) if isinstance(raw_common, Mapping) else IdentitySignature()
    return IdentitySignature(
        country=common.country,
        food_domain=common.food_domain,
        commodity=common.commodity,
        product_form=common.product_form,
        origin=common.origin,
        transient=common.transient,
        destination=common.destination,
    )


def run_temporal_trend(payload: Mapping[str, object]) -> dict[str, object]:
    """Build a historical node/product, CPC, EDI and THQ series.

    Target dates are supplied explicitly or inherited from a manager-selected
    anchor stream (normally node mass).  At every target date, each predictor is
    matched independently to its nearest certified compatible observation.  No
    equality of dates is imposed, and every selected date, direction and gap is
    carried into the point certificate.
    """
    raw_config = payload.get("temporal_trend") or payload.get("trend")
    config = dict(raw_config) if isinstance(raw_config, Mapping) else dict(payload)
    raw_streams = config.get("streams")
    if not isinstance(raw_streams, Mapping):
        raise ValueError("temporal trend requires a streams object")
    streams: dict[str, list[Mapping[str, object]]] = {}
    for stream_name, records in raw_streams.items():
        if isinstance(records, (list, tuple)):
            streams[str(stream_name)] = [record for record in records if isinstance(record, Mapping)]
    if not any(streams.values()):
        raise ValueError("temporal trend requires at least one dated evidence record")

    raw_date_fields = config.get("date_fields")
    date_fields = tuple(str(item) for item in raw_date_fields) if isinstance(raw_date_fields, (list, tuple)) else (
        "observed_at", "period", "reference_date", "reported_at", "evidence_date",
    )
    raw_targets = config.get("target_dates")
    if isinstance(raw_targets, (list, tuple)) and raw_targets:
        target_dates = [str(item) for item in raw_targets if str(item)]
        anchor_stream = str(config.get("anchor_stream") or "manager_supplied_dates")
    else:
        preferred_anchor = str(config.get("anchor_stream") or "mass")
        if not streams.get(preferred_anchor):
            preferred_anchor = next((name for name in ("direct_cpc", "chemistry", "population") if streams.get(name)), "")
        if not preferred_anchor:
            preferred_anchor = next(name for name, records in streams.items() if records)
        anchor_stream = preferred_anchor
        target_dates = []
        for record in streams[anchor_stream]:
            raw_date = next((record.get(field_name) for field_name in date_fields if record.get(field_name) not in MISSING), None)
            if raw_date not in MISSING:
                target_dates.append(str(raw_date))
    target_dates = list(dict.fromkeys(target_dates))
    if not target_dates:
        raise ValueError("the selected temporal anchor has no parseable dates")
    target_dates.sort(key=lambda value: (_temporal_interval(value, "target date")[0], _temporal_interval(value, "target date")[1]))

    direction_policy = str(config.get("direction_policy") or "nearest")
    raw_max_gap = config.get("max_gap_days")
    max_gap_days = None if raw_max_gap in MISSING else int(raw_max_gap)
    days_per_period = _finite_nonnegative(config.get("days_per_period", 365), "days_per_period")
    if days_per_period <= 0:
        raise ValueError("days_per_period must be positive")
    known_streams = ("mass", "direct_cpc", "population", "chemistry", "body_weight", "reference_dose")
    points: list[dict[str, object]] = []

    for target_date in target_dates:
        matches: dict[str, dict[str, object]] = {}
        unavailable: dict[str, str] = {}
        for stream_name in known_streams:
            records = streams.get(stream_name, [])
            if not records:
                continue
            try:
                matches[stream_name] = nearest_compatible_evidence(
                    records,
                    target_date=target_date,
                    required_signature=_trend_signature(config, stream_name),
                    date_fields=date_fields,
                    direction_policy=direction_policy,
                    max_gap_days=max_gap_days,
                    require_certified=True,
                )
            except ValueError as exc:
                unavailable[stream_name] = str(exc)

        temporal_matches: dict[str, dict[str, object]] = {}
        for stream_name, match in matches.items():
            record = match["record"]
            evidence = _record_evidence_ids(record)  # type: ignore[arg-type]
            if not evidence:
                unavailable[stream_name] = "selected record has no evidence identifier"
                continue
            temporal_matches[stream_name] = {
                "record_id": str(record.get("record_id") or record.get("evidence_id") or evidence[0]),  # type: ignore[union-attr]
                "evidence_ids": list(evidence),
                "selected_evidence_date": match["selected_evidence_date"],
                "selected_interval_start": match["selected_interval_start"],
                "selected_interval_end": match["selected_interval_end"],
                "date_precision": match["date_precision"],
                "temporal_gap_days": match["temporal_gap_days"],
                "temporal_direction": match["temporal_direction"],
            }

        mass_result: dict[str, object] | None = None
        population_result: dict[str, object] | None = None
        cpc_result: dict[str, object] | None = None
        chemistry_result: dict[str, object] | None = None
        edi_result: dict[str, object] | None = None
        thq_result: dict[str, object] | None = None
        point_blockers: list[dict[str, str]] = []

        mass_match = matches.get("mass") if "mass" in temporal_matches else None
        if mass_match is not None:
            try:
                mass_lower, mass_upper = _record_interval(
                    mass_match["record"],  # type: ignore[arg-type]
                    lower_fields=("allocated_mass_lower_kg_year", "mass_lower", "lower", "value"),
                    upper_fields=("allocated_mass_upper_kg_year", "mass_upper", "upper"),
                    name="node product mass",
                )
                mass_result = {"lower": mass_lower, "upper": mass_upper, "unit": str(mass_match["record"].get("unit") or "kg/year")}  # type: ignore[union-attr]
            except ValueError as exc:
                point_blockers.append({"claim": "node product mass", "reason": str(exc)})

        population_match = matches.get("population") if "population" in temporal_matches else None
        if population_match is not None:
            try:
                population_lower, population_upper = _record_interval(
                    population_match["record"],  # type: ignore[arg-type]
                    lower_fields=("consumer_population_lower", "population_lower", "lower", "value"),
                    upper_fields=("consumer_population_upper", "population_upper", "upper"),
                    name="node population projection",
                    positive=True,
                )
                population_result = {"lower": population_lower, "upper": population_upper, "unit": "persons"}
            except ValueError as exc:
                point_blockers.append({"claim": "node population projection", "reason": str(exc)})

        direct_match = matches.get("direct_cpc") if "direct_cpc" in temporal_matches else None
        if direct_match is not None:
            try:
                cpc_lower, cpc_upper = _record_interval(
                    direct_match["record"],  # type: ignore[arg-type]
                    lower_fields=("measured_lower", "cpc_lower", "lower", "value"),
                    upper_fields=("measured_upper", "cpc_upper", "upper"),
                    name="direct node CPC",
                )
                cpc_result = {
                    "lower": cpc_lower,
                    "upper": cpc_upper,
                    "unit": str(direct_match["record"].get("unit") or "kg/person/year"),  # type: ignore[union-attr]
                    "mode": "nearest_certified_direct_node_cpc",
                }
            except ValueError as exc:
                point_blockers.append({"claim": "direct node CPC", "reason": str(exc)})
        elif mass_result is not None and population_result is not None:
            mass_record = mass_match["record"] if mass_match is not None else {}
            mass_is_edible = bool(config.get("mass_is_edible", False) or mass_record.get("mass_is_edible", False))  # type: ignore[union-attr]
            raw_yield_lower = config.get("edible_yield_lower")
            raw_yield_upper = config.get("edible_yield_upper")
            if mass_is_edible:
                yield_lower = yield_upper = 1.0
            elif raw_yield_lower not in MISSING:
                yield_lower = _finite_nonnegative(raw_yield_lower, "edible_yield_lower")
                yield_upper = _finite_nonnegative(raw_yield_upper if raw_yield_upper not in MISSING else raw_yield_lower, "edible_yield_upper")
            else:
                yield_lower = yield_upper = -1.0
                point_blockers.append({"claim": "derived node CPC", "reason": "mass must be certified as edible or carry an edible-yield interval"})
            if yield_lower >= 0:
                if yield_lower > yield_upper:
                    point_blockers.append({"claim": "derived node CPC", "reason": "edible-yield interval endpoints are inconsistent"})
                else:
                    cpc_result = {
                        "lower": float(mass_result["lower"]) * yield_lower / float(population_result["upper"]),
                        "upper": float(mass_result["upper"]) * yield_upper / float(population_result["lower"]),
                        "unit": str(config.get("cpc_unit") or "kg/person/year"),
                        "mode": "nearest_mass_divided_by_nearest_population_projection",
                        "edible_yield_lower": yield_lower,
                        "edible_yield_upper": yield_upper,
                    }
        elif mass_result is not None:
            point_blockers.append({"claim": "derived node CPC", "reason": "no compatible population projection matched this target date"})

        chemistry_match = matches.get("chemistry") if "chemistry" in temporal_matches else None
        if chemistry_match is not None:
            try:
                concentration_lower, concentration_upper = _record_interval(
                    chemistry_match["record"],  # type: ignore[arg-type]
                    lower_fields=("concentration_lower_mg_per_kg_food", "concentration_mg_per_kg_food", "lower", "value"),
                    upper_fields=("concentration_upper_mg_per_kg_food", "upper"),
                    name="food chemistry",
                )
                chemistry_result = {"lower": concentration_lower, "upper": concentration_upper, "unit": "mg/kg-food"}
            except ValueError as exc:
                point_blockers.append({"claim": "food chemistry", "reason": str(exc)})

        body_weight_match = matches.get("body_weight") if "body_weight" in temporal_matches else None
        body_weight_interval: tuple[float, float] | None = None
        if body_weight_match is not None:
            try:
                body_weight_interval = _record_interval(
                    body_weight_match["record"],  # type: ignore[arg-type]
                    lower_fields=("body_weight_lower_kg", "body_weight_kg", "lower", "value"),
                    upper_fields=("body_weight_upper_kg", "upper"),
                    name="body weight",
                    positive=True,
                )
            except ValueError as exc:
                point_blockers.append({"claim": "estimated daily intake", "reason": str(exc)})
        if cpc_result is not None and chemistry_result is not None and body_weight_interval is not None:
            edi_result = {
                "lower": float(cpc_result["lower"]) * float(chemistry_result["lower"]) / (days_per_period * body_weight_interval[1]),
                "upper": float(cpc_result["upper"]) * float(chemistry_result["upper"]) / (days_per_period * body_weight_interval[0]),
                "unit": "mg/kg-bodyweight/day",
            }

        reference_match = matches.get("reference_dose") if "reference_dose" in temporal_matches else None
        reference_interval: tuple[float, float] | None = None
        if reference_match is not None:
            try:
                reference_interval = _record_interval(
                    reference_match["record"],  # type: ignore[arg-type]
                    lower_fields=("reference_dose_lower_mg_per_kg_day", "reference_dose_mg_per_kg_day", "lower", "value"),
                    upper_fields=("reference_dose_upper_mg_per_kg_day", "upper"),
                    name="reference dose",
                    positive=True,
                )
            except ValueError as exc:
                point_blockers.append({"claim": "target hazard quotient", "reason": str(exc)})
        if edi_result is not None and reference_interval is not None:
            thq_result = {
                "lower": float(edi_result["lower"]) / reference_interval[1],
                "upper": float(edi_result["upper"]) / reference_interval[0],
                "unit": "THQ",
            }

        if thq_result is None:
            alarm = {"status": "not_computable", "threshold_thq": 1.0}
        else:
            thq_lower, thq_upper = float(thq_result["lower"]), float(thq_result["upper"])
            alarm_status = "alarm_across_interval" if thq_lower >= 1 else "threshold_crossing_within_interval" if thq_upper >= 1 else "no_alarm_within_interval"
            alarm = {"status": alarm_status, "threshold_thq": 1.0}

        if thq_result is not None:
            point_status = "mass_cpc_edi_thq_computed"
        elif edi_result is not None:
            point_status = "mass_cpc_edi_computed"
        elif cpc_result is not None:
            point_status = "mass_and_cpc_computed" if mass_result is not None else "cpc_computed"
        elif mass_result is not None:
            point_status = "mass_only"
        else:
            point_status = "insufficient_compatible_evidence"
        certificate = {
            "target_date": target_date,
            "anchor_stream": anchor_stream,
            "matching_rule": "nearest certified identity-compatible observation selected independently per predictor stream",
            "direction_policy": _text(direction_policy).replace(" ", "_"),
            "max_gap_days": max_gap_days,
            "contemporaneousness_required": False,
            "selected_predictor_dates": {name: details["selected_evidence_date"] for name, details in temporal_matches.items()},
            "temporal_gap_days": {name: details["temporal_gap_days"] for name, details in temporal_matches.items()},
            "unavailable_streams": unavailable,
        }
        point_payload = {
            "target_date": target_date,
            "mass": mass_result,
            "cpc": cpc_result,
            "edi": edi_result,
            "thq": thq_result,
            "temporal_matches": temporal_matches,
            "blockers": point_blockers,
        }
        points.append({
            "trend_claim_id": _claim_id(point_payload),
            "target_date": target_date,
            "status": point_status,
            "node_product_mass": mass_result,
            "population": population_result,
            "cpc": cpc_result,
            "chemistry": chemistry_result,
            "estimated_daily_intake": edi_result,
            "target_hazard_quotient": thq_result,
            "alarm": alarm,
            "temporal_matches": temporal_matches,
            "blocked_outputs": point_blockers,
            "calculation_certificate": certificate,
        })

    return {
        "status": "computed",
        "anchor_stream": anchor_stream,
        "target_dates": target_dates,
        "point_count": len(points),
        "matching_policy": {
            "rule": "nearest certified compatible record per stream and target date",
            "direction_policy": _text(direction_policy).replace(" ", "_"),
            "tie_break": "prefer the earlier record when temporal distances are equal",
            "max_gap_days": max_gap_days,
            "contemporaneousness_required": False,
            "temporal_intervals_preserved": True,
        },
        "points": points,
    }


def run_typed_model(
    payload: Mapping[str, object],
    *,
    active_evidence: Mapping[str, object] | None = None,
    contaminant_trace: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Apply the TEM admissible-claim operator while preserving UI keys."""
    temporal_trend = run_temporal_trend(payload) if isinstance(payload.get("temporal_trend") or payload.get("trend"), Mapping) else None
    cpc_input = dict(payload.get("cpc") or {}) if isinstance(payload.get("cpc"), Mapping) else dict(payload)
    allocation = dict(payload.get("allocation") or {}) if isinstance(payload.get("allocation"), Mapping) else {}
    trace_records = list((contaminant_trace or {}).get("records", []))
    dependencies: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    raw_certificates = payload.get("certificates")
    certificate_inputs = dict(raw_certificates) if isinstance(raw_certificates, Mapping) else {}

    def evidence_ids(value: Mapping[str, object], *, fallback: str = "") -> tuple[str, ...]:
        raw = value.get("evidence_ids")
        if isinstance(raw, (list, tuple, set)):
            identifiers = [str(item) for item in raw if str(item)]
        elif raw not in MISSING:
            identifiers = [str(raw)]
        else:
            identifiers = []
        single = str(value.get("evidence_id") or fallback)
        if single:
            identifiers.append(single)
        return tuple(dict.fromkeys(identifiers))

    def certified_mapping(name: str) -> Mapping[str, object]:
        value = certificate_inputs.get(name)
        if not isinstance(value, Mapping) or _text(value.get("status")) != "certified":
            raise ValueError(f"{name} certificate is required and must be certified")
        return value

    for record in trace_records:
        if record.get("value") in MISSING or record.get("unit") in MISSING:
            blockers.append({
                "claim": "quantitative contaminant propagation",
                "evidence_id": str(record.get("evidence_id") or record.get("record_id") or ""),
                "reason": "linked source summary has no machine-readable concentration and unit; provenance is retained without numerical propagation",
            })

    allocation_requested = any(value not in MISSING for value in allocation.values())
    explicit_cpc_requested = cpc_input.get("measured_lower") not in MISSING
    cpc_resolution: dict[str, object] = {"mode": "none", "certificate_ids": []}
    analysis_reference_date = str(payload.get("analysis_date") or payload.get("flow_as_of") or payload.get("as_of") or "")
    evidence_cutoff = str(payload.get("evidence_cutoff") or "latest_available_at_run")
    temporal_selection: dict[str, object] = {
        "analysis_reference_date": analysis_reference_date or None,
        "evidence_cutoff": evidence_cutoff,
        "selection_rule": "select the latest identity-compatible CPC/mass/population/chemistry evidence independently within its stream",
        "contemporaneousness_required": False,
        "cross_date_join_rule": "different evidence dates are admissible when identity, applicability and provenance certificates are satisfied",
    }

    # A certified explicit CPC for one exact node has absolute precedence.  A
    # population number supplied alongside it is ignored rather than used to
    # silently recalculate the node CPC.
    if explicit_cpc_requested:
        try:
            direct_input = certified_mapping("direct_cpc")
            raw_signature = cpc_input.get("signature")
            raw_certificate_signature = direct_input.get("signature")
            if not isinstance(raw_signature, Mapping) or not isinstance(raw_certificate_signature, Mapping):
                raise ValueError("explicit node CPC requires claim and certificate identity signatures")
            claim_signature = IdentitySignature.from_mapping(raw_signature)
            certificate_signature = IdentitySignature.from_mapping(raw_certificate_signature)
            direct_evidence = evidence_ids(direct_input)
            if not direct_evidence:
                raise ValueError("direct_cpc certificate requires evidence_ids")
            direct_certificate = DirectCPCCertificate(
                certificate_id=str(direct_input.get("certificate_id") or ""),
                signature=certificate_signature,
                evidence_ids=direct_evidence,
                boundary=str(direct_input.get("boundary") or ""),
            )
            explicit_claim = IntervalMeasureClaim(
                signature=claim_signature,
                lower=_finite_nonnegative(cpc_input["measured_lower"], "measured_lower"),
                upper=_finite_nonnegative(cpc_input.get("measured_upper", cpc_input["measured_lower"]), "measured_upper"),
                evidence_ids=evidence_ids(cpc_input, fallback=direct_evidence[0]),
                expression="explicit node CPC supplied to model run",
            )
            resolved_cpc = resolve_node_cpc_claim(
                explicit_cpc=explicit_claim,
                direct_cpc_certificate=direct_certificate,
            )
            cpc_input["measured_lower"], cpc_input["measured_upper"] = resolved_cpc.lower, resolved_cpc.upper
            recalculation = {
                "status": "explicit_node_cpc_used",
                "destination_node": resolved_cpc.signature.destination,
                "cpc_lower": resolved_cpc.lower,
                "cpc_upper": resolved_cpc.upper,
                "unit": resolved_cpc.signature.unit,
                "certificate_ids": list(resolved_cpc.certificate_ids),
                "rule": "Certified explicit CPC for the exact node takes precedence; population-based derivation was not run.",
            }
            cpc_resolution = {"mode": "certified_explicit_node_cpc", "certificate_ids": list(resolved_cpc.certificate_ids)}
            temporal_selection.update({
                "cpc_mode": "reported_or_computed_explicit_node_cpc",
                "cpc_period": resolved_cpc.signature.period,
                "cpc_evidence_date": direct_input.get("evidence_date") or direct_input.get("observed_at") or resolved_cpc.signature.period,
                "mass_periods": [],
                "population_projection_vintage": None,
                "population_target_period": None,
            })
            dependencies.append({"input": "explicit_node_cpc", "role": "certified exact-node CPC", "certificate_ids": list(resolved_cpc.certificate_ids)})
        except (TypeError, ValueError) as exc:
            cpc_input.pop("measured_lower", None)
            cpc_input.pop("measured_upper", None)
            reason = str(exc)
            recalculation = {"status": "blocked", "reason": reason}
            blockers.append({"claim": "explicit node CPC", "reason": reason})
            cpc_resolution = {"mode": "blocked_explicit_node_cpc", "certificate_ids": []}
    elif allocation_requested:
        try:
            if allocation.get("allocated_mass_lower_kg_year") in MISSING:
                raise ValueError("derived node CPC requires an allocated mass lower bound")
            mass_lower = _finite_nonnegative(allocation["allocated_mass_lower_kg_year"], "allocated_mass_lower_kg_year")
            mass_upper = mass_lower if allocation.get("allocated_mass_upper_kg_year") in MISSING else _finite_nonnegative(allocation["allocated_mass_upper_kg_year"], "allocated_mass_upper_kg_year")
            population_lower_raw = allocation.get("consumer_population_lower", allocation.get("consumer_population"))
            if population_lower_raw in MISSING:
                raise ValueError("derived node CPC requires a projected consumer population")
            population_lower = _finite_nonnegative(population_lower_raw, "consumer_population_lower")
            population_upper = population_lower if allocation.get("consumer_population_upper") in MISSING else _finite_nonnegative(allocation["consumer_population_upper"], "consumer_population_upper")
            if mass_lower > mass_upper or population_lower <= 0 or population_lower > population_upper:
                raise ValueError("compatible mass and population intervals are inconsistent")

            projection_input = certified_mapping("population_projection")
            allocation_input = certified_mapping("cpc_allocation")
            raw_mass_signature = allocation_input.get("mass_signature")
            raw_population_signature = allocation_input.get("population_signature")
            raw_output_signature = allocation_input.get("output_signature")
            raw_projection_signature = projection_input.get("signature")
            if not all(isinstance(item, Mapping) for item in (raw_mass_signature, raw_population_signature, raw_output_signature, raw_projection_signature)):
                raise ValueError("population_projection and cpc_allocation certificates require exact identity signatures")
            mass_signature = IdentitySignature.from_mapping(raw_mass_signature)  # type: ignore[arg-type]
            population_signature = IdentitySignature.from_mapping(raw_population_signature)  # type: ignore[arg-type]
            output_signature = IdentitySignature.from_mapping(raw_output_signature)  # type: ignore[arg-type]
            projection_signature = IdentitySignature.from_mapping(raw_projection_signature)  # type: ignore[arg-type]
            projection_evidence = evidence_ids(projection_input)
            allocation_evidence = evidence_ids(allocation_input)
            mass_evidence = evidence_ids(allocation, fallback=str(allocation_input.get("mass_evidence_id") or ""))
            if not projection_evidence or not allocation_evidence or not mass_evidence:
                raise ValueError("derived node CPC requires mass, population-projection and allocation evidence_ids")
            projection_certificate = PopulationProjectionCertificate(
                certificate_id=str(projection_input.get("certificate_id") or ""),
                signature=projection_signature,
                projection_scenario=str(projection_input.get("projection_scenario") or ""),
                geographic_level=str(projection_input.get("geographic_level") or ""),
                projection_as_of=str(projection_input.get("projection_as_of") or ""),
                evidence_ids=projection_evidence,
                boundary=str(projection_input.get("boundary") or ""),
            )
            allocation_certificate = CPCAllocationCertificate(
                certificate_id=str(allocation_input.get("certificate_id") or ""),
                mass_signature=mass_signature,
                population_signature=population_signature,
                output_signature=output_signature,
                edible_yield_lower=_finite_nonnegative(allocation_input.get("edible_yield_lower"), "edible_yield_lower"),
                edible_yield_upper=_finite_nonnegative(allocation_input.get("edible_yield_upper"), "edible_yield_upper"),
                evidence_ids=allocation_evidence,
                boundary=str(allocation_input.get("boundary") or ""),
            )
            mass_claim = IntervalMeasureClaim(mass_signature, mass_lower, mass_upper, mass_evidence, expression="allocated node mass")
            population_claim = IntervalMeasureClaim(population_signature, population_lower, population_upper, projection_evidence, expression="named current node population projection")
            resolved_cpc = resolve_node_cpc_claim(
                allocated_mass=mass_claim,
                consumer_population=population_claim,
                population_certificate=projection_certificate,
                allocation_certificate=allocation_certificate,
            )
            cpc_input["measured_lower"], cpc_input["measured_upper"] = resolved_cpc.lower, resolved_cpc.upper
            recalculation = {
                "status": "computed_from_certified_population_projection",
                "allocated_mass_lower_kg_year": mass_lower,
                "allocated_mass_upper_kg_year": mass_upper,
                "consumer_population_lower": population_lower,
                "consumer_population_upper": population_upper,
                "population_projection_scenario": projection_certificate.projection_scenario,
                "population_geographic_level": projection_certificate.geographic_level,
                "population_projection_as_of": projection_certificate.projection_as_of,
                "destination_node": resolved_cpc.signature.destination,
                "cpc_lower": resolved_cpc.lower,
                "cpc_upper": resolved_cpc.upper,
                "unit": resolved_cpc.signature.unit,
                "certificate_ids": list(resolved_cpc.certificate_ids),
                "rule": "Allocated edible mass divided by a named current projection for the exact country/city/town/village node.",
            }
            cpc_resolution = {"mode": "certified_population_projection", "certificate_ids": list(resolved_cpc.certificate_ids)}
            temporal_selection.update({
                "cpc_mode": "derived_from_latest_eligible_mass_and_applicable_population_projection",
                "cpc_period": resolved_cpc.signature.period,
                "mass_periods": [mass_signature.period],
                "population_projection_vintage": projection_certificate.projection_as_of,
                "population_target_period": population_signature.period,
            })
            dependencies.extend([
                {"input": "allocated_mass_interval", "role": "certified compatible node mass", "evidence_ids": list(mass_evidence)},
                {"input": "consumer_population_interval", "role": "named current exact-node projection", "evidence_ids": list(projection_evidence)},
                {"input": "cpc_allocation", "role": "edible-yield and mass/population join", "certificate_ids": list(resolved_cpc.certificate_ids)},
            ])
        except (TypeError, ValueError) as exc:
            cpc_input.pop("measured_lower", None)
            cpc_input.pop("measured_upper", None)
            reason = str(exc)
            recalculation = {"status": "blocked", "reason": reason}
            blockers.append({"claim": "derived node CPC", "reason": reason})
            cpc_resolution = {"mode": "blocked_population_derivation", "certificate_ids": []}
    else:
        recalculation = {
            "status": "not_requested",
            "reason": "Provide a certified explicit CPC for the exact node, or certified allocated mass plus a named current exact-node population projection.",
        }

    required = ("identified_lower", "identified_upper", "measured_lower")
    if all(cpc_input.get(field) not in MISSING for field in required):
        identified = (
            _finite_nonnegative(cpc_input["identified_lower"], "identified_lower"),
            _finite_nonnegative(cpc_input["identified_upper"], "identified_upper"),
        )
        measured = (
            _finite_nonnegative(cpc_input["measured_lower"], "measured_lower"),
            _finite_nonnegative(cpc_input.get("measured_upper", cpc_input["measured_lower"]), "measured_upper"),
        )
        if identified[0] > identified[1] or measured[0] > measured[1]:
            raise ValueError("CPC interval endpoints are inconsistent")
        comparison = _compare_intervals(identified, measured)
        cpc_status = "computed"
    else:
        comparison = None
        cpc_status = "not_computed"

    chemistry_fields = ("concentration_mg_per_kg_food", "body_weight_kg", "reference_dose_mg_per_kg_day")
    chemistry_supplied = all(cpc_input.get(field) not in MISSING for field in chemistry_fields)
    chemistry_certificate = _chemistry_certificate(payload, trace_records)
    chemistry_input = certificate_inputs.get("chemistry")
    if isinstance(chemistry_input, Mapping):
        raw_chemistry_signature = chemistry_input.get("signature")
        temporal_selection["chemistry_period"] = (
            IdentitySignature.from_mapping(raw_chemistry_signature).period
            if isinstance(raw_chemistry_signature, Mapping)
            else chemistry_input.get("period")
        )
        temporal_selection["chemistry_evidence_date"] = chemistry_input.get("evidence_date") or chemistry_input.get("observed_at") or chemistry_input.get("period")
    elif trace_records:
        temporal_selection["chemistry_evidence_dates"] = [
            record.get("observed_at") or record.get("period") or record.get("year")
            for record in trace_records
            if record.get("observed_at") or record.get("period") or record.get("year")
        ]
    if comparison is not None and chemistry_supplied and chemistry_certificate["certified"]:
        concentration = _finite_nonnegative(cpc_input["concentration_mg_per_kg_food"], "concentration_mg_per_kg_food")
        body_weight = _finite_nonnegative(cpc_input["body_weight_kg"], "body_weight_kg")
        reference_dose = _finite_nonnegative(cpc_input["reference_dose_mg_per_kg_day"], "reference_dose_mg_per_kg_day")
        if body_weight <= 0 or reference_dose <= 0:
            raise ValueError("body weight and reference dose must be positive")
        matched_lower, matched_upper = comparison["matched_cpc_lower"], comparison["matched_cpc_upper"]
        if matched_lower is None or matched_upper is None:
            hazard = {"hq_matched_lower": None, "hq_matched_upper": None, "hi_total_status": "not_identified", "reason": comparison["chemistry_rule"]}
        else:
            factor = concentration / (365.0 * body_weight * reference_dose)
            hazard = {
                "hq_matched_lower": factor * float(matched_lower),
                "hq_matched_upper": factor * float(matched_upper),
                "hi_total_status": "partial" if comparison["status"] == "upper_envelope_miss" else "identified_for_selected_analyte",
                "reason": comparison["chemistry_rule"],
                "chemistry_certificate": chemistry_certificate["certificate"],
            }
    else:
        reason = chemistry_certificate["reason"] if chemistry_supplied else "Compatible chemistry inputs were not supplied."
        hazard = {"hq_matched_lower": None, "hq_matched_upper": None, "hi_total_status": "blocked_by_evidence_identity" if chemistry_supplied else "chemistry_not_supplied", "reason": reason}
        if chemistry_supplied:
            blockers.append({"claim": "hazard quotient", "reason": reason, "linked_evidence_ids": sorted(str(record.get("evidence_id") or "") for record in trace_records if record.get("evidence_id"))})

    hq_lower, hq_upper = hazard.get("hq_matched_lower"), hazard.get("hq_matched_upper")
    if hq_lower is None or hq_upper is None:
        alarm = {"status": "not_computable", "threshold_hq": 1.0, "scope": "certified identity-compatible CPC only", "reason": hazard["reason"]}
    else:
        alarm_status = "alarm_across_matched_interval" if float(hq_lower) >= 1 else "threshold_crossing_within_matched_interval" if float(hq_upper) >= 1 else "no_alarm_within_matched_interval"
        alarm = {"status": alarm_status, "threshold_hq": 1.0, "hq_lower": hq_lower, "hq_upper": hq_upper, "scope": "certified identity-compatible CPC only", "completeness": "partial" if hazard.get("hi_total_status") == "partial" else "identified", "reason": hazard["reason"]}

    cpc_result: dict[str, object] = {
        "status": cpc_status,
        "comparison": comparison,
        "hazard": hazard,
        "alarm_projection": alarm,
        "recalculation": recalculation,
    }
    if comparison is None:
        cpc_result["reason"] = "Identified and measured/recalculated CPC intervals are required."

    claim_payload = {
        "operator": "TEM_ADMISSIBLE_CLAIM_V0_3",
        "selection": active_evidence or {},
        "comparison": comparison,
        "hazard": hazard,
        "dependencies": dependencies,
        "blockers": blockers,
    }
    claim = {
        "claim_id": _claim_id(claim_payload),
        "operator": "TEM_ADMISSIBLE_CLAIM_V0_3",
        "status": "blocked" if blockers else "identified" if comparison is not None else "insufficient_evidence",
        "quantity": "CPC compatibility and matched hazard",
        "comparison": comparison,
        "hazard": hazard,
        "dependencies": dependencies,
        "blocked_evidence": blockers,
        "identity_rule": "identity may change only through an explicit transformation certificate",
    }
    return {
        "cpc_result": cpc_result,
        "recalculation": recalculation,
        "temflow_claims": [claim],
        "blocked_evidence": blockers,
        "calculation_certificate": {
            "operator": "TEM_ADMISSIBLE_CLAIM_V0_3",
            "claim_digest": hashlib.sha256(json.dumps(claim, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest(),
            "chemistry": chemistry_certificate,
            "node_cpc_resolution": cpc_resolution,
            "temporal_selection": temporal_selection,
        },
        "temporal_trend": temporal_trend,
    }


def tem_compare_and_screen(payload: Mapping[str, object]) -> dict[str, object]:
    """TEM replacement for the legacy untyped CPC endpoint."""
    result = run_typed_model({"cpc": dict(payload), "certificates": payload.get("certificates", {})})
    return {**result["cpc_result"], "temflow_claims": result["temflow_claims"], "blocked_evidence": result["blocked_evidence"], "calculation_certificate": result["calculation_certificate"]}
