# TEM-FLOW v1.1 ERR: eight formal results

Assume `F` is a non-empty compact convex subset of `R_+^m`, `a_K` is a binary
certificate mask and `w>=0`. Write `c_K=w*(1-a_K)`, and define `rho^-`,
`rho^+` and `F*_K` as in equations (3)-(5) of the formulation.

## Result 1 — existence and the optimum face

Both `rho^-_K` and `rho^+_K` are finite and attained. `F*_K` is non-empty,
compact and convex.

**Proof.** The linear functional `<c_K,x>` is continuous, so the extreme-value
theorem gives finite attained minimum and maximum on compact `F`. The minimizer
set is `F` intersected with the closed supporting hyperplane
`<c_K,x>=rho^-_K`; it is non-empty, compact and convex. QED.

## Result 2 — zero equivalence under positive unresolved weights

If `w_j>0` for every `j` with `a_Kj=0`, then

```
rho^-_K=0  iff  there exists x in F with x_j=0 for every uncertified j.
```

**Proof.** Every summand `w_j(1-a_Kj)x_j` is nonnegative. With positive weights
on all uncertified coordinates, their sum is zero exactly when all those
coordinates are zero. The attained minimizer from Result 1 supplies the
required feasible point in the forward direction. QED.

If any unresolved weight is zero, only the forward score definition remains:
zero may hide mass on zero-weight coordinates. The implementation accepts such
weights but does not apply the equivalence or mass-fraction interpretation.

## Result 3 — certificate antitonicity of both endpoints

If `K` is refined to `K'` with `a_K<=a_K'` coordinatewise, then

```
rho^-_{K'} <= rho^-_K  and  rho^+_{K'} <= rho^+_K.
```

**Proof.** Because `x>=0` and `w>=0`, `c_K'<=c_K` implies
`<c_K',x><=<c_K,x>` for every `x in F`. Taking minima gives the first
inequality; taking maxima gives the second. QED.

The theorem is scalar. It does not imply monotonicity of coordinate interval
widths on the changing faces `F*_K`.

## Result 4 — positive homogeneity of both endpoints

For `lambda>=0` and `lambda F={lambda x:x in F}`,

```
rho^-_K(lambda F)=lambda rho^-_K(F),
rho^+_K(lambda F)=lambda rho^+_K(F).
```

**Proof.** Substitute `y=lambda x`. The linear objective becomes
`<c_K,y>=lambda<c_K,x>`, and both extrema factor by `lambda`. At `lambda=0`
both sides are zero. QED.

## Result 5 — Cartesian additivity of both endpoints

For independent systems with product set `F_1 x F_2` and concatenated costs,

```
rho^-_{1+2}=rho^-_1+rho^-_2,
rho^+_{1+2}=rho^+_1+rho^+_2.
```

**Proof.** The objective is a separable sum. The minimum of a separable sum
over a Cartesian product is the sum of the two minima, and the same identity
holds for maxima. Attainment follows from Result 1. QED.

## Result 6 — uniqueness of the requested operational projection

For a supplied `p in R_{++}^m`, equation (8) has exactly one minimizer on
`F*_K`.

**Proof.** Its Hessian is `diag(1/p_j)`, which is positive definite, so the
objective is strictly convex. Compactness gives existence and strict convexity
on a convex feasible set gives uniqueness. QED.

This result is conditional: no operational point is generated unless a point
table and a prior version are explicitly requested.

## Result 7 — sharp nesting

For every coordinate,

```
L^0_j <= L*_j <= U*_j <= U^0_j,
```

and, when requested, `L*_j<=x^dagger_Kj<=U*_j`. Every bound endpoint is
attainable in its defining set.

**Proof.** `F*_K` is a non-empty subset of `F`, so restricting the feasible set
cannot lower a minimum or raise a maximum. The operational point lies in
`F*_K`. Compactness and continuity make all extrema attainable. QED.

## Result 8 — limiting cases

With unit weights and a common total `sum_j x_j=T` for every `x in F`:

1. If all coordinates are certified, `rho^-=rho^+=0`, `eta=[1,1]` and
   `F*_K=F`.
2. If no coordinates are certified, `rho^-=rho^+=T`, `eta=[0,0]`, and all
   named route queries are blocked although the latent balance problem remains
   feasible.

**Proof.** For `a_K=1`, `c_K=0`; for `a_K=0` and unit weights,
`<c_K,x>=sum_j x_j=T` throughout `F`. Substitute these constants into the
definitions. The blocker follows from the reportability domain. QED.

## Computational correspondence

The reference implementation uses sparse linear programs for the two scalar
endpoints and every sharp coordinate bound, appends the attained minimum as an
equality for `F*_K`, and uses a strictly convex constrained projection only on
request. Tests exercise all eight results, zero-weight caveats, no-false-zero
reporting, serialization, API integration and repeated projection. Randomized
stress tests separately check both antitonic endpoints; any coordinate-width
increase is logged as a permitted diagnostic rather than a failure.
