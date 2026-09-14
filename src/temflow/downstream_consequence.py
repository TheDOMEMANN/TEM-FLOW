"""Typed mass-to-CPC-to-chemistry consequence calculations.

The module keeps physical evidence, product identity, time matching and
decision rules explicit.  It does not turn missing evidence into zero and it
does not attach chemistry to a different species, form, node or period.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import math
from typing import Callable, Iterable, Sequence, TypeVar


def _number(value: float, name: str, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        condition = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {condition}")
    return result


def _day(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO date") from exc


@dataclass(frozen=True)
class Interval:
    lower: float
    upper: float
    unit: str

    def __post_init__(self) -> None:
        low = _number(self.lower, "lower")
        high = _number(self.upper, "upper")
        if low > high:
            raise ValueError("interval lower cannot exceed upper")
        if not self.unit.strip():
            raise ValueError("interval unit is required")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FlowIdentity:
    commodity: str
    species: str
    product_form: str
    origin: str
    checkpoint: str
    destination: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not str(value).strip():
                raise ValueError(f"{name} is required")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class MassEvidence:
    evidence_id: str
    identity: FlowIdentity
    observed_at: str
    mass: Interval


@dataclass(frozen=True)
class PopulationEvidence:
    evidence_id: str
    place: str
    observed_at: str
    scenario: str
    denominator: str
    population: Interval


@dataclass(frozen=True)
class CPCObservation:
    evidence_id: str
    identity: FlowIdentity
    observed_at: str
    population_place: str
    denominator: str
    cpc: Interval


@dataclass(frozen=True)
class EdibleConversionEvidence:
    evidence_id: str
    commodity: str
    product_form: str
    observed_at: str
    edible_fraction: Interval
    transfer_status: str


@dataclass(frozen=True)
class ChemistryEvidence:
    evidence_id: str
    identity: FlowIdentity
    analyte: str
    matrix: str
    tissue: str
    observed_at: str | None
    concentration: Interval


@dataclass(frozen=True)
class ToxicologyRule:
    evidence_id: str
    analyte: str
    endpoint: str
    reference_dose: Interval


@dataclass(frozen=True)
class TemporalPolicy:
    """Evidence-time rule selected by the caller, never silently assumed."""

    max_lag_days: int | None = None
    allow_unbounded_past: bool = False

    def __post_init__(self) -> None:
        if self.max_lag_days is not None and self.max_lag_days < 0:
            raise ValueError("max_lag_days cannot be negative")
        if self.max_lag_days is None and not self.allow_unbounded_past:
            return

    @property
    def declared(self) -> bool:
        return self.max_lag_days is not None or self.allow_unbounded_past


@dataclass(frozen=True)
class Blocker:
    code: str
    field: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


T = TypeVar("T")


def select_latest_on_or_before(
    records: Iterable[T],
    target_date: str,
    policy: TemporalPolicy,
    observed_at: Callable[[T], str | None] = lambda item: getattr(item, "observed_at"),
) -> tuple[T | None, dict[str, object] | None, Blocker | None]:
    """Select the closest past record and report its lag.

    Undated records are not eligible.  A future record is never used for a
    past target.  The caller must explicitly allow an unbounded past or set a
    maximum lag.
    """

    target = _day(target_date, "target_date")
    if not policy.declared:
        return None, None, Blocker(
            "temporal_policy_missing",
            "temporal_policy",
            "Set a maximum lag or explicitly allow the closest earlier record.",
        )
    eligible: list[tuple[date, T]] = []
    undated = 0
    future = 0
    for record in records:
        raw = observed_at(record)
        if raw in (None, ""):
            undated += 1
            continue
        observed = _day(str(raw), "observed_at")
        if observed > target:
            future += 1
            continue
        eligible.append((observed, record))
    if not eligible:
        detail = "No dated record occurs on or before the target date."
        if undated:
            detail += f" {undated} undated record(s) were blocked."
        if future:
            detail += f" {future} future record(s) were blocked."
        return None, None, Blocker("no_past_evidence", "observed_at", detail)
    observed, selected = max(eligible, key=lambda pair: pair[0])
    lag = (target - observed).days
    if policy.max_lag_days is not None and lag > policy.max_lag_days:
        return None, None, Blocker(
            "maximum_lag_exceeded",
            "observed_at",
            f"Closest earlier evidence is {lag} days old; maximum is {policy.max_lag_days} days.",
        )
    match = {
        "target_date": target.isoformat(),
        "observed_at": observed.isoformat(),
        "lag_days": lag,
        "policy": "maximum_lag" if policy.max_lag_days is not None else "explicit_unbounded_past",
        "max_lag_days": policy.max_lag_days,
    }
    return selected, match, None


_MASS_FACTORS_TO_KG_YEAR = {
    "kg/year": 1.0,
    "kg/yr": 1.0,
    "t/year": 1000.0,
    "tonne/year": 1000.0,
    "tonnes/year": 1000.0,
}


def mass_to_kg_year(value: Interval) -> Interval:
    try:
        factor = _MASS_FACTORS_TO_KG_YEAR[value.unit]
    except KeyError as exc:
        raise ValueError(f"unsupported annual mass unit: {value.unit}") from exc
    return Interval(value.lower * factor, value.upper * factor, "kg/year")


def cpc_to_kg_person_year(value: Interval) -> Interval:
    if value.unit in {"kg/person/year", "kg person-1 year-1"}:
        return Interval(value.lower, value.upper, "kg/person/year")
    if value.unit in {"g/person/day", "g person-1 day-1"}:
        factor = 365.0 / 1000.0
        return Interval(value.lower * factor, value.upper * factor, "kg/person/year")
    raise ValueError(f"unsupported CPC unit: {value.unit}")


def concentration_to_mg_kg(value: Interval) -> Interval:
    if value.unit in {"mg/kg", "mg kg-1"}:
        return Interval(value.lower, value.upper, "mg/kg")
    if value.unit in {"ug/kg", "µg/kg", "ug kg-1"}:
        return Interval(value.lower / 1000.0, value.upper / 1000.0, "mg/kg")
    raise ValueError(f"unsupported concentration unit: {value.unit}")


def _identity_equal(left: FlowIdentity, right: FlowIdentity) -> bool:
    return left == right


def _temporal_select(
    records: Sequence[T], target_date: str, policy: TemporalPolicy
) -> tuple[T | None, dict[str, object] | None, Blocker | None]:
    return select_latest_on_or_before(records, target_date, policy)


def calculate_cpc_state(
    *,
    identity: FlowIdentity,
    target_date: str,
    temporal_policy: TemporalPolicy,
    mass_records: Sequence[MassEvidence] = (),
    population_records: Sequence[PopulationEvidence] = (),
    conversion_records: Sequence[EdibleConversionEvidence] = (),
    explicit_cpc_records: Sequence[CPCObservation] = (),
) -> dict[str, object]:
    """Use an exact reported CPC or calculate a bounded CPC from mass.

    Exact CPC has precedence.  Otherwise the interval calculation is
    ``mass * edible fraction / population`` with denominator reversal for the
    interval endpoints.
    """

    target = _day(target_date, "target_date").isoformat()
    blockers: list[Blocker] = []
    exact_cpc = [record for record in explicit_cpc_records if _identity_equal(record.identity, identity)]
    if exact_cpc:
        selected, match, blocker = _temporal_select(exact_cpc, target, temporal_policy)
        if blocker is None and selected is not None:
            if selected.population_place != identity.destination:
                blocker = Blocker(
                    "population_place_mismatch",
                    "population_place",
                    "Reported CPC population place does not equal the destination node.",
                )
            elif not selected.denominator.strip():
                blocker = Blocker("population_denominator_missing", "denominator", "Reported CPC denominator is missing.")
            else:
                try:
                    cpc = cpc_to_kg_person_year(selected.cpc)
                except ValueError as exc:
                    blocker = Blocker("unit_incompatible", "cpc.unit", str(exc))
                else:
                    return {
                        "status": "computed",
                        "target_date": target,
                        "identity": identity.to_dict(),
                        "source": "explicit_cpc",
                        "cpc": cpc.to_dict(),
                        "evidence_ids": [selected.evidence_id],
                        "temporal_matches": {"cpc": match},
                        "transformations": ["reported CPC converted to kg/person/year"],
                        "interval_assumption": "reported CPC interval retained",
                        "blockers": [],
                    }
        if blocker is not None:
            blockers.append(blocker)

    mass_matches = [record for record in mass_records if _identity_equal(record.identity, identity)]
    if not mass_matches:
        blockers.append(Blocker("compatible_mass_missing", "mass", "No exact identity-compatible mass record is available."))
    population_matches = [
        record
        for record in population_records
        if record.place == identity.destination and bool(record.denominator.strip())
    ]
    if not population_matches:
        blockers.append(
            Blocker(
                "compatible_population_missing",
                "population",
                "No population record has the exact destination place and a declared denominator.",
            )
        )
    conversion_matches = [
        record
        for record in conversion_records
        if record.commodity == identity.commodity and record.product_form == identity.product_form
    ]
    if not conversion_matches:
        blockers.append(
            Blocker(
                "compatible_edible_conversion_missing",
                "edible_fraction",
                "No edible conversion matches the commodity and product form.",
            )
        )
    if blockers:
        return _blocked(target, identity, blockers)

    mass, mass_match, mass_blocker = _temporal_select(mass_matches, target, temporal_policy)
    population, population_match, population_blocker = _temporal_select(population_matches, target, temporal_policy)
    conversion, conversion_match, conversion_blocker = _temporal_select(conversion_matches, target, temporal_policy)
    blockers = [item for item in (mass_blocker, population_blocker, conversion_blocker) if item is not None]
    if blockers or mass is None or population is None or conversion is None:
        return _blocked(target, identity, blockers)
    if population.population.unit != "persons":
        return _blocked(target, identity, [Blocker("unit_incompatible", "population.unit", "Population unit must be persons.")])
    if conversion.edible_fraction.unit != "fraction":
        return _blocked(target, identity, [Blocker("unit_incompatible", "edible_fraction.unit", "Edible yield must be a fraction.")])
    if conversion.edible_fraction.upper > 1:
        return _blocked(target, identity, [Blocker("fraction_out_of_range", "edible_fraction", "Edible yield cannot exceed one.")])
    if population.population.lower <= 0:
        return _blocked(target, identity, [Blocker("invalid_denominator", "population", "Population lower bound must be positive.")])
    try:
        mass_kg = mass_to_kg_year(mass.mass)
    except ValueError as exc:
        return _blocked(target, identity, [Blocker("unit_incompatible", "mass.unit", str(exc))])
    edible_low = mass_kg.lower * conversion.edible_fraction.lower
    edible_high = mass_kg.upper * conversion.edible_fraction.upper
    cpc = Interval(
        edible_low / population.population.upper,
        edible_high / population.population.lower,
        "kg/person/year",
    )
    return {
        "status": "computed",
        "target_date": target,
        "identity": identity.to_dict(),
        "source": "mass_population_conversion",
        "cpc": cpc.to_dict(),
        "edible_mass": Interval(edible_low, edible_high, "kg/year").to_dict(),
        "population": population.population.to_dict(),
        "evidence_ids": [mass.evidence_id, conversion.evidence_id, population.evidence_id],
        "temporal_matches": {"mass": mass_match, "conversion": conversion_match, "population": population_match},
        "transformations": [
            "annual mass converted to kg/year",
            "edible mass interval = mass interval × edible-fraction interval",
            "CPC interval = edible mass interval / population interval",
        ],
        "interval_assumption": "non-negative outer bounds; dependence not estimated",
        "transfer_status": conversion.transfer_status,
        "blockers": [],
    }


def evaluate_consequence(
    *,
    cpc_state: dict[str, object],
    identity: FlowIdentity,
    target_date: str,
    temporal_policy: TemporalPolicy,
    analyte: str,
    matrix: str,
    tissue: str,
    chemistry_records: Sequence[ChemistryEvidence],
    toxicology_rule: ToxicologyRule,
    body_weight_kg: Interval,
) -> dict[str, object]:
    """Propagate an identified CPC interval into dose, HQ and a threshold state."""

    target = _day(target_date, "target_date").isoformat()
    if cpc_state.get("status") != "computed":
        return _blocked(
            target,
            identity,
            [Blocker("cpc_not_computed", "cpc", "Consequence calculation requires a computed compatible CPC interval.")],
        )
    if toxicology_rule.analyte != analyte:
        return _blocked(target, identity, [Blocker("toxicology_analyte_mismatch", "analyte", "Toxicology rule analyte does not match chemistry analyte.")])
    if toxicology_rule.reference_dose.unit not in {"mg/kg-bw/day", "mg kg-1 bw day-1"}:
        return _blocked(target, identity, [Blocker("unit_incompatible", "reference_dose.unit", "Reference dose must be mg/kg-bw/day.")])
    if toxicology_rule.reference_dose.lower <= 0:
        return _blocked(target, identity, [Blocker("invalid_reference_dose", "reference_dose", "Reference-dose lower bound must be positive.")])
    if body_weight_kg.unit != "kg" or body_weight_kg.lower <= 0:
        return _blocked(target, identity, [Blocker("invalid_body_weight", "body_weight", "Body-weight interval must be positive and in kg.")])

    exact = [
        record
        for record in chemistry_records
        if _identity_equal(record.identity, identity)
        and record.analyte == analyte
        and record.matrix == matrix
        and record.tissue == tissue
    ]
    if not exact:
        return _blocked(
            target,
            identity,
            [
                Blocker(
                    "compatible_chemistry_missing",
                    "chemistry",
                    "No chemistry record matches commodity, species, product form, route state, analyte, matrix and tissue.",
                )
            ],
        )
    chemistry, chemistry_match, chemistry_blocker = _temporal_select(exact, target, temporal_policy)
    if chemistry_blocker is not None or chemistry is None:
        return _blocked(target, identity, [chemistry_blocker] if chemistry_blocker is not None else [])
    try:
        concentration = concentration_to_mg_kg(chemistry.concentration)
        cpc_dict = cpc_state["cpc"]
        if not isinstance(cpc_dict, dict):
            raise ValueError("CPC payload is invalid")
        cpc = cpc_to_kg_person_year(Interval(float(cpc_dict["lower"]), float(cpc_dict["upper"]), str(cpc_dict["unit"])))
    except (KeyError, TypeError, ValueError) as exc:
        return _blocked(target, identity, [Blocker("unit_incompatible", "calculation_input", str(exc))])

    dose = Interval(
        cpc.lower * concentration.lower / (365.0 * body_weight_kg.upper),
        cpc.upper * concentration.upper / (365.0 * body_weight_kg.lower),
        "mg/kg-bw/day",
    )
    hq = Interval(
        dose.lower / toxicology_rule.reference_dose.upper,
        dose.upper / toxicology_rule.reference_dose.lower,
        "HQ",
    )
    classification = threshold_classification(hq, 1.0)
    evidence_ids = list(cpc_state.get("evidence_ids", [])) + [chemistry.evidence_id, toxicology_rule.evidence_id]
    return {
        "status": "computed",
        "target_date": target,
        "identity": identity.to_dict(),
        "analyte": analyte,
        "matrix": matrix,
        "tissue": tissue,
        "cpc": cpc.to_dict(),
        "concentration": concentration.to_dict(),
        "dose": dose.to_dict(),
        "hazard_quotient": hq.to_dict(),
        "threshold_hq": 1.0,
        "threshold_classification": classification,
        "evidence_ids": evidence_ids,
        "temporal_matches": {**dict(cpc_state.get("temporal_matches", {})), "chemistry": chemistry_match},
        "transformations": list(cpc_state.get("transformations", []))
        + [
            "dose interval = CPC × concentration / 365 / body weight",
            "HQ interval = dose interval / reference-dose interval",
        ],
        "interval_assumption": "non-negative outer bounds; dependence not estimated",
        "blockers": [],
    }


def evaluate_history(target_dates: Sequence[str], **kwargs: object) -> list[dict[str, object]]:
    """Evaluate distinct dated states; each date uses only prior evidence."""

    results: list[dict[str, object]] = []
    for target_date in target_dates:
        cpc_kwargs = dict(kwargs)
        chemistry_records = cpc_kwargs.pop("chemistry_records")
        toxicology_rule = cpc_kwargs.pop("toxicology_rule")
        body_weight_kg = cpc_kwargs.pop("body_weight_kg")
        analyte = cpc_kwargs.pop("analyte")
        matrix = cpc_kwargs.pop("matrix")
        tissue = cpc_kwargs.pop("tissue")
        identity = cpc_kwargs["identity"]
        cpc_state = calculate_cpc_state(target_date=target_date, **cpc_kwargs)
        consequence = evaluate_consequence(
            cpc_state=cpc_state,
            identity=identity,
            target_date=target_date,
            temporal_policy=cpc_kwargs["temporal_policy"],
            analyte=analyte,
            matrix=matrix,
            tissue=tissue,
            chemistry_records=chemistry_records,
            toxicology_rule=toxicology_rule,
            body_weight_kg=body_weight_kg,
        )
        results.append({"target_date": target_date, "cpc_state": cpc_state, "consequence": consequence})
    return results


def threshold_classification(interval: Interval, threshold: float) -> str:
    limit = _number(threshold, "threshold")
    if interval.upper < limit:
        return "below"
    if interval.lower >= limit:
        return "above"
    return "crossing"


def _blocked(target_date: str, identity: FlowIdentity, blockers: Sequence[Blocker]) -> dict[str, object]:
    return {
        "status": "blocked",
        "target_date": target_date,
        "identity": identity.to_dict(),
        "cpc": None,
        "dose": None,
        "hazard_quotient": None,
        "evidence_ids": [],
        "blockers": [item.to_dict() for item in blockers],
        "missing_values_are_zero": False,
    }
