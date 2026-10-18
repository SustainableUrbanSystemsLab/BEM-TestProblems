# SPDX-License-Identifier: MIT
"""Optional solver adapters for a documented rerun, not recovered paper trajectories.

Callbacks use physical coordinates. The outer experiment must record starts,
true simulator calls and failures independently. Missing original implementations
are reported explicitly; this module never substitutes another named algorithm.
"""

from copy import deepcopy
from importlib import import_module, util
from importlib.metadata import PackageNotFoundError, version
from math import inf, isfinite, nextafter
from threading import RLock

_RANDOM_LOCK = RLock()
_PAPER = "https://doi.org/10.1016/j.enbuild.2019.01.048"
_NLOPT = "https://nlopt.readthedocs.io/en/latest/NLopt_Python_Reference/"
_CMA = "https://cma-es.github.io/apidocs-pycma/cma.evolution_strategy.CMAEvolutionStrategy.html"
_PYBOBYQA = "https://numericalalgorithmsgroup.github.io/pybobyqa/build/html/userguide.html"

SOLVER_ORDER = (
    "sga", "sga_unt", "es", "es_unt", "pso", "pso_unt", "fips", "fips_unt",
    "silvereye", "galapagos_ga", "galapagos_sa", "direct", "crs2", "sbplex",
    "cma_es", "rbfopt", "bobyqa", "pybobyqa",
)

_DEFINITIONS = {}
for _name in SOLVER_ORDER:
    _DEFINITIONS[_name] = {
        "name": _name,
        "paper_method": _name not in {"bobyqa", "pybobyqa"},
        "implemented": False,
        "dependency": None,
        "source": _PAPER,
        "settings": {},
        "skip_reason": "The paper's original implementation has no faithful Python adapter here.",
    }
for _name in SOLVER_ORDER[:8]:
    _DEFINITIONS[_name]["skip_reason"] = (
        "The paper uses BB-O through FrOG, including dimension-specific tuned settings. "
        "The original operators and tuning have not been ported and validated; "
        "a generic GA/ES/PSO implementation would not reproduce this method."
    )
_DEFINITIONS["silvereye"]["skip_reason"] = (
    "The original Silvereye PSO plugin implementation/defaults are not available "
    "as a validated headless Python adapter; generic PSO is not substituted."
)
for _name in ("galapagos_ga", "galapagos_sa"):
    _DEFINITIONS[_name]["skip_reason"] = (
        "The paper uses proprietary Galapagos implementations whose complete operators "
        "are not specified. A generic GA or annealer is not substituted."
    )
_DEFINITIONS["rbfopt"].update({
    "dependency": "rbfopt",
    "source": "https://github.com/coin-or/rbfopt",
    "settings": {"paper_thresh_unlimited_refinement": 0.6},
    "skip_reason": (
        "The paper's RBFOpt/Opossum configuration requires external mathematical-programming "
        "solvers and historical defaults that are not provisioned/validated here. "
        "A solver-free MSRSM variant would be a different method and is not substituted."
    ),
})
for _name, _algorithm in (("direct", "GN_DIRECT"), ("crs2", "GN_CRS2_LM"),
                          ("sbplex", "LN_SBPLX")):
    _DEFINITIONS[_name].update({
        "implemented": True, "dependency": "nlopt", "source": _NLOPT,
        "settings": {"algorithm": _algorithm, "coordinates": "physical",
                     "stopping": "explicit evaluation budget; other NLopt defaults",
                     "initialization": "box midpoint" if _name == "direct" else "supplied x0"},
        "skip_reason": None,
        "fidelity": "Same NLopt algorithm family; exact 2019 Goat defaults/build are unverified.",
    })
_DEFINITIONS["cma_es"].update({
    "implemented": True, "dependency": "cma", "source": _CMA, "skip_reason": None,
    "settings": {"coordinates": "unit box", "sigma0": 0.3,
                 "initialization": "supplied x0 as the initial mean",
                 "population": "pycma default", "restarts": 0,
                 "randomness": "private NumPy RandomState seeded by supplied seed"},
    "fidelity": (
        "Original author's Python implementation family; historical Opossum scaling, "
        "initial sigma and package version are unverified. Sigma0=0.3 in a unit box "
        "is an explicit rerun setting, not an asserted paper setting."
    ),
})
_DEFINITIONS["bobyqa"].update({
    "implemented": True, "dependency": "pdfo", "source": "https://www.pdfo.net/",
    "skip_reason": None,
    "settings": {"method": "bobyqa", "scale": True, "quiet": True, "honour_x0": True,
                 "endpoint_roundoff": "normalize at most one binary64 ULP outside finite bounds"},
    "fidelity": "Added PDFO BOBYQA comparison; not one of the paper's 16 methods.",
})
_DEFINITIONS["pybobyqa"].update({
    "implemented": True, "dependency": "pybobyqa", "source": _PYBOBYQA,
    "skip_reason": None,
    "settings": {"scaling_within_bounds": True, "seek_global_minimum": False,
                 "objfun_has_noise": False, "restarts.use_restarts": False,
                 "endpoint_roundoff": "normalize at most one binary64 ULP outside finite bounds"},
    "fidelity": "Added Py-BOBYQA comparison; not one of the paper's 16 methods.",
})


def _canonical_name(name):
    key = str(name).strip().lower().replace("-", "_")
    aliases = {"cmaes": "cma_es", "subplex": "sbplex", "py_bobyqa": "pybobyqa",
               "pdfo_bobyqa": "bobyqa"}
    key = aliases.get(key, key)
    if key not in _DEFINITIONS:
        raise ValueError(f"Unknown solver {name!r}; choose from {', '.join(SOLVER_ORDER)}")
    return key


def _available(module):
    try:
        return util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _runtime_incompatibility(name):
    if name == "bobyqa":
        try:
            if version("pdfo") == "2.2.0" and int(version("numpy").split(".")[0]) >= 2:
                return "PDFO 2.2.0 requires a NumPy 1.x compatible environment; NumPy 2.x has an incompatible native ABI."
        except PackageNotFoundError:
            pass
    return None


def solver_metadata(name=None):
    """Return JSON-ready metadata in experiment order, including honest skips.

    ``available`` checks package presence only; actual import/ABI failures are
    reported by ``solve_solver``. No optimizer package is imported by inspection.
    """
    if name is None:
        return [solver_metadata(item) for item in SOLVER_ORDER]
    key = _canonical_name(name)
    result = deepcopy(_DEFINITIONS[key])
    result["available"] = result["implemented"] and _available(result["dependency"])
    if result["implemented"] and not result["available"]:
        result["skip_reason"] = f"Optional package {result['dependency']!r} is not installed."
    incompatibility = _runtime_incompatibility(key)
    if incompatibility:
        result["available"] = False
        result["skip_reason"] = incompatibility
    return result


class _BudgetExceeded(Exception):
    pass


class _ObservedObjective:
    def __init__(self, objective, bounds, budget):
        self.objective, self.bounds, self.budget = objective, bounds, budget
        self.nfev, self.best_x, self.best_fun = 0, None, None

    def __call__(self, x):
        if self.nfev >= self.budget:
            raise _BudgetExceeded("Objective evaluation budget exhausted")
        physical = tuple(float(v) for v in x)
        if len(physical) != len(self.bounds) or any(
            not isfinite(v) or not lower <= v <= upper
            for v, (lower, upper) in zip(physical, self.bounds, strict=True)
        ):
            raise ValueError("The solver requested a nonfinite or out-of-bounds design")
        self.nfev += 1
        value = float(self.objective(physical))
        if not isfinite(value):
            raise ValueError("The objective returned a nonfinite value")
        if self.best_fun is None or value < self.best_fun:
            self.best_x, self.best_fun = physical, value
        return value


def _inputs(x0, bounds, max_evaluations, seed):
    if isinstance(max_evaluations, bool) or not isinstance(max_evaluations, int):
        raise ValueError("max_evaluations must be a positive integer")
    if max_evaluations <= 0:
        raise ValueError("max_evaluations must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    box = tuple(tuple(float(v) for v in pair) for pair in bounds)
    start = tuple(float(v) for v in x0)
    if not box or any(len(pair) != 2 for pair in box) or len(start) != len(box):
        raise ValueError("x0 and bounds must have the same nonzero dimension")
    if any(not isfinite(a) or not isfinite(b) or a >= b for a, b in box):
        raise ValueError("Use finite bounds with lower < upper; remove fixed coordinates")
    if any(not isfinite(v) or not a <= v <= b for v, (a, b) in zip(start, box)):
        raise ValueError("x0 must be finite and inside the box")
    return start, box


def _nlopt(module, observed, start, bounds, budget, seed, algorithm):
    optimizer = module.opt(getattr(module, algorithm), len(start))
    optimizer.set_lower_bounds([a for a, _ in bounds])
    optimizer.set_upper_bounds([b for _, b in bounds])
    optimizer.set_maxeval(budget)
    failure = None

    def callback(x, _grad):
        nonlocal failure
        if failure is not None:
            optimizer.force_stop()
            return float("nan")
        try:
            return observed(x)
        except BaseException as exc:
            # Explicitly stop the native optimizer, then re-raise after it
            # unwinds. NaN is an invalid callback sentinel, never an observation.
            failure = exc
            optimizer.force_stop()
            return float("nan")

    optimizer.set_min_objective(callback)
    with _RANDOM_LOCK:  # NLopt's RNG is process-global.
        module.srand(seed)
        try:
            optimizer.optimize(start)
        except module.ForcedStop:
            if failure is None:
                raise
        except module.RoundoffLimited:
            if failure is not None:
                raise failure
            return "roundoff", False, "NLopt stopped because roundoff limited progress", -4
    if failure is not None:
        raise failure
    code = int(optimizer.last_optimize_result())
    return ("budget" if code == 5 else "terminated", code in {1, 2, 3, 4},
            f"NLopt termination code {code}", code)


def _cma(module, np, observed, start, bounds, budget, seed):
    lower, upper = np.array([a for a, _ in bounds]), np.array([b for _, b in bounds])
    width = upper - lower
    rng = np.random.RandomState(seed)
    strategy = module.CMAEvolutionStrategy((np.array(start) - lower) / width, 0.3, {
        "bounds": [0.0, 1.0], "randn": rng.randn, "seed": 1,
        "maxfevals": budget, "verbose": -9, "verb_log": 0,
    })
    while not strategy.stop():
        samples = strategy.ask()
        values = []
        for sample in samples:
            # pycma enforces unit-box bounds; clipping here removes only
            # floating-point overshoot from mapping endpoints to physical units.
            values.append(observed(np.clip(lower + width * sample, lower, upper)))
        strategy.tell(samples, values)
    stop = {str(k): str(v) for k, v in strategy.stop().items()}
    status = "budget" if "maxfevals" in stop else "terminated"
    return status, status != "budget", f"pycma stopped: {stop}", stop


def _bounded_physical_point(x, bounds):
    """Remove only one-ULP endpoint overshoot from affine solver unscaling.

    PDFO 2.2.0 and Py-BOBYQA 1.5.0 can map an endpoint to the adjacent float outside
    its physical bound. Normalize that neighbor before validation/recording;
    all larger violations, nonfinite values, and wrong dimensions stay invalid.
    """
    physical = tuple(float(value) for value in x)
    if len(physical) != len(bounds):
        raise ValueError("The solver requested a nonfinite or out-of-bounds design")
    corrected = []
    for value, (lower, upper) in zip(physical, bounds, strict=True):
        if isfinite(value) and value == nextafter(lower, -inf):
            value = lower
        elif isfinite(value) and value == nextafter(upper, inf):
            value = upper
        if not isfinite(value) or not lower <= value <= upper:
            raise ValueError("The solver requested a nonfinite or out-of-bounds design")
        corrected.append(value)
    return tuple(corrected)


def _pdfo(module, observed, start, bounds, budget):
    if budget < len(start) + 2:
        raise ValueError("PDFO BOBYQA needs at least dimension + 2 evaluations")
    failure = None

    def callback(x):
        nonlocal failure
        if failure is not None:
            return float("nan")
        try:
            return observed(_bounded_physical_point(x, bounds))
        except BaseException as exc:
            # Python exceptions must not cross PDFO's compiled Fortran callback.
            failure = exc
            return float("nan")

    result = module.pdfo(callback, start, bounds=bounds, method="bobyqa", options={
        "maxfev": budget, "npt": min(2 * len(start) + 1, budget),
        "scale": True, "quiet": True, "honour_x0": True,
    })
    if failure is not None:
        raise failure
    return ("budget" if int(result.status) == 3 else "terminated",
            bool(result.success), str(result.message), int(result.status))


def _pybobyqa(module, np, observed, start, bounds, budget, seed):
    if budget < len(start) + 1:
        raise ValueError("Py-BOBYQA needs at least dimension + 1 evaluations")
    with _RANDOM_LOCK:
        previous_state = np.random.get_state()
        np.random.seed(seed)
        try:
            result = module.solve(
                lambda x: observed(_bounded_physical_point(x, bounds)), np.array(start),
                bounds=(np.array([a for a, _ in bounds]), np.array([b for _, b in bounds])),
                maxfun=budget, npt=min(2 * len(start) + 1, budget),
                scaling_within_bounds=True, seek_global_minimum=False,
                objfun_has_noise=False, do_logging=False, print_progress=False,
                user_params={"restarts.use_restarts": False},
            )
        finally:
            np.random.set_state(previous_state)
    return ("budget" if result.flag == result.EXIT_MAXFUN_WARNING else "terminated",
            result.flag == result.EXIT_SUCCESS, str(result.msg), int(result.flag))


def solve_solver(name, objective, x0, bounds, max_evaluations, seed):
    """Run an optional solver and return its best *observed* physical design.

    Missing implementations/dependencies return ``status='skipped'`` with zero
    calls. Objective failures, including the caller's own budget exception,
    propagate unchanged. An independent hard objective-call cap never creates a
    fabricated penalty. Native termination is not a claim of global optimality.
    This function performs no installation, simulation setup, or network access.
    """
    key = _canonical_name(name)
    start, box = _inputs(x0, bounds, max_evaluations, seed)
    metadata = solver_metadata(key)
    result = {"solver": key, "x": None, "fun": None, "nfev": 0,
              "status": "skipped", "success": False, "message": metadata["skip_reason"],
              "dependency": metadata["dependency"], "dependency_version": None,
              "settings": deepcopy(metadata["settings"]), "seed": seed}
    if not metadata["implemented"]:
        return result
    if _runtime_incompatibility(key):
        return result
    try:
        module = import_module(metadata["dependency"])
        np = import_module("numpy")
    except ImportError as exc:
        result["message"] = f"Cannot import optional solver dependency: {exc}"
        return result
    result["dependency_version"] = str(getattr(module, "__version__", "unknown"))
    observed = _ObservedObjective(objective, box, max_evaluations)
    try:
        if key in {"direct", "crs2", "sbplex"}:
            if key == "direct":
                start = tuple((a + b) / 2 for a, b in box)
            outcome = _nlopt(module, observed, start, box, max_evaluations, seed,
                             metadata["settings"]["algorithm"])
        elif key == "cma_es":
            outcome = _cma(module, np, observed, start, box, max_evaluations, seed)
        elif key == "bobyqa":
            outcome = _pdfo(module, observed, start, box, max_evaluations)
        else:
            outcome = _pybobyqa(module, np, observed, start, box, max_evaluations, seed)
        status, success, message, native_status = outcome
    except _BudgetExceeded:
        status, success, message, native_status = "budget", False, "Hard evaluation budget reached", None
    result.update({"x": list(observed.best_x) if observed.best_x is not None else None,
                   "fun": observed.best_fun, "nfev": observed.nfev,
                   "status": status, "success": success, "message": message,
                   "native_status": native_status})
    return result
