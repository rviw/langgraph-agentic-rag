import ast
import math
import operator
from collections.abc import Callable
from typing import Annotated

from langchain_core.tools import tool
from pydantic import Field

MAX_EXPRESSION_CHARACTERS = 200
_MAX_EXPRESSION_DEPTH = 20
_MAX_EXPRESSION_OPERATIONS = 20
_MAX_NUMBER = 10**100
_MAX_EXPONENT = 100

_BINARY_OPERATORS: dict[
    type[ast.operator], Callable[[int | float, int | float], int | float]
] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[int | float], int | float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _checked(value: object) -> int | float:
    if type(value) not in (int, float):
        raise ValueError("Invalid arithmetic expression")
    if abs(value) > _MAX_NUMBER:
        raise ValueError("Arithmetic result is too large")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Arithmetic result must be finite")
    return value


def _evaluate(node: ast.expr, *, depth: int, operations: list[int]) -> int | float:
    if depth > _MAX_EXPRESSION_DEPTH:
        raise ValueError("Arithmetic expression is too complex")

    if isinstance(node, ast.Constant):
        return _checked(node.value)

    operations[0] += 1
    if operations[0] > _MAX_EXPRESSION_OPERATIONS:
        raise ValueError("Arithmetic expression is too complex")

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        operand = _evaluate(node.operand, depth=depth + 1, operations=operations)
        return _checked(_UNARY_OPERATORS[type(node.op)](operand))

    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, depth=depth + 1, operations=operations)
        right = _evaluate(node.right, depth=depth + 1, operations=operations)

        if isinstance(node.op, ast.Pow):
            # Bound the exponent so one expression cannot occupy the process.
            if type(right) is not int or abs(right) > _MAX_EXPONENT:
                raise ValueError("Arithmetic exponent is not supported")
            return _checked(operator.pow(left, right))

        operation = _BINARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise ValueError("Invalid arithmetic expression")
        return _checked(operation(left, right))

    raise ValueError("Invalid arithmetic expression")


def evaluate_expression(expression: str) -> int | float:
    """Evaluate arithmetic from an untrusted string without executing code."""

    normalized = expression.strip()
    if not normalized or len(normalized) > MAX_EXPRESSION_CHARACTERS:
        raise ValueError("Arithmetic expression must contain 1 to 200 characters")

    try:
        parsed = ast.parse(normalized, mode="eval")
        return _evaluate(parsed.body, depth=0, operations=[0])
    except (OverflowError, SyntaxError, ZeroDivisionError) as exc:
        raise ValueError("Invalid arithmetic expression") from exc


@tool
def calculator(
    expression: Annotated[
        str,
        Field(
            min_length=1,
            max_length=MAX_EXPRESSION_CHARACTERS,
            description=(
                "An arithmetic expression using numbers, parentheses, "
                "+, -, *, /, //, %, and **"
            ),
        ),
    ],
) -> str:
    """Evaluate a basic arithmetic expression."""

    return str(evaluate_expression(expression))
