"""
Rule expressions: a JSON tree evaluated against one energy reading.

Every operator node is a single-key dict `{op: [arguments]}`. Operands are
`{"field": name}` (a `RuleContext` field), numbers, or strings (`HH:MM`
time / ISO 8601 datetime) typed by the other side of the comparison.

Evaluation is three-valued: a null reading or a division by zero is
unknown (None), `not` keeps it unknown, and a rule passes only when the
result is True.
"""

import operator
import typing
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, time
from functools import cache
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone

from src.director_app.schemas import RuleContext

NUMBER = "number"
TIME = "time"
DATETIME = "datetime"
BOOL = "bool"
# A string constant; its type comes from the other side of a comparison.
STRING = "string"

COMPARABLE = (NUMBER, TIME, DATETIME)
FIELD = "field"


@dataclass(frozen=True)
class Operator:
    kind: str
    symbol: str
    types: tuple[str, ...]
    func: Callable[[Any, Any], Any] | None = None


OPERATORS = {
    "and": Operator(
        "logic",
        "AND",
        (BOOL,),
    ),
    "or": Operator(
        "logic",
        "OR",
        (BOOL,),
    ),
    "not": Operator(
        "logic",
        "NOT",
        (BOOL,),
    ),
    "eq": Operator(
        "comparison",
        "=",
        COMPARABLE,
        operator.eq,
    ),
    "ne": Operator(
        "comparison",
        "!=",
        COMPARABLE,
        operator.ne,
    ),
    "gt": Operator(
        "comparison",
        ">",
        COMPARABLE,
        operator.gt,
    ),
    "ge": Operator(
        "comparison",
        "≥",
        COMPARABLE,
        operator.ge,
    ),
    "lt": Operator(
        "comparison",
        "<",
        COMPARABLE,
        operator.lt,
    ),
    "le": Operator(
        "comparison",
        "≤",
        COMPARABLE,
        operator.le,
    ),
    "in": Operator(
        "membership",
        "in",
        (NUMBER, TIME),
    ),
    "add": Operator(
        "arithmetic",
        "+",
        (NUMBER,),
        operator.add,
    ),
    "sub": Operator(
        "arithmetic",
        "−",
        (NUMBER,),
        operator.sub,
    ),
    "mul": Operator(
        "arithmetic",
        "×",
        (NUMBER,),
        operator.mul,
    ),
    "div": Operator(
        "arithmetic",
        "÷",
        (NUMBER,),
        operator.truediv,
    ),
}


@dataclass(frozen=True)
class RuleField:
    name: str
    type: str
    nullable: bool
    description: str | None


_PYTHON_TYPES = {int: NUMBER, float: NUMBER, time: TIME, datetime: DATETIME}


def _value_type(annotation) -> tuple[str | None, bool]:
    args = typing.get_args(annotation)
    nullable = type(None) in args
    if args:
        rest = [arg for arg in args if arg is not type(None)]
        annotation = rest[0] if len(rest) == 1 else None
    return _PYTHON_TYPES.get(annotation), nullable


@cache
def rule_fields() -> dict[str, RuleField]:
    """Rule operands: every `RuleContext` field with a comparable type."""
    annotated = {
        **{
            name: (info.annotation, info.description)
            for name, info in RuleContext.model_fields.items()
        },
        **{
            name: (info.return_type, info.description)
            for name, info in RuleContext.model_computed_fields.items()
        },
    }
    fields = {}
    for name, (annotation, description) in annotated.items():
        value_type, nullable = _value_type(annotation)
        if name != "id" and value_type is not None:
            fields[name] = RuleField(
                name,
                value_type,
                nullable,
                description,
            )
    return fields


def catalog() -> dict:
    """Fields and operators for the admin rule builder."""
    return {
        "fields": [asdict(field) for field in rule_fields().values()],
        "operators": [
            {
                "op": op,
                "kind": spec.kind,
                "symbol": spec.symbol,
                "types": list(spec.types),
            }
            for op, spec in OPERATORS.items()
        ],
    }


def _parse_time(value: str) -> time:
    parsed = time.fromisoformat(value)
    if parsed.tzinfo is not None:
        raise ValueError("time constants are local, without an offset")
    return parsed


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    # Naive constants are local time, like the derived time fields.
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


_PARSERS = {TIME: _parse_time, DATETIME: _parse_datetime}
_FORMATS = {TIME: "HH:MM", DATETIME: "ISO 8601, e.g. 2026-10-01T00:00"}


def _split(node: dict) -> tuple[str, Any]:
    ((op, args),) = node.items()
    return op, args


def _error(path: str, message: str) -> ValidationError:
    return ValidationError(f"{path}: {message}" if path else message)


def validate_combination(value) -> None:
    if _check(value, "") != BOOL:
        raise _error(
            "",
            "A rule must be a condition: and / or / not, a comparison or in.",
        )


def _check(node, path: str) -> str:
    if isinstance(node, (bool, list)) or node is None:
        raise _error(path, "expected an operator, a number or a string")
    if isinstance(node, (int, float)):
        return NUMBER
    if isinstance(node, str):
        return STRING
    if len(node) != 1:
        raise _error(path, 'expected one {"operator": [arguments]} pair')
    op, args = _split(node)
    here = f"{path}.{op}" if path else op
    if op == FIELD:
        if not isinstance(args, str) or args not in rule_fields():
            raise _error(here, f"unknown field {args!r}")
        return rule_fields()[args].type
    spec = OPERATORS.get(op)
    if spec is None:
        raise _error(path, f"unknown operator {op!r}")
    if not isinstance(args, list):
        raise _error(here, "arguments must be a list")
    if spec.kind == "logic":
        return _check_logic(
            op,
            args,
            here,
        )
    if spec.kind == "membership":
        return _check_membership(
            spec,
            args,
            here,
        )
    if len(args) != 2:
        raise _error(here, "expects two arguments")
    left, right = (_check(arg, f"{here}[{i}]") for i, arg in enumerate(args))
    if spec.kind == "arithmetic":
        for i, kind in enumerate((left, right)):
            if kind != NUMBER:
                raise _error(f"{here}[{i}]", "expected a number")
        return NUMBER
    if BOOL in (left, right):
        raise _error(here, "cannot compare conditions")
    kind = _common_type(
        left,
        right,
        args,
        here,
    )
    if kind not in spec.types:
        raise _error(here, f"cannot compare {kind} values")
    return BOOL


def _check_logic(
    op: str,
    args: list,
    here: str,
) -> str:
    if op == "not" and len(args) != 1:
        raise _error(here, "expects one condition")
    if not args:
        raise _error(here, "expects at least one condition")
    for i, arg in enumerate(args):
        if _check(arg, f"{here}[{i}]") != BOOL:
            raise _error(f"{here}[{i}]", "expected a condition")
    return BOOL


def _check_membership(
    spec: Operator,
    args: list,
    here: str,
) -> str:
    if len(args) != 2 or not isinstance(args[1], list) or not args[1]:
        raise _error(here, "expects a value and a non-empty list")
    kind = _check(args[0], f"{here}[0]")
    if kind not in spec.types or not _has_field(args[0]):
        raise _error(f"{here}[0]", "expected a number or time field")
    for i, constant in enumerate(args[1]):
        _check_constant(
            constant,
            kind,
            f"{here}[1][{i}]",
        )
    return BOOL


def _common_type(
    left: str,
    right: str,
    args: list,
    here: str,
) -> str:
    if left == right == STRING:
        raise _error(here, "compare at least one field")
    if STRING not in (left, right):
        if left != right:
            raise _error(here, f"cannot compare {left} with {right}")
        if not (_has_field(args[0]) or _has_field(args[1])):
            raise _error(here, "compare at least one field")
        return left
    kind, index = (right, 0) if left == STRING else (left, 1)
    _check_constant(
        args[index],
        kind,
        f"{here}[{index}]",
    )
    return kind


def _check_constant(value, kind: str, path: str) -> None:
    if kind == NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _error(path, "expected a number")
        return
    if not isinstance(value, str):
        raise _error(path, f"expected a {kind} string ({_FORMATS[kind]})")
    try:
        _PARSERS[kind](value)
    except ValueError:
        raise _error(
            path,
            f"invalid {kind} {value!r}, use {_FORMATS[kind]}",
        ) from None


def _has_field(node) -> bool:
    if not isinstance(node, dict):
        return False
    op, args = _split(node)
    return op == FIELD or any(_has_field(arg) for arg in args)


def evaluate(combination: dict, context: RuleContext) -> bool | None:
    """True / False, or None when a reading is unknown."""
    op, args = _split(combination)
    if op in ("and", "or"):
        results = [evaluate(arg, context) for arg in args]
        decisive = op == "or"
        if any(result is decisive for result in results):
            return decisive
        if any(result is None for result in results):
            return None
        return not decisive
    if op == "not":
        result = evaluate(args[0], context)
        return None if result is None else not result
    left = _value(args[0], context)
    if left is None:
        return None
    if op == "in":
        return left in [_coerce(constant, left) for constant in args[1]]
    right = _value(args[1], context)
    if right is None:
        return None
    return OPERATORS[op].func(_coerce(left, right), _coerce(right, left))


def _value(node, context: RuleContext):
    if not isinstance(node, dict):
        return node
    op, args = _split(node)
    if op == FIELD:
        # A field dropped from the schema reads as unknown.
        return getattr(
            context,
            args,
            None,
        )
    left, right = (_value(arg, context) for arg in args)
    if left is None or right is None:
        return None
    try:
        return OPERATORS[op].func(left, right)
    except ZeroDivisionError:
        return None


def _coerce(value, like):
    if isinstance(value, str):
        if isinstance(like, datetime):
            return _parse_datetime(value)
        if isinstance(like, time):
            return _parse_time(value)
    return value


def describe(combination) -> str:
    """Readable form, e.g. `(weekday in [0, 1]) AND (pv1_power_w > 300)`."""
    try:
        return _describe(combination, top=True)
    except (AttributeError, KeyError, TypeError, ValueError):
        return "invalid rule"


def _describe(node, top: bool = False) -> str:
    op, args = _split(node)
    if op in ("and", "or"):
        text = f" {OPERATORS[op].symbol} ".join(_describe(a) for a in args)
        return text if top or len(args) == 1 else f"({text})"
    if op == "not":
        return f"NOT ({_describe(args[0], top=True)})"
    if op == "in":
        constants = ", ".join(str(constant) for constant in args[1])
        return f"{_describe_value(args[0])} in [{constants}]"
    left, right = (_describe_value(arg) for arg in args)
    return f"{left} {OPERATORS[op].symbol} {right}"


def _describe_value(node) -> str:
    if not isinstance(node, dict):
        return str(node)
    op, args = _split(node)
    if op == FIELD:
        return args
    left, right = (_describe_value(arg) for arg in args)
    return f"({left} {OPERATORS[op].symbol} {right})"
