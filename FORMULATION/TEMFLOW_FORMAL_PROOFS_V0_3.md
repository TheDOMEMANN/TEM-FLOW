# TEM-FLOW 0.3: definitions and safety proofs

## Scope

This document proves the safety properties created by the TEM-FLOW formulation.
It does not claim that finite measures, interval arithmetic, dimensional types,
or provenance are new. The contribution being proved is the behavior of their
certificate-gated composition in an evidential flow engine.

## 1. Objects

Let \(I\) be the set of scientific identities. An identity is the complete tuple

\[
i=(g,d,q,f,m,o,h,z,t,n,u),
\]

where the coordinates denote geography, food domain, commodity, product form,
material, origin, transient/checkpoint, destination, period, denominator, and unit. Equality in
\(I\) is coordinatewise equality.

An evidential measure is a finite-support function

\[
\mu:I\rightarrow\mathbb{R}_{\ge 0}.
\]

An interval claim is \(x=(i,[l,u],E,C)\), where \(i\in I\),
\(0\le l\le u\), \(E\) is a nonempty finite evidence set, and \(C\) is an
ordered certificate chain.

A primitive transformation certificate is

\[
c=(i,j,[a,b],E_c),\qquad 0\le a\le b,
\]

and denotes the partial map

\[
\Phi_c(i,[l,u],E,C)=
(j,[al,bu],E\cup E_c,C\mathbin{\|}c).
\]

The map is undefined when the claim identity is not exactly the certificate
input identity. A chain \((c_1,\ldots,c_k)\) is well typed only when the output
identity of \(c_r\) equals the input identity of \(c_{r+1}\) for every adjacent
pair.

The admissible closure \(\mathcal A(B,K)\) is the least set containing the base
claims \(B\) and closed under the defined certificate maps in \(K\), monotone
interval multiplication with an explicitly supplied output identity, and
addition only within a single identity atom. An undefined operation creates a
blocker record and adds no numerical claim to \(\mathcal A\).

## 2. Identity non-amalgamation

**Theorem 1.** If \(i\ne j\), adding measures supported at \(i\) and \(j\) does
not replace them by one atom.

**Proof.** Measure addition is pointwise:
\((\mu+\nu)(k)=\mu(k)+\nu(k)\). Let \(\mu(i)=x>0\), \(\nu(j)=y>0\), and all
other values be zero. Since \(i\ne j\),
\((\mu+\nu)(i)=x\) and \((\mu+\nu)(j)=y\). Thus the support contains both
\(i\) and \(j\). Scalar projection may equal \(x+y\), but it cannot alter the
two-atom support. QED.

## 3. Certified transport conservation

**Theorem 2.** A certified transport with yield interval \([1,1]\) conserves
the mass interval.

**Proof.** For any admissible input \((i,[l,u],E,C)\), the certificate map gives
the output interval \([1\cdot l,1\cdot u]=[l,u]\). Only the identity and witness
change. QED.

This theorem does not assert that transport occurred. Occurrence requires a base
measure or an explicitly labelled model-derived claim in addition to the route
certificate.

## 4. Associativity of certificate composition

**Theorem 3.** Composition of well-typed certificate chains is associative.

**Proof.** A chain is represented by its ordered tuple of primitive
certificates, and composition is tuple concatenation. For any composable chains
\(A,B,C\),

\[
(A\mathbin{\|}B)\mathbin{\|}C
=A\mathbin{\|}(B\mathbin{\|}C)
\]

because ordered-sequence concatenation is associative. The lower yield of each
side is the product of the same ordered lower endpoints; the upper yield is the
product of the same ordered upper endpoints. Multiplication of nonnegative real
numbers is associative, so applying either parenthesization to the same input
claim gives the same output identity and numerical interval. QED.

Certificate order is not commutative: changing the order generally breaks the
endpoint typing or changes the resulting identity.

## 5. Conservative scalar projection

Define the forgetful projection

\[
\pi(\mu)=\sum_{i\in I}\mu(i)
\]

and, for a single interval claim, \(\pi(i,[l,u],E,C)=[l,u]\).

**Theorem 4.** On fully certified computations, TEM-FLOW conservatively extends
the corresponding nonnegative scalar arithmetic.

**Proof.** Pointwise addition gives
\(\pi(\mu+\nu)=\pi(\mu)+\pi(\nu)\) by finite-sum linearity. For a certificate
with yield \([a,b]\), projection after transformation is \([al,bu]\), exactly
the monotone scalar interval product. Induction on the length of a well-typed
certificate chain proves equality for every certified derivation. Therefore,
when an ED-FLOW calculation uses the same nonnegative inputs and yield factors,
TEM-FLOW projects to the same scalar interval. QED.

The converse does not hold: equal scalar projections do not imply equal
identity-indexed claims, by Theorem 1.

## 6. Sound refusal

**Theorem 5.** No identity-changing numerical claim enters the admissible
closure without a matching certificate.

**Proof.** By construction, the only closure rule whose output identity differs
from its input identity is \(\Phi_c\). That rule has two premises: a certificate
\(c\in K\), and equality between the claim identity and the certificate input.
If either premise is absent, the partial map is undefined. The remaining closure
rules preserve identity or require their output identity explicitly and do not
supply an identity-change witness. Hence no such claim can be derived. QED.

This is a syntactic safety theorem. It guarantees that unsupported joins are not
silently executed; it does not guarantee that every submitted certificate is
scientifically true. Certificate evidence therefore remains auditable.

## 7. Sharp two-margin bounds

Let a nonnegative flow table have row total \(R_i\), column total \(C_j\), and
grand total \(T\). For a certificate-admissible cell \(x_{ij}\), define

\[
L_{ij}=\max(0,R_i+C_j-T),\qquad U_{ij}=\min(R_i,C_j).
\]

**Theorem 6.** Every nonnegative table with those margins satisfies
\(L_{ij}\le x_{ij}\le U_{ij}\), and both endpoints are attainable whenever the
remaining cells are unrestricted.

**Proof.** Since a cell cannot exceed either its row or column sum,
\(x_{ij}\le\min(R_i,C_j)\). The mass outside row \(i\) is \(T-R_i\), so at most
that amount of column \(j\) can lie outside the cell. Therefore
\(x_{ij}\ge C_j-(T-R_i)=R_i+C_j-T\), together with nonnegativity. To attain the
upper endpoint, place as much as possible at \((i,j)\) and distribute the
remaining margins outside it. To attain the lower endpoint, place as much of
column \(j\) as possible outside row \(i\), then distribute the remainder.
These constructions respect nonnegative residual margins. QED.

TEM-FLOW emits this interval only when the route identity is certified. It does
not select a midpoint and does not interpret a possible cell as an observed
shipment.

In the implementation a route certificate carries one complete
`IdentitySignature`; equality with the requested cell signature is a necessary
precondition. Thus an arbitrary nonempty certificate label cannot satisfy the
gate. This realizes Theorem 5 for route admission as well as for transformation
chains.

## 8. Sharp three-margin path bounds

Let (x_{ohz}\ge0) be a source-transient-destination tensor with source margin
(S_o), transient margin (H_h), destination margin (D_z), and total (T).
Define

\[
L_{ohz}=\max(0,S_o+H_h+D_z-2T),\qquad
U_{ohz}=\min(S_o,H_h,D_z).
\]

**Theorem 7.** Every nonnegative tensor with these one-way margins satisfies
(L_{ohz}\le x_{ohz}\le U_{ohz}). Both endpoints are sharp when residual
cells are unrestricted.

**Proof.** The upper bound follows because the cell is contained in each of its
three margins. For the lower bound, the complement of the source slice has mass
(T-S_o), the complement of the transient slice (T-H_h), and the complement
of the destination slice (T-D_z). All mass outside the triple intersection is
contained in the union of those three complements and is therefore at most
((T-S_o)+(T-H_h)+(T-D_z)). Hence
(T-x_{ohz}\le3T-S_o-H_h-D_z), or
(x_{ohz}\ge S_o+H_h+D_z-2T), together with nonnegativity. Sharpness follows
by collapsing each dimension into the selected category and its complement,
placing the greatest respectively least feasible mass in the triple
intersection, and then splitting the residual complement cells among the
unrestricted categories to match their margins. QED.

The software adds an exact `PathCertificate` premise. Tensor feasibility does
not by itself authorize a named path claim.

## 9. Conservative certified CPC and exposure propagation

**Theorem 8.** Let (M,e,P,C,W,R) be nonnegative closed intervals, with
(P^-,W^-,R^->0), and let (d>0). The CPC, EDI, and HQ intervals defined in
the formulation enclose every scalar result obtained from values selected from
the respective input intervals.

**Proof.** Products of nonnegative inputs are coordinatewise increasing.
Division by a positive variable is increasing in the numerator and decreasing
in the denominator. Therefore the smallest CPC uses (M^-,e^-,P^+), while the
largest uses (M^+,e^+,P^-). Applying the same monotonicity to concentration,
body weight, days, and reference dose gives the stated EDI and HQ endpoints.
Exact certificate equality is a separate admissibility premise, so no result is
emitted for an unmatched food, tissue, node, population, analyte, or unrecorded
temporal selection. Equality applies between each input and its own certificate;
it does not require the CPC, mass, projection, and chemistry dates to equal one
another.
QED.

For derived CPC, the implementation adds the premise that the population claim
equals a `PopulationProjectionCertificate` naming a current scenario and the
exact country/city/town/village node. If a node-specific CPC is explicitly
reported, `DirectCPCCertificate` exact equality selects it before derivation;
this is a precedence rule, not an arithmetic transformation.

Temporal selection is asynchronous. Given an evidence cutoff (K), each stream
selects its latest compatible record available by (K). The analysis reference
date (D), mass-observation date, projection vintage and target period, explicit
CPC date, and chemistry date may therefore differ. Theorem 8 is unchanged by
this policy because its enclosure proof depends on the selected nonnegative
intervals, not equality of their observation dates. Every selected date and the
selection rule remain part of the dependency witness.

The EDI and HQ scalar definitions are established exposure endpoints. The new
claim is the certificate-gated interval composition from a certified path/node
mass and its refusal semantics, not invention of a new toxicological endpoint.

## 10. Implementation correspondence

| Mathematical object | Implementation |
|---|---|
| \(I\) | `IdentitySignature` |
| \(\mu\) | `EvidentialMeasure` |
| interval claim | `IntervalMeasureClaim` |
| primitive certificate | `TransformationCertificate` |
| exact route certificate | `RouteCertificate` |
| exact source-transient-destination certificate | `PathCertificate` |
| mass/population/edible-yield join | `CPCAllocationCertificate` |
| exact current node-population scenario | `PopulationProjectionCertificate` |
| explicit node CPC precedence | `DirectCPCCertificate`, `resolve_node_cpc_claim` |
| CPC/chemistry/body-weight/reference-dose join | `ExposureCertificate` |
| typed chain | `TransformationChain` |
| \(\pi\) | `scalar_projection` |
| two-margin closure | `certified_marginal_flow_claim` |
| three-margin path closure | `certified_path_flow_claim` |
| node CPC enclosure | `derive_node_cpc_claim` |
| EDI/HQ enclosure | `propagate_contaminant_exposure` |
| latest eligible independent-stream selection | `latest_eligible_evidence` |
| nearest-date historical stream matching | `nearest_compatible_evidence` |
| historical node mass/CPC/EDI/THQ series | `run_temporal_trend` |

`tests/test_proof_obligations.py` supplies six executable regression witnesses
for Theorems 1-7 and the marginal/path implementations, including explicit
product-form and transient-node corruptions rejected by exact certificate
gates. CPC/exposure tests exercise Theorem 8 and incompatible-commodity refusal.
Those tests support, but do not replace, the mathematical proofs above.
