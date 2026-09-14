# TEM-FLOW v1.1 Evidence-Resolved Reconstruction

## Claim boundary and mathematical contribution

Evidence-Resolved Reconstruction (ERR) is a multi-domain mass-flow operator
for systems in which physical totals, bounds and route identities are only
partly observed. Its contribution is not linear programming, convex
optimization, mass balance, provenance, or interval analysis separately. The
new object is the joint evidence-resolution construction: a full latent
feasible polytope, a certificate-indexed unresolved-mass envelope, its optimum
face, two levels of sharp coordinate bounds, and a typed result that separates
physical feasibility from permission to make a named claim.

Absence of a certificate is never encoded as physical zero. Domain-specific
quantities such as consumption, exposure, inventory, energy or financial
metrics may consume a compatible ERR result, but they are not part of the ERR
estimand.

## 1. Full physical feasible set

Let `J={1,...,m}` index candidate flows. Each coordinate has a versioned
identity signature, such as material, form, origin, checkpoint, destination,
period and unit. Evidence `E` defines the non-empty compact polytope

```
F(E) = {x in R^m: x >= 0, A x = b, G x <= h, l <= x <= u}.          (1)
```

The matrices may encode conservation, measured margins, capacity, conversion,
loss and other auditable physical restrictions. Every candidate coordinate
remains in (1), including coordinates whose identity is not certified.

Let `a_K in {0,1}^m` be the active identity-certificate mask. `a_Kj=1`
authorizes a named model-derived report for coordinate `j`; it does not assert
positive observed flow. `a_Kj=0` leaves `x_j` latent in all constraints.

## 2. Unresolved-mass envelope

For declared nonnegative weights `w in R_+^m`, define

```
c_K = w * (1-a_K),                                                 (2)
rho^-_K = min{x in F(E)} <c_K,x>,
rho^+_K = max{x in F(E)} <c_K,x>.                                 (3)
```

The interval `[rho^-_K,rho^+_K]` is sharp. With unit weights it is the complete
feasible range of mass carried on uncertified identities. For a known common
total `T>0`, the evidence-resolution ratio is

```
eta_K = [1-rho^+_K/T, 1-rho^-_K/T].                               (4)
```

The right endpoint of (4) is a best feasible case, not hidden truth. If weights
are not all one, the score remains valid but is not labelled a physical mass
fraction. Zero weights are allowed for deliberately excluded coordinates;
the zero-equivalence theorem requires positive weight on every uncertified
coordinate.

The minimum-unresolved optimum face is

```
F*_K = {x in F(E): <c_K,x> = rho^-_K}.                             (5)
```

`F*_K` is a transparent decision layer: all its members make the least
unsupported identity commitment permitted by the physical evidence.

## 3. Neutral and optimum-face coordinate bounds

For every coordinate, including latent coordinates retained for diagnosis,

```
[L^0_j,U^0_j] = [min{x in F(E)} x_j, max{x in F(E)} x_j],           (6)
[L*_j,U*_j]  = [min{x in F*_K} x_j, max{x in F*_K} x_j].           (7)
```

Both are sharp. Equation (6) is evidence-neutral; equation (7) is conditional
on minimum unresolved specificity. A named query for an uncertified coordinate
returns an identity blocker, while the integrated result retains its numerical
bounds so reviewers can verify conservation and see that it was not zero-filled.

Only `rho^-` and `rho^+` are antitone under certificate refinement. Individual
coordinate widths `U*_j-L*_j` can shrink, stay fixed, or increase because the
objective face itself changes. TEM-FLOW does not claim route-width monotonicity.

## 4. Optional operational projection

The set-valued result is the default. Only if an operational table is explicitly
requested, and a strictly positive versioned prior `p` is supplied, TEM-FLOW
computes

```
x^dagger_K = argmin{x in F*_K} 1/2 sum_j (x_j-p_j)^2/p_j.           (8)
```

Strict convexity makes (8) unique. It is a reproducible working allocation,
not an observation, posterior mean or extra physical restriction. A legacy
ED-FLOW allocation may be supplied as the declared prior or used in a separately
versioned projection generator; it has no role in defining (1)-(7).

## 5. Integrated result contract

The software returns one serializable object containing:

- both unresolved-envelope endpoints and, when valid, the ratio interval;
- the explicit coefficients, optimum and a feasible witness for `F*_K`;
- neutral and optimum-face sharp bounds for every coordinate;
- named-report status, certificate IDs, global evidence IDs and blockers;
- the optional `x^dagger_K` and mandatory prior version when requested; and
- solver statuses, equality/inequality/bound residuals and declared tolerances.

If (1) is infeasible or unbounded, the operator fails explicitly rather than
returning a scientific result. The current continental reviewer registry is a
topological/evidence catalogue and does not by itself contain a complete
`A,b,G,h,l,u` system for every selection. ERR therefore runs only when that
physical constraint problem is supplied; the software never manufactures it
from map lines.

## 6. Downstream use

ERR is agnostic to the material and application domain. A certified node or
route interval can be transformed by a downstream model when units, period,
product identity and denominator are compatible. For example, an application
may divide a node mass interval by a corresponding population to compute a
consumption interval, then combine that result with independently dated
chemistry under an explicit temporal matching rule. These are optional typed
consumers. They do not alter the mass-flow reconstruction or certify an
otherwise unresolved coordinate.
