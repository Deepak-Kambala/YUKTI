"""Problem representation: variables, constraints, objective, full Model."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Sense(Enum):
    LE = "<="
    GE = ">="
    EQ = "="


class ObjSense(Enum):
    MIN = "minimize"
    MAX = "maximize"


class VarType(Enum):
    CONTINUOUS = "C"
    INTEGER = "I"
    BINARY = "B"


INF = float("inf")


@dataclass
class Variable:
    name: str
    lb: float = 0.0
    ub: float = INF
    vtype: VarType = VarType.CONTINUOUS
    obj_coeff: float = 0.0

    def is_integer(self) -> bool:
        return self.vtype in (VarType.INTEGER, VarType.BINARY)


@dataclass
class Constraint:
    name: str
    coeffs: Dict[str, float]  # var name -> coefficient
    sense: Sense
    rhs: float


@dataclass
class Model:
    name: str = "problem"
    obj_sense: ObjSense = ObjSense.MIN
    variables: Dict[str, Variable] = field(default_factory=dict)
    constraints: List[Constraint] = field(default_factory=dict if False else list)
    var_order: List[str] = field(default_factory=list)

    # ---- building ----
    def add_variable(self, name: str, lb: float = 0.0, ub: float = INF,
                      vtype: VarType = VarType.CONTINUOUS, obj: float = 0.0) -> Variable:
        if name in self.variables:
            raise ValueError(f"Variable {name} already exists")
        if vtype == VarType.BINARY:
            lb, ub = 0.0, 1.0
        v = Variable(name=name, lb=lb, ub=ub, vtype=vtype, obj_coeff=obj)
        self.variables[name] = v
        self.var_order.append(name)
        return v

    def add_constraint(self, name: str, coeffs: Dict[str, float], sense: Sense, rhs: float) -> Constraint:
        for vn in coeffs:
            if vn not in self.variables:
                raise ValueError(f"Constraint {name} references unknown variable {vn}")
        c = Constraint(name=name, coeffs=dict(coeffs), sense=sense, rhs=rhs)
        self.constraints.append(c)
        return c

    def set_objective(self, coeffs: Dict[str, float], sense: ObjSense = ObjSense.MIN):
        self.obj_sense = sense
        for vn, c in coeffs.items():
            if vn not in self.variables:
                raise ValueError(f"Objective references unknown variable {vn}")
            self.variables[vn].obj_coeff = c

    # ---- introspection ----
    def num_vars(self) -> int:
        return len(self.variables)

    def num_constraints(self) -> int:
        return len(self.constraints)

    def num_integer_vars(self) -> int:
        return sum(1 for v in self.variables.values() if v.is_integer())

    def num_nonzeros(self) -> int:
        return sum(len(c.coeffs) for c in self.constraints)

    def is_milp(self) -> bool:
        return self.num_integer_vars() > 0

    def copy(self) -> "Model":
        m = Model(name=self.name, obj_sense=self.obj_sense)
        for vn in self.var_order:
            v = self.variables[vn]
            m.add_variable(vn, lb=v.lb, ub=v.ub, vtype=v.vtype, obj=v.obj_coeff)
        for c in self.constraints:
            m.add_constraint(c.name, dict(c.coeffs), c.sense, c.rhs)
        return m
