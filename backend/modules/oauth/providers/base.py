from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    # Given the ID token claims: is `iss` this provider?
    valid_issuer: Callable[[dict], bool]
    # Given the ID token claims: can the email be trusted to log someone in?
    email_verified: Callable[[dict], bool]
