"""The documented entry points work without installing or launching EnergyPlus."""

import pytest

import bem_testproblems as bem
from bem_testproblems.energyplus import EnergyPlusRunner
from bem_testproblems.evaluation import make_objective
from bem_testproblems.optimize import solve, solve_bobyqa


def test_documented_lazy_exports_are_the_public_implementations():
    assert bem.EnergyPlusRunner is EnergyPlusRunner
    assert bem.make_objective is make_objective
    assert bem.solve_bobyqa is solve_bobyqa
    assert bem.solve is solve
    with pytest.raises(AttributeError, match="unknown_entry_point"):
        getattr(bem, "unknown_entry_point")


def test_problem_lookup_exposes_the_solver_contract():
    problem = bem.get_problem(1)
    assert len(problem.bounds) == len(problem.midpoint) == problem.dimension
    assert problem.validate(problem.midpoint)
    with pytest.raises(ValueError):
        bem.get_problem(7)


def test_problem_provenance_identifies_the_definition_and_cannot_be_changed_by_the_caller():
    problem = bem.get_problem(1)
    provenance = problem.provenance
    assert provenance["upstream_commit"] == "54736a6b899a488222ad3184f306c1f401daf4f9"
    assert provenance["paper_doi"] == "10.1016/j.enbuild.2019.01.048"
    assert provenance["paper_equation"] == 5
    provenance["upstream_commit"] = "caller-edited"
    assert problem.provenance["upstream_commit"] != "caller-edited"
