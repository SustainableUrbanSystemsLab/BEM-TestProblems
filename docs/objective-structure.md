# Objective structure and known derivatives

Each problem exposes a simulator map `s(x)` and a pure outer function:

$$F(x)=\phi(x,s(x)).$$

`simulate_outputs` performs the simulation. `objective_terms`, `outer_loss`,
`outer_derivatives` and `penalty_metadata` require no simulator. Coordinates use
physical units; `problem.parameters` records their names, units and original
paper numbering. The formulas below preserve the original C# calculation.
See [validation](validation.md) for paper/code differences and engine changes.

## Canonical simulator outputs

| Problems | Outputs used by the objective | Meaning and units |
| --- | --- | --- |
| 1–3 | `Q_h`, `Q_c`, `E_L` | Ideal-load sensible heating, sensible cooling and lighting energy, respectively; kWh over the annual run |
| 4–6, 8 | `H_1` … `H_6`, `C`, `L_N`, `L_W`, `L_E`, `L_S`, `L_I`, `V_legacy` | Heating-coil gas energy for north/west/east/south/interior/main coils; main cooling-coil electricity; zone lighting electricity; supply-fan electricity. All kWh over the annual run |
| 9–10 | `Y` | Reported **Total Source Energy / Energy Per Conditioned Building Area**, MJ/m² over the annual run |
| 13 | `Q`, `P` | District hot-water heating energy, kWh over the embedded winter design day; its daily **time-average** heating rate, kW |

Detailed outputs also include `V_return` for diagnosis; the historical loss uses
`V_legacy` twice. Office `Y` retains the tabular report's displayed precision.
Its fuel factors are already applied inside EnergyPlus (electricity 3.095,
natural gas 1.092). Replacing it with an unrounded sum of fuel meters would
change the reference definition. School `P` is not a peak demand. For a complete
24-hour design day, `Q ≈ 24 P` provides a consistency check; both original reports
remain exposed.

## Four outer functions

For problems 1–3, with area 96 m²:

$$\phi=\frac{Q_h/0.44+Q_c/0.77+3E_L}{96}.$$

The returned terms are `heating`, `cooling`, `lighting`; the objective unit is
kWh/(m² year).

For problems 4–6 and 8, with area 1104 m²:

$$\phi=\frac{\sum_{i=1}^{6}H_i+
3\left(C+5L_N+L_W+L_E+5L_S+L_I+2V_{legacy}\right)}{1104}.$$

The returned terms are `heating`, `cooling`, `lighting`, `fans`, in kWh/(m² year).
The factors 5 account for the representative north/south rooms. The duplicated
supply-fan observation is the preserved C# behavior. Problem 8 fixes paper
`x11=25°C`, `x13=12°C`; its free vector retains paper coordinates `x1`–`x10`,
`x12` and uses the same outer function.

For problems 9–10, write paper window coordinates as bottom/top pairs:

$$g_j(x)=x_{2j-1}-x_{2j}+0.5488,\quad j=1,\ldots,4,$$
$$m(x)=1+0.5\sum_{j=1}^{4}\mathbf{1}[g_j(x)\geq0],\qquad\phi=m(x)Y.$$

`objective_terms` returns `source_energy = Y` and
`window_penalty = (m-1)Y`, both MJ/m². `outer_loss` preserves the original
multiplication `m*Y`. The paper prints 0.55 m; the implementation uses 0.5488 m.
These penalties jump across known affine boundaries. Invalid simulator runs
remain explicit errors, independent of these defined window penalties.

For problem 13, let `δ=x1` be insulation thickness in m and `UA_i=x(i+1)` be
the nine radiator conductances in W/K:

$$\begin{aligned}
\phi={}&\alpha Q+12.42P+(678.3\delta-5.355)
       +0.4375\sum_{i=1}^{9}UA_i,\\
\alpha={}&\frac{2520(0.6)(0.75)}{19-(-11.5)}(0.034)
       =1.2641311475409838.
\end{aligned}$$

The returned terms are `energy`, `insulation`, `radiators`, in the historical
cost unit EUR. The component constants and annualization come from the
reference C#; paper Eq. (10) gives the additive categories.

## Derivative interface

```python
from bem_testproblems import get_problem

problem = get_problem(13)
x = problem.midpoint
d = problem.outer_derivatives(x)

names = tuple(d.output_gradient)
weights = tuple(d.output_gradient[name] for name in names)
direct = d.direct_gradient
hessian = d.output_hessian

# After obtaining outputs from one simulate_outputs call:
# s = tuple(outputs[name] for name in names)
# terms = problem.objective_terms(x, outputs)
# value = problem.outer_loss(x, outputs)
```

`output_gradient` is `∂φ/∂s` keyed by canonical output name. Its units are
`problem.objective_unit` divided by the corresponding output unit. The
`output_hessian` rows/columns follow **the insertion order of this mapping**,
obtained by `tuple(d.output_gradient)`. Use these names to assemble an output
vector; the complete simulator dictionary also contains diagnostic outputs.

`direct_gradient` is `∂φ/∂x` **holding simulator outputs fixed**, ordered like
`problem.parameters`. Its units are objective units per physical coordinate
unit. The known values are:

| Family | Output partial derivatives | Direct coordinate partial derivatives |
| --- | --- | --- |
| Simple | `Q_h: 1/(0.44*96)`, `Q_c: 1/(0.77*96)`, `E_L: 3/96` | Zero |
| Detailed | Each `H_i: 1/1104`; `C: 3/1104`; `L_N,L_S: 15/1104`; other lighting: `3/1104`; `V_legacy: 6/1104` | Zero |
| Office | `Y: m(x)` | Zero within each fixed penalty region |
| School | `Q: α`, `P: 12.42` | `(678.3, 0.4375, …, 0.4375)` |

All returned output Hessians are zero: the outer maps are affine in their
outputs. Office joint differentiability is marked false when any `|g_j| ≤ 1e-12`,
and `direct_gradient` is then `None`. This conservative numerical boundary flag
does not alter the exact `>= 0` penalty comparison. `penalty_metadata(x)` exposes
the four `g_j`, violation flags, factor and affine constraint Jacobian;
`d.penalty_jacobian` exposes the same rows, with `+1` at the bottom coordinate
and `−1` at its top coordinate.

These are outer partials, not a computed gradient of `F`. Where derivatives
exist, the chain rule additionally requires the unknown simulator Jacobian:
`∇F = ∂φ/∂x + J_s(x)ᵀ ∂φ/∂s`. No EnergyPlus sensitivities are supplied. A
structured derivative-free method can model the observable components and reuse
this known algebra, direct school cost and office boundaries. None of these
native objectives is a sum of squared misfits; the exposed observations are
energy/cost quantities. Report quantization, HVAC controls and failed evaluations
also limit smoothness assumptions about the simulator map.
