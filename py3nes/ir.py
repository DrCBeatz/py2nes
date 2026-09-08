"""A small typed language for state that exists in the running cartridge.

Python builds these immutable expression trees. Only generated 6502 code reads
their values. Arithmetic wraps to eight bits; comparisons preserve signedness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


class ActionSpec:
    """Marker for an explicit gameplay statement."""
    depth = 0


class Expr:
    kind = "u8"
    depth = 0

    def __eq__(self, other):
        raise TypeError("use .eq() for runtime equality, or 'is' for description identity")

    def __ne__(self, other):
        raise TypeError("use .ne() for runtime inequality, or 'is not' for description identity")

    def __bool__(self):
        raise TypeError("runtime values cannot be used in Python if/and/or; use If and conditions joined with &, |, ~")

    def __add__(self, other): return Binary("+", self, as_expr(other))
    def __radd__(self, other): return Binary("+", as_expr(other), self)
    def __sub__(self, other): return Binary("-", self, as_expr(other))
    def __rsub__(self, other): return Binary("-", as_expr(other), self)
    def __and__(self, other):
        if self.kind == "flag" and (isinstance(other, Condition) or getattr(other, "kind", None) == "flag"):
            return as_condition(self) & other
        return Binary("&", self, as_expr(other))
    def __or__(self, other):
        if self.kind == "flag" and (isinstance(other, Condition) or getattr(other, "kind", None) == "flag"):
            return as_condition(self) | other
        return Binary("|", self, as_expr(other))
    def __invert__(self):
        return ~as_condition(self) if self.kind == "flag" else Binary("^", self, Constant(255))
    def __xor__(self, other): return Binary("^", self, as_expr(other))
    def eq(self, other): return Compare("eq", self, as_expr(other))
    def ne(self, other): return Compare("ne", self, as_expr(other))
    def lt(self, other): return Compare("lt", self, as_expr(other))
    def le(self, other): return Compare("le", self, as_expr(other))
    def gt(self, other): return Compare("gt", self, as_expr(other))
    def ge(self, other): return Compare("ge", self, as_expr(other))


@dataclass(frozen=True, eq=False)
class Constant(Expr):
    value: int

    def __post_init__(self):
        if not isinstance(self.value, int) or not -255 <= self.value <= 255:
            raise ValueError("expression constants must be integers from -255 to 255")

    @property
    def kind(self):
        return "i8" if self.value < 0 else "u8"


@dataclass(frozen=True, eq=False)
class Variable(Expr):
    name: str
    initial: int = 0
    kind: str = "u8"

    def __post_init__(self):
        if not isinstance(self.name, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", self.name) is None:
            raise ValueError("variable name must start with an ASCII letter and contain only letters, digits, underscores")
        if self.kind not in ("u8", "i8", "flag"):
            raise ValueError("variable kind must be u8, i8, or flag")
        low, high = {"u8": (0, 255), "i8": (-128, 127), "flag": (0, 1)}[self.kind]
        if not isinstance(self.initial, int) or (isinstance(self.initial, bool) and self.kind != "flag"):
            raise TypeError("variable initial value must be an integer (bool is allowed for flags)")
        if not low <= self.initial <= high:
            raise ValueError(f"{self.kind} initial value must be between {low} and {high}")


def as_expr(value) -> Expr:
    if isinstance(value, Expr):
        return value
    if isinstance(value, int):
        return Constant(value)
    raise TypeError("runtime expression must be an integer or a registered variable/expression")


@dataclass(frozen=True, eq=False)
class Binary(Expr):
    operator: str
    left: Expr
    right: Expr
    _kind: str = field(init=False, repr=False)
    depth: int = field(init=False, repr=False)

    def __post_init__(self):
        if self.operator not in ("+", "-", "&", "|", "^"):
            raise ValueError("unsupported byte operator")
        object.__setattr__(self, "left", as_expr(self.left))
        object.__setattr__(self, "right", as_expr(self.right))
        _compatible(self.left, self.right)
        operand = self.right if isinstance(self.left, Constant) else self.left
        object.__setattr__(self, "_kind", "i8" if operand.kind == "i8" else "u8")
        depth = 1 + max(self.left.depth, self.right.depth)
        if depth > 32:
            raise ValueError("runtime expressions may nest at most 32 levels")
        object.__setattr__(self, "depth", depth)

    @property
    def kind(self):
        return self._kind


def _compatible(left: Expr, right: Expr):
    if not isinstance(left, Constant) and not isinstance(right, Constant):
        if (left.kind == "i8") != (right.kind == "i8"):
            raise TypeError("signed and unsigned runtime expressions cannot be mixed")


class Condition:
    depth = 0

    def __eq__(self, other):
        raise TypeError("runtime conditions cannot use Python ==; combine .eq()/.ne() comparisons with &, |, ~")

    def __ne__(self, other):
        raise TypeError("runtime conditions cannot use Python !=; combine .eq()/.ne() comparisons with &, |, ~")

    def __bool__(self):
        raise TypeError("runtime conditions cannot be evaluated by Python; use If and &, |, ~")

    def __and__(self, other): return Logical("and", self, as_condition(other))
    def __or__(self, other): return Logical("or", self, as_condition(other))
    def __invert__(self): return Logical("not", self)


@dataclass(frozen=True, eq=False)
class Compare(Condition):
    operator: str
    left: Expr
    right: Expr

    def __post_init__(self):
        if self.operator not in ("eq", "ne", "lt", "le", "gt", "ge"):
            raise ValueError("unsupported comparison")
        object.__setattr__(self, "left", as_expr(self.left))
        object.__setattr__(self, "right", as_expr(self.right))
        _compatible(self.left, self.right)
        for value in (self.left, self.right):
            if isinstance(value, Constant):
                low, high = (-128, 127) if self.signed else (0, 255)
                if not low <= value.value <= high:
                    raise ValueError(f"comparison constant must be between {low} and {high}")

    @property
    def signed(self):
        values = [value for value in (self.left, self.right) if not isinstance(value, Constant)]
        return any(value.kind == "i8" for value in (values or (self.left, self.right)))


@dataclass(frozen=True, eq=False)
class Logical(Condition):
    operator: str
    left: Condition
    right: Condition | None = None
    depth: int = field(init=False, repr=False)

    def __post_init__(self):
        if self.operator not in ("and", "or", "not"):
            raise ValueError("unsupported condition operator")
        object.__setattr__(self, "left", as_condition(self.left))
        if self.operator != "not":
            object.__setattr__(self, "right", as_condition(self.right))
        elif self.right is not None:
            raise ValueError("not takes only one condition")
        depth = 1 + max(self.left.depth, self.right.depth if self.right is not None else 0)
        if depth > 32:
            raise ValueError("runtime conditions may nest at most 32 levels")
        object.__setattr__(self, "depth", depth)


def as_condition(value) -> Condition:
    if isinstance(value, Condition):
        return value
    if isinstance(value, Expr):
        return value.ne(0)
    if isinstance(value, bool):
        return Constant(int(value)).eq(1)
    raise TypeError("If requires a runtime condition or flag")


@dataclass(frozen=True)
class Set(ActionSpec):
    variable: Variable
    value: Expr

    def __post_init__(self):
        if not isinstance(self.variable, Variable):
            raise TypeError("Set target must be a registered variable")
        value = as_expr(self.value)
        if self.variable.kind == "flag":
            if not (isinstance(value, Constant) and value.value in (0, 1)) and value.kind != "flag":
                raise ValueError("flags can only be set to 0, 1, bool, or another flag")
        elif not isinstance(value, Constant):
            _compatible(self.variable, value)
        elif self.variable.kind == "i8" and not -128 <= value.value <= 127:
            raise ValueError("signed Set constant must fit -128..127")
        elif self.variable.kind == "u8" and not 0 <= value.value <= 255:
            raise ValueError("byte Set constant must fit 0..255")
        object.__setattr__(self, "value", value)


@dataclass(frozen=True)
class Add(ActionSpec):
    variable: Variable
    value: Expr

    def __post_init__(self):
        if not isinstance(self.variable, Variable):
            raise TypeError("Add target must be a registered variable")
        if self.variable.kind == "flag":
            raise ValueError("flags do not support Add; use Set")
        value = as_expr(self.value)
        _compatible(self.variable, value)
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, init=False)
class If(ActionSpec):
    condition: Condition
    actions: tuple[ActionSpec, ...]
    otherwise: tuple[ActionSpec, ...]
    depth: int = field(init=False, repr=False)

    def __init__(self, condition, *actions, otherwise=()):
        object.__setattr__(self, "condition", as_condition(condition))
        object.__setattr__(self, "actions", tuple(actions))
        object.__setattr__(self, "otherwise", tuple(otherwise))
        if not actions and not self.otherwise:
            raise ValueError("If needs at least one action")
        for action in self.actions + self.otherwise:
            if not isinstance(action, ActionSpec):
                raise TypeError("If branches require explicit actions, not Python callbacks")
        depth = 1 + max(action.depth for action in self.actions + self.otherwise)
        if depth > 32:
            raise ValueError("conditional actions may nest at most 32 levels")
        object.__setattr__(self, "depth", depth)


def walk_actions(actions):
    """Walk both branches, so allocation and validation never depend on runtime state."""
    for action in actions:
        yield action
        if isinstance(action, If):
            yield from walk_actions(action.actions)
            yield from walk_actions(action.otherwise)
