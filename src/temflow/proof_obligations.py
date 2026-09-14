"""Executable witnesses for the TEM-FLOW 1.0 formal proof obligations.

These checks are regression tests for the implementation.  The mathematical
proofs are stated separately in ``FORMULATION/TEMFLOW_FORMAL_PROOFS_V0_3.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .tem_calculus import (
    EvidentialMeasure,
    IdentitySignature,
    IntervalMeasureClaim,
    PathCertificate,
    RouteCertificate,
    TransformationCertificate,
    TransformationChain,
    certified_marginal_flow_claim,
    certified_path_flow_claim,
    scalar_projection,
)


@dataclass(frozen=True)
class ProofCheck:
    theorem: str
    passed: bool
    witness: str


def _signature(stage: str) -> IdentitySignature:
    return IdentitySignature(
        country="ETH",
        food_domain="fish",
        commodity="Nile tilapia",
        product_form=stage,
        material="edible product",
        origin="Lake Ziway",
        destination="Addis Ababa",
        period="2018",
        denominator="annual mass",
        unit="t/year",
    )


def verify_non_amalgamation() -> ProofCheck:
    whole = _signature("whole fish")
    muscle = _signature("muscle")
    result = EvidentialMeasure({whole: 10.0}).add(EvidentialMeasure({muscle: 10.0}))
    passed = len(result.atoms) == 2 and result.atoms[whole] == 10.0 and result.atoms[muscle] == 10.0
    return ProofCheck("identity non-amalgamation", passed, f"atoms={len(result.atoms)}, scalar_total={result.total}")


def verify_transport_conservation() -> ProofCheck:
    source = _signature("whole fish")
    destination = IdentitySignature(**{**source.__dict__, "origin": "", "destination": "Adama"})
    claim = IntervalMeasureClaim(source, 8.0, 12.0, ("OBS-1",))
    certificate = TransformationCertificate("CERT-TRANSPORT", source, destination, 1.0, 1.0, ("ROUTE-1",))
    output = claim.apply(certificate)
    passed = scalar_projection(output) == scalar_projection(claim)
    return ProofCheck("certified transport conservation", passed, f"input={scalar_projection(claim)}, output={scalar_projection(output)}")


def verify_chain_associativity() -> ProofCheck:
    s0, s1, s2, s3 = (_signature(f"stage-{index}") for index in range(4))
    certificates = tuple(
        TransformationCertificate(f"CERT-{index}", left, right, lower, upper, (f"E-{index}",))
        for index, (left, right, lower, upper) in enumerate(
            ((s0, s1, 0.5, 0.75), (s1, s2, 0.5, 1.0), (s2, s3, 0.25, 0.5)), start=1
        )
    )
    a, b, c = (TransformationChain((certificate,)) for certificate in certificates)
    left = a.compose(b).compose(c)
    right = a.compose(b.compose(c))
    claim = IntervalMeasureClaim(s0, 16.0, 32.0, ("OBS-CHAIN",))
    left_output, right_output = left.apply(claim), right.apply(claim)
    passed = left.certificates == right.certificates and scalar_projection(left_output) == scalar_projection(right_output)
    return ProofCheck("certificate composition associativity", passed, f"yield={left.yield_interval}, output={scalar_projection(left_output)}")


def verify_conservative_scalar_projection() -> ProofCheck:
    source, destination = _signature("source"), _signature("destination")
    claim = IntervalMeasureClaim(source, 20.0, 24.0, ("OBS-SCALAR",))
    certificate = TransformationCertificate("CERT-YIELD", source, destination, 0.5, 0.75, ("E-YIELD",))
    output = TransformationChain((certificate,)).apply(claim)
    expected = (claim.lower * certificate.yield_lower, claim.upper * certificate.yield_upper)
    passed = all(math.isclose(actual, target, rel_tol=0.0, abs_tol=1e-12) for actual, target in zip(scalar_projection(output), expected))
    return ProofCheck("conservative scalar projection", passed, f"projected={scalar_projection(output)}, scalar_baseline={expected}")


def verify_route_certificate_identity_gate() -> ProofCheck:
    signature = IdentitySignature(
        country="ETH",
        food_domain="fish",
        commodity="Nile tilapia",
        product_form="whole fish",
        origin="Lake Ziway",
        destination="Addis Ababa",
        period="2024",
        denominator="bilateral flow",
        unit="t",
    )
    certificate = RouteCertificate(
        "CERT-ROUTE-ZIWAY-ADDIS",
        signature,
        ("ROUTE-EVIDENCE",),
        "The certificate authorizes only this exact scientific identity.",
    )
    corrupted = IdentitySignature(**{**signature.__dict__, "product_form": "fillet"})
    try:
        certified_marginal_flow_claim(
            row_total=70.0,
            column_total=60.0,
            network_total=100.0,
            signature=corrupted,
            evidence_ids=("ROW", "COLUMN"),
            route_certificate=certificate,
        )
    except ValueError as error:
        passed = "product_form" in str(error)
        witness = str(error)
    else:
        passed = False
        witness = "identity-mismatched route certificate was admitted"
    return ProofCheck("exact route-certificate identity gate", passed, witness)


def verify_three_margin_path_closure() -> ProofCheck:
    signature = IdentitySignature(
        country="GHA",
        food_domain="food",
        commodity="maize",
        product_form="fresh-weight equivalent",
        origin="Yendi",
        transient="Datoyili barrier",
        destination="Tamale",
        period="2014-peak-holdout",
        denominator="path flow",
        unit="kg",
    )
    certificate = PathCertificate(
        "CERT-PATH-YENDI-DATOYILI-TAMALE",
        signature,
        ("FIELD-PATH-TRAINING",),
        "The training record certifies this exact path identity, not positive holdout mass.",
    )
    claim = certified_path_flow_claim(
        source_total=80.0,
        transient_total=70.0,
        destination_total=60.0,
        network_total=100.0,
        signature=signature,
        evidence_ids=("SOURCE-MARGIN", "TRANSIENT-MARGIN", "DESTINATION-MARGIN"),
        path_certificate=certificate,
    )
    corrupted = IdentitySignature(**{**signature.__dict__, "transient": "Airport junction"})
    try:
        certified_path_flow_claim(
            source_total=80.0,
            transient_total=70.0,
            destination_total=60.0,
            network_total=100.0,
            signature=corrupted,
            evidence_ids=("SOURCE-MARGIN", "TRANSIENT-MARGIN", "DESTINATION-MARGIN"),
            path_certificate=certificate,
        )
    except ValueError as error:
        refused = "transient" in str(error)
    else:
        refused = False
    passed = scalar_projection(claim) == (10.0, 60.0) and refused
    return ProofCheck("sharp three-margin path closure and exact transient gate", passed, f"bounds={scalar_projection(claim)}, corrupted_transient_refused={refused}")


def run_proof_checks() -> list[ProofCheck]:
    return [
        verify_non_amalgamation(),
        verify_transport_conservation(),
        verify_chain_associativity(),
        verify_conservative_scalar_projection(),
        verify_route_certificate_identity_gate(),
        verify_three_margin_path_closure(),
    ]
