from .json_api import ConfigurableJsonAdapter


def pay_text_from_salary_range(payload: dict) -> str | None:
    """Lever posts pay as a structured `salaryRange` object ({min, max, currency, interval}),
    separate from description/lists/additional (confirmed live on Zoox: the posting page
    shows "$146,000 - $199,000 a year" while none of the text fields carry it), so a text
    mine of the description finds nothing. Turns a yearly USD range into a plain sentence the
    shared `salary.evaluate_salary` reads like any other posting. Only per-year USD pairs
    with min <= max are used, never a guess (an hourly figure would read as an annual one)."""
    salary_range = payload.get("salaryRange")
    if not isinstance(salary_range, dict):
        return None
    low, high = salary_range.get("min"), salary_range.get("max")
    if (
        salary_range.get("currency") != "USD"
        or salary_range.get("interval") != "per-year-salary"
        or isinstance(low, bool)
        or isinstance(high, bool)
        or not isinstance(low, (int, float))
        or not isinstance(high, (int, float))
        or not 0 < low <= high
    ):
        return None
    return f"Pay range: ${low:,.0f} - ${high:,.0f} a year."


class LeverAdapter(ConfigurableJsonAdapter):
    def augment_description(self, payload: dict, description: str | None) -> str | None:
        pay = pay_text_from_salary_range(payload)
        if not pay:
            return description
        return f"{description}\n\n{pay}" if description else pay
