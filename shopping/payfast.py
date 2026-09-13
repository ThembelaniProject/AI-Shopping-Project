from hashlib import md5
from urllib.parse import quote_plus


def generate_signature(data, passphrase=None):

    parameter_string = ""

    for key, value in data.items():

        if value is None:
            continue

        value = str(value).strip()

        if not value:
            continue

        parameter_string += (
            f"{key}={quote_plus(value)}&"
        )

    parameter_string = parameter_string.rstrip("&")

    if passphrase:
        parameter_string += (
            "&passphrase="
            + quote_plus(passphrase.strip())
        )

    return md5(
        parameter_string.encode("utf-8")
    ).hexdigest()
