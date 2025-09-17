import random
import string
from datetime import date, datetime
from typing import Union


def _coerce_to_date(dob: Union[str, date, datetime]) -> date:
    """Normalize supported date inputs to a ``date`` object."""

    if isinstance(dob, date) and not isinstance(dob, datetime):
        return dob
    if isinstance(dob, datetime):
        return dob.date()
    if isinstance(dob, str):
        dob = dob.strip()
        try:
            return datetime.strptime(dob, "%d/%m/%Y").date()
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError("Date of birth must be in DD/MM/YYYY format.") from exc
    raise TypeError("Date of birth must be a date, datetime, or DD/MM/YYYY string.")


def generate_student_username(first_name, surname, day=None, month=None, dob=None):
    """Generate a username using the student's name and date of birth details."""

    if dob is not None and (day is None or month is None):
        parsed = _coerce_to_date(dob)
        day = parsed.day
        month = parsed.month

    if day is None or month is None:
        raise ValueError("Day and month or a valid date of birth must be provided.")

    username = f"{first_name.capitalize()}{surname[:2].capitalize()}{int(day):02}{int(month):02}"
    return username

def generate_random_password(length=4):
    """
    Generate a random numeric password of a given length.
    """
    return ''.join(random.choices(string.digits, k=length))
