import random
import string

def generate_student_username(first_name, surname, day, month):
    """
    Generate a username for a student.
    Format: FirstName + FirstTwoLettersOfSurname + Day + Month
    """
    username = f"{first_name.capitalize()}{surname[:2].capitalize()}{day:02}{month:02}"
    return username

def generate_random_password(length=4):
    """
    Generate a random numeric password of a given length.
    """
    return ''.join(random.choices(string.digits, k=length))
