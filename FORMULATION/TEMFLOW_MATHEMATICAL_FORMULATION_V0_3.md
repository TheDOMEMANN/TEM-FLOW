# TEM-FLOW 0.3: canonical mathematical formulation

## Purpose and claim boundary

TEM-FLOW constructs evidence-admissible claims rather than completing one
origin-destination table. Its primitive is an identity-indexed, interval-valued
measure with a finite dependency witness. A numerical value may enter a
downstream claim only when its scientific identity is preserved or a typed,
evidence-supported certificate explicitly authorizes the identity change.

The formulation is independent of ED-FLOW's feasible-polytope optimization and
KL minimum-change allocation. Linear programming, IPF, entropy projection, or a
machine-learning model may supply candidate values, but none is a constitutive
TEM-FLOW operator and none can create a certificate.

TEM-FLOW does not claim that finite measures, interval arithmetic, dimensional
types, or provenance are new. The contribution is their certificate-gated
composition, explicit partiality, and machine-readable refusal semantics for
data-sparse flow and exposure systems.

## 1. Scientific identities and evidential atoms

Let the identity space be

\[
I=G\times D\times Q\times F\times M\times O\times H\times Z\times T\times N\times U,
\]

where a coordinate tuple

\[
i=(g,d,q,f,m,o,h,z,t,n,u)
\]

records geography, food domain, commodity or species, product form, material or
tissue, origin, transient/checkpoint, destination, period, denominator, and
unit. Equality is coordinatewise. An empty coordinate means unresolved
identity, not a wildcard.

An evidential atom is

\[
e=(i,[q^-,q^+],E,s), \qquad 0\le q^-\le q^+,
\]

where (E\) is a nonempty set of immutable evidence identifiers and (s\) is an
epistemic status. Status distinguishes at least:

- observed or reported measurement;
- source-reported calculation or statistic;
- TEM/ED pipeline-derived calculation;
- structural or contextual observation;
- prior or context; and
- unresolved summary.

These statuses are not interchangeable. A source summary is not promoted to a
direct measurement merely because it contains a scientific conclusion.

The carrier is a finite identity-indexed interval measure

\[
\mu=\sum_k [q_k^-,q_k^+]\,\delta_{i_k}^{E_k,s_k}.
\]

Atoms with different identities remain distinct even when their scalar values
are equal.

## 2. Transformation certificates

A primitive transformation certificate is

\[
c=(i_{in},i_{out},[y^-,y^+],E_c,b), \qquad 0\le y^-\le y^+,
\]

where (E_c\) is the supporting evidence set and (b\) is the explicit claim
boundary. The partial push-forward is

\[
\Phi_c(i_{in},[q^-,q^+],E,C)
=
(i_{out},[q^-y^-,q^+y^+],E\cup E_c,C\mathbin{\|}c).
\]

The operation is undefined when the claim identity does not exactly match the
certificate input, the certificate is blocked, or its evidence set is empty.
Undefined operations emit a blocker and no numerical claim.

A certificate authorizes a transformation. It does not assert that a shipment,
consumption event, or exposure occurred. A quantitative claim additionally
requires a compatible base measure or an explicitly labelled model-derived
input.

Certificates compose only when adjacent endpoint identities match. For a
well-typed chain (C=(c_1,\ldots,c_k)\), the composite yield interval is

\[
\left[\prod_{r=1}^k y_r^-,\prod_{r=1}^k y_r^+\right].
\]

## 3. Admissible-claim closure

Given base atoms (B\) and certificates (K\), define
\(\mathcal A(B,K)\) as the least set closed under:

1. retention of every base atom with its original status and evidence witness;
2. addition only within one complete identity;
3. application of a matching certified push-forward;
4. monotone interval multiplication by a compatible dimensionless statistic
   with an explicit output identity;
5. certified marginal interval construction; and
6. scalar projection only after the identity-indexed claim and witness exist.

Every output is

\[
Q=(i_Q,[L_Q,U_Q],D_Q,C_Q,B_Q,s_Q),
\]

where (D_Q\) is the evidence dependency set, (C_Q\) the ordered certificate
chain, (B_Q\) the unresolved blockers, and (s_Q\) the output epistemic status.
The operator returns

\[
\mathcal T_K(B,q)=
\begin{cases}
Q, & Q\in\mathcal A(B,K),\\
\bot(B_Q), & \text{otherwise.}
\end{cases}
\]

Refusal is therefore part of the mathematical output, not an interface warning.

## 4. Certified marginal-flow claims

For nonnegative row total (R_i\), column total (C_j\), and grand total (T\),
the sharp marginal interval for a route cell is

\[
L_{ij}=\max(0,R_i+C_j-T), \qquad
U_{ij}=\min(R_i,C_j).
\]

Let a route certificate be \(r=(c,i,E_r,b)\), where \(c\) is a certificate
identifier, \(i\in I\) is one complete route signature, \(E_r\ne\varnothing\)
is its immutable evidence set, and \(b\) states the certificate's claim
boundary. TEM-FLOW emits \([L_{ij},U_{ij}]\) only when the submitted certificate
signature equals the requested route identity exactly. A nonempty certificate
identifier alone is insufficient. A difference in product form, material,
origin, destination, period, denominator, unit, or any other signature field
returns an identity-mismatch blocker.

The interval operator does not select a midpoint and does not treat feasibility
or historical route presence as proof of an observed shipment. Without an
exactly matching route certificate the result is a blocker.

### 4.1 Source-transient-destination path closure

Let (x_{ohz}\ge 0) be a three-stage path tensor with source margins (S_o),
transient/checkpoint margins (H_h), destination margins (D_z), and total
(T). TEM-FLOW's three-margin path closure is

\[
L_{ohz}=\max(0,S_o+H_h+D_z-2T),\qquad
U_{ohz}=\min(S_o,H_h,D_z).
\]

This is a closed-form interval operation, not an entropy, gravity, Bayesian,
or machine-learning point allocation. The requested identity must contain all
three node labels and must equal a `PathCertificate` signature exactly. An
earlier path observation may certify identity support but does not assert
positive mass in a later period. Previously unseen paths therefore return a
blocker rather than an invented zero or positive flow.

### 4.2 Node CPC and contaminant propagation

For a certified allocated edible-product mass interval (M=[M^-,M^+]), edible
yield (e=[e^-,e^+]\subseteq[0,1]), and compatible consumer-population interval
(P=[P^-,P^+]) with (P^->0), node CPC is

\[
\operatorname{CPC}(M,e,P)=
\left[\frac{M^-e^-}{P^+},\frac{M^+e^+}{P^-}\right].
\]

The operation is defined only through a `CPCAllocationCertificate` that names
the exact mass identity, population identity, edible conversion, destination,
period, denominator, and output unit. The population input additionally requires
a `PopulationProjectionCertificate` naming the current projection scenario,
projection as-of date, exact node, and geographic level (`country`, `city`,
`town`, or `village`). A generic national population cannot stand in for a city,
town, or village node. Source or checkpoint throughput is not consumer intake
unless a matching consuming population is separately certified.

If an explicit CPC interval is already reported or calculated for the exact
node, commodity/product, period, denominator, and unit, a matching
`DirectCPCCertificate` gives that claim precedence and no population
recalculation is performed. An untyped or geographically unmatched CPC value is
not eligible for this precedence rule.

TEM-FLOW does **not** require CPC, mass, population-projection, and chemistry
records to be contemporaneous. It distinguishes the flow/exposure reference
date (D) from an evidence-availability cutoff (K). Within each evidence stream,
the selected record is the latest identity-compatible record eligible by (K):

\[
r_s^*(K)=\arg\max_{r\in\mathcal R_s}
\{t_{evidence}(r):t_{evidence}(r)\le K,\ I(r)\sim I_{required}\}.
\]

The CPC stream is resolved first from the latest certified explicit node CPC;
when absent, it is derived from the latest eligible compatible node-mass
evidence and the official population projection applicable to the node and
target period. Chemistry is selected independently as the latest compatible
food/tissue/analyte record. Their dates may differ and are retained in the
calculation certificate. If a historical knowledge-state analysis is required,
(K) is set explicitly; otherwise it represents the latest evidence available
at run time. Projection vintage, projection target period, mass date, CPC date,
and chemistry date are separate provenance fields.

That rule defines a current snapshot or a historical **knowledge-state** run. A
historical **trend reconstruction** uses a different, explicit operator. Let
\(d\) be a manager-supplied date or a date from a selected anchor stream, and
let \(I_r=[a_r,b_r]\) be the temporal support of record \(r\). TEM-FLOW does not
invent a day for an annual or multi-year record. It defines the interval gap

\[
g(d,r)=
\begin{cases}
0,& I_d\cap I_r\neq\varnothing,\\
a_d-b_r,& b_r<a_d,\\
a_r-b_d,& a_r>b_d,
\end{cases}
\]

and selects independently in each predictor stream \(s\)

\[
r_s^*(d)=\arg\min_{r\in\mathcal E_s:\,\sigma(r)\sim\sigma^*_s}
\left(g(d,r),\ |\operatorname{mid}(I_r)-\operatorname{mid}(I_d)|,\
\mathbf 1[a_r>b_d]\right).
\]

Thus the closest compatible record may precede or follow the target date; the
earlier record wins an exact tie. A manager may instead request `past_only`, or
set a maximum admissible gap \(G\), in which case records with \(g(d,r)>G\) are
refused. Every selected interval, direction, and gap is retained in the point
certificate.

At each trend date, nearest certified direct CPC has precedence. Otherwise,
nearest compatible mass and population intervals yield

\[
\mathrm{CPC}_d=\left[\frac{M_L(d)y_L}{P_U(d)},
\frac{M_U(d)y_U}{P_L(d)}\right].
\]

Nearest compatible chemistry and body-weight records then yield EDI, and the
nearest compatible reference dose yields THQ. Consequently, product mass and
CPC trends remain available without chemistry; EDI/THQ points appear only at
dates for which their independently matched certified predictors are available.

CPC closure is independent of the chemistry stream. When CPC evidence or its
mass/population derivation is admissible, the CPC claim is emitted even if no
chemistry record exists. Chemistry absence blocks only the downstream EDI, HQ,
and alarm claims.

For compatible contaminant concentration (C=[C^-,C^+]), body weight
(W=[W^-,W^+]) with (W^->0), reference dose (R=[R^-,R^+]) with (R^->0),
and (d>0) days in the CPC period, the certified exposure push-forward is

\[
\operatorname{EDI}=
\left[\frac{\operatorname{CPC}^-C^-}{dW^+},
      \frac{\operatorname{CPC}^+C^+}{dW^-}\right],\qquad
\operatorname{HQ}=
\left[\frac{\operatorname{EDI}^-}{R^+},
      \frac{\operatorname{EDI}^+}{R^-}\right].
\]

An `ExposureCertificate` must match each CPC, food/tissue chemistry, body-weight
population, reference-dose analyte, and destination claim to its own declared
identity and evidence date. It does not require those dates to be equal. Health
index aggregation is permitted only among such compatible analyte-specific HQ
claims. The conventional EDI/HQ endpoints are not claimed as novel; TEM-FLOW's
contribution is the path-specific typed enclosure, dependency witness, and
refusal of unmatched propagation.

## 5. Provenance invariants

The canonical ledger enforces the following invariants:

1. every TEM record has a unique identifier;
2. every record retains its parent source identifier and immutable payload hash;
3. direct measurements remain distinguishable from reported statistics,
   pipeline calculations, topology, and priors;
4. every certificate has a content-derived proof digest;
5. every generated output names its release and dependency records; and
6. corrections create a new versioned record rather than rewriting the frozen
   ED-FLOW source.

## 6. Core properties

### Identity non-amalgamation

Claims with different identities cannot be added or substituted without a
certificate path. Equal scalar totals do not erase the identity distinction.

### Conservation under certified transport

A certified transport with yield ([1,1]\) preserves both mass bounds. An
identity-scope certificate without an input mass authorizes no quantity.

### Associative certificate chains

Well-typed certificate-chain composition is associative because its witness is
ordered tuple concatenation and its nonnegative yield bounds multiply
associatively. Composition is generally not commutative.

### Conservative scalar projection

On fully certified compatible inputs, scalar projection reproduces the same
nonnegative interval arithmetic as ED-FLOW. The converse is false: equal scalar
projections need not represent the same evidential claim.

### Sound refusal

No identity-changing numerical claim enters the admissible closure without a
matching certificate. This is a syntactic safety guarantee, not proof that every
submitted certificate is scientifically true; the certificate evidence remains
subject to audit.

### Conservative path and exposure enclosure

The three-stage path bounds enclose every nonnegative tensor consistent with
the supplied one-way margins. CPC, EDI, and HQ endpoint rules enclose every
combination of their nonnegative certified input intervals because the
numerators are monotone increasing and the positive divisors monotone
decreasing.

Formal statements and proofs are supplied in
`TEMFLOW_FORMAL_PROOFS_V0_3.md`.

## 7. Ziway evidence derivation

The source ledger retains 488.9 t/year total production and an Addis share
interval of 0.4067293925-0.4147064839 after the documented 485.0/488.9
denominator correction. Certificate
`TEM-CERT-ZIWAY-ADDIS-DENOMINATOR-2018` authorizes the conversion from marketed-
channel share to total-source share:

\[
[488.9,488.9]\times[0.4067293925,0.4147064839]
=[198.849999993,202.749999979]\ \mathrm{t/year}.
\]

This is a pipeline-derived interval, not an observed route mass. Its dependency
witness retains both source records and the denominator certificate. No
allocation of the remaining production among named markets is authorized.

## 8. Relationship to ED-FLOW

ED-FLOW defines feasible scalar-route sets and may select a KL-minimum point.
TEM-FLOW defines a typed partial derivation system producing intervals, exact
claims, or blockers. TEM-FLOW may accept an ED-FLOW or other model output as a
labelled upstream atom, but it does not use ED-FLOW's optimization equations as
its defining algorithm.

The FAO holdout confirms that ED-FLOW is the stronger point estimator in the
tested network. TEM-FLOW's empirical contribution is selective coverage,
identity safety, and calibrated refusal—not point-accuracy superiority. Its
three-stage closure addresses the same operational chain—source,
transient/checkpoint, destination, node CPC, and food-contaminant exposure—while
replacing ED-FLOW's selected scalar allocation with certificate-gated intervals
and explicit blockers.

## 9. Validation boundary

Version 0.3 is supported by analytic proofs, executable proof obligations,
corpus-grounded parity and negative controls, a 2019-2024 external-release
holdout, three point baselines, controlled identity-corruption tests, component
ablations, and a separate Karg et al. primary field-flow validation. The FAO
release is administratively related to trade data used elsewhere in ED-FLOW;
the Karg dataset is genuinely independent of both the frozen ED-FLOW ledger and
the FAO holdout. It independently validates three-stage allocation and refusal,
not CPC or hazard, because compatible destination-population and laboratory
chemistry inputs are absent.
