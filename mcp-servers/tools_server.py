"""AgentOS Tools MCP Server — utility tools for agents."""

import uuid
from datetime import datetime, timezone, timedelta

from fastmcp import FastMCP

mcp = FastMCP("AgentOS Tools")


@mcp.tool()
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely.

    Args:
        expression: Math expression (e.g., "2 + 2", "sqrt(144)", "15 * 1.08").

    Returns:
        The result as a string.
    """
    import ast
    import math

    # Safe evaluation using ast.literal_eval for simple expressions
    # For complex math, use a restricted eval with math functions
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow, "int": int, "float": float,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "pi": math.pi, "e": math.e, "ceil": math.ceil, "floor": math.floor,
    }

    try:
        # Validate: only allow safe characters
        safe_chars = set("0123456789.+-*/()%, abcdefghijklmnopqrstuvwxyz_")
        if not all(c in safe_chars for c in expression.lower()):
            return f"Error: expression contains disallowed characters"

        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error evaluating '{expression}': {e}"


@mcp.tool()
def get_current_datetime(tz: str = "UTC") -> str:
    """Get current date and time in the specified timezone.

    Args:
        tz: Timezone offset (e.g., "UTC", "+5", "-8", "EST").

    Returns:
        Current datetime formatted as ISO 8601.
    """
    offsets = {
        "UTC": 0, "GMT": 0, "EST": -5, "CST": -6,
        "MST": -7, "PST": -8, "CET": 1, "JST": 9,
        "IST": 5, "AEST": 10,
    }

    offset_hours = offsets.get(tz.upper(), None)
    if offset_hours is None:
        try:
            offset_hours = int(tz.replace("+", ""))
        except ValueError:
            offset_hours = 0

    now = datetime.now(timezone(timedelta(hours=offset_hours)))
    return now.strftime("%Y-%m-%d %H:%M:%S %Z (offset: UTC%+d)")


@mcp.tool()
def generate_uuid() -> str:
    """Generate a new UUID v4.

    Returns:
        A new random UUID string.
    """
    return str(uuid.uuid4())


@mcp.tool()
def format_currency(amount: float, currency: str = "USD") -> str:
    """Format a number as currency.

    Args:
        amount: The numeric amount.
        currency: Currency code (USD, EUR, GBP, JPY, MXN).

    Returns:
        Formatted currency string.
    """
    symbols = {
        "USD": "$", "EUR": "\u20ac", "GBP": "\u00a3",
        "JPY": "\u00a5", "MXN": "$", "CAD": "C$",
        "AUD": "A$", "CHF": "CHF ", "CNY": "\u00a5",
        "INR": "\u20b9", "BRL": "R$",
    }
    symbol = symbols.get(currency.upper(), currency + " ")

    if currency.upper() == "JPY":
        return f"{symbol}{amount:,.0f}"

    return f"{symbol}{amount:,.2f}"


@mcp.tool()
def json_format(data: str) -> str:
    """Pretty-print a JSON string.

    Args:
        data: Raw JSON string to format.

    Returns:
        Formatted JSON string.
    """
    import json
    try:
        parsed = json.loads(data)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"


if __name__ == "__main__":
    mcp.run()
