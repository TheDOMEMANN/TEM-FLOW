"""Evidence-bound transformation certificates for TEM-FLOW 1.0.

A certificate authorizes one identity change; it does not assert that a flow
occurred.  A quantitative claim additionally needs a compatible input measure.
This separation prevents a mapped route or a product label from becoming an
invented shipment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .tem_calculus import IdentitySignature


CERTIFIED = "certified"
BLOCKED = "blocked"
NOT_APPLICABLE = "not_applicable"


def _digest(payload: Mapping[str, object]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class CertificateRecord:
    certificate_id: str
    object_id: str
    certificate_kind: str
    status: str
    input_identity: str
    output_identity: str
    yield_lower: float | None
    yield_upper: float | None
    quantity_authorized: bool
    evidence_ids: tuple[str, ...]
    evidence_basis: str
    boundary: str
    source_release: str
    proof_digest: str = ""

    def __post_init__(self) -> None:
        if self.status not in {CERTIFIED, BLOCKED, NOT_APPLICABLE}:
            raise ValueError(f"unsupported certificate status: {self.status}")
        if self.status == CERTIFIED and not self.evidence_ids:
            raise ValueError("certified transformations require evidence")
        if self.quantity_authorized and self.status != CERTIFIED:
            raise ValueError("only certified transformations can authorize quantity")
        if (self.yield_lower is None) != (self.yield_upper is None):
            raise ValueError("yield bounds must be supplied together")
        if self.yield_lower is not None:
            if self.yield_lower < 0 or self.yield_upper is None or self.yield_lower > self.yield_upper:
                raise ValueError("invalid yield interval")
        unsigned = {key: value for key, value in asdict(self).items() if key != "proof_digest"}
        expected = _digest(unsigned)
        if self.proof_digest and self.proof_digest != expected:
            raise ValueError("certificate proof digest does not match its content")
        object.__setattr__(self, "proof_digest", expected)

    def as_row(self) -> dict[str, object]:
        row = asdict(self)
        row["evidence_ids"] = "|".join(self.evidence_ids)
        return row


def _identity(country: str, domain: str, commodity: str, form: str, origin: str, destination: str, period: str, unit: str) -> str:
    return json.dumps(asdict(IdentitySignature(
        country=country,
        food_domain=domain,
        commodity=commodity,
        product_form=form,
        origin=origin,
        destination=destination,
        period=period,
        unit=unit,
    )), sort_keys=True, separators=(",", ":"))


def build_registry_certificates(rows: Iterable[Mapping[str, object]], *, source_release: str) -> list[CertificateRecord]:
    """Classify every registry edge without treating structural edges as flow."""
    records: list[CertificateRecord] = []
    for row in rows:
        edge_id = str(row.get("edge_id") or "")
        kind = str(row.get("edge_kind") or "")
        evidence = tuple(filter(None, (str(row.get("source_reference") or ""),)))
        form = str(row.get("commodity_or_form") or "")
        quantity = str(row.get("quantity_tonnes") or "").strip()
        period = str(row.get("quantity_period") or "")
        identity_in = _identity(
            str(row.get("origin_iso3") or row.get("iso3_context") or ""),
            str(row.get("food_domain") or ""), form, form,
            str(row.get("from_node_id") or ""), "", period, "t" if quantity else "",
        )
        identity_out = _identity(
            str(row.get("destination_iso3") or row.get("iso3_context") or ""),
            str(row.get("food_domain") or ""), form, form,
            "", str(row.get("to_node_id") or ""), period, "t" if quantity else "",
        )
        if kind == "formal_cross_border_aquatic_food_form_route" and quantity:
            status, cert_kind, auth, yields = CERTIFIED, "identity_preserving_transport", True, (1.0, 1.0)
            basis = "Customs mass is attached to a product-form-specific cross-border route."
            boundary = "Certifies transport of the stated form and mass only; it does not convert product forms or periods."
        elif kind == "commodity_specific_domestic_od" and evidence:
            status, cert_kind, auth, yields = CERTIFIED, "identity_scope_transport", False, (1.0, 1.0)
            basis = "A source record identifies the same commodity at both route endpoints."
            boundary = "Identity scope is certified, but no route quantity is authorized until a compatible mass is joined."
        elif kind == "compound_parent_to_member_allocation_gate":
            status, cert_kind, auth, yields = BLOCKED, "allocation_bridge", False, (None, None)
            basis = str(row.get("claim_boundary") or "Allocation evidence is absent.")
            boundary = "A parent total cannot be distributed to members without an explicit allocation rule."
        elif kind == "formal_cross_border_aquatic_food_trade":
            status, cert_kind, auth, yields = BLOCKED, "aggregate_to_product_form", False, (None, None)
            basis = "Aggregate trade summary has separately represented product-form children."
            boundary = "The aggregate is not duplicated or propagated to a particular form."
        elif kind in {"reported_or_context_od", "reported_source_labelled_corridor", "edflow_v5_network_edge", "reported_source_consumer_context"}:
            status, cert_kind, auth, yields = BLOCKED, "topology_to_quantity", False, (None, None)
            basis = str(row.get("quantitative_state") or row.get("evidence_class") or "Topology only.")
            boundary = "Topology can admit a possible connection but cannot create a numerical flow."
        else:
            status, cert_kind, auth, yields = NOT_APPLICABLE, "structural_attachment", False, (None, None)
            basis = str(row.get("evidence_class") or "Structural registry relation.")
            boundary = "Structural membership or attachment is retained outside numerical transformation algebra."
        records.append(CertificateRecord(
            certificate_id=f"TEM-CERT-{edge_id}",
            object_id=edge_id,
            certificate_kind=cert_kind,
            status=status,
            input_identity=identity_in,
            output_identity=identity_out,
            yield_lower=yields[0],
            yield_upper=yields[1],
            quantity_authorized=auth,
            evidence_ids=evidence if status == CERTIFIED else tuple(filter(None, evidence)),
            evidence_basis=basis,
            boundary=boundary,
            source_release=source_release,
        ))
    return records


def ziway_denominator_certificate() -> CertificateRecord:
    """Evidence-supported bridge from marketed-channel share to total production."""
    evidence = ("ZIWAY_PRODUCTION_2018_MARKET_STUDY", "ZIWAY_ADDIS_TOTAL_SHARE_2018")
    return CertificateRecord(
        certificate_id="TEM-CERT-ZIWAY-ADDIS-DENOMINATOR-2018",
        object_id="ZIWAY_ADDIS_TOTAL_SHARE_2018",
        certificate_kind="denominator_bridge",
        status=CERTIFIED,
        input_identity=_identity("ETH", "fish", "fish", "marketed mixed forms", "Lake Ziway", "Addis Ababa", "2018", "share of marketed mass"),
        output_identity=_identity("ETH", "fish", "fish", "gutted, filleted and whole fish", "Lake Ziway", "Addis Ababa", "2018", "share of total production"),
        yield_lower=485.0 / 488.9,
        yield_upper=1.0,
        quantity_authorized=True,
        evidence_ids=evidence,
        evidence_basis="488.9 t produced, 485.0 t marketed, and 0.41 reported Addis channel share in the same source-year record.",
        boundary="Authorizes only the documented denominator correction; it does not allocate the remaining 59% among named markets.",
        source_release="TEMFLOW_Patterns_private_engine_v0_3_0_2026-09-01",
    )


def chamo_blocker_certificates() -> list[CertificateRecord]:
    """Explicit rejected joins for the Chamo validation case."""
    output: list[CertificateRecord] = []
    for suffix, evidence in (
        ("TIME", ("CHAMO_PRODUCTION_1990_FAO", "CHAMO_BAGRUS_CHLORPYRIFOS_CURRENT_RECORD")),
        ("MATERIAL", ("CHAMO_PRODUCTION_1990_FAO", "CHAMO_TILAPIA_DDE_CURRENT_RECORD")),
        ("ROUTE", ("CHAMO_ROUTE_ADDIS_2021_CHANNEL", "CHAMO_BAGRUS_CHLORPYRIFOS_CURRENT_RECORD")),
    ):
        output.append(CertificateRecord(
            certificate_id=f"TEM-CERT-CHAMO-BLOCK-{suffix}",
            object_id="CHAMO_VALIDATION",
            certificate_kind=f"blocked_{suffix.casefold()}_bridge",
            status=BLOCKED,
            input_identity=_identity("ETH", "fish", "fish", "all catch", "Lake Chamo", "", "1990", "t/year"),
            output_identity=_identity("ETH", "fish", "species-specific fish", "muscle", "Lake Chamo", "Addis Ababa", "2026", "mg/kg wet weight"),
            yield_lower=None,
            yield_upper=None,
            quantity_authorized=False,
            evidence_ids=evidence,
            evidence_basis="Existing records disagree on period/material identity or omit destination quantity.",
            boundary="No concentration or mass is propagated until the named mismatch is resolved by new evidence.",
            source_release="TEMFLOW_Patterns_private_engine_v0_3_0_2026-09-01",
        ))
    return output


def write_certificate_ledger(records: Iterable[CertificateRecord], csv_path: Path, jsonl_path: Path) -> None:
    items = list(records)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(items[0].as_row()) if items else list(CertificateRecord.__dataclass_fields__)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(item.as_row() for item in items)
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item.as_row(), sort_keys=True) + "\n")
