from django.http import HttpRequest
from ninja import Router, Schema

from modules.bearer.security import user_auth

router = Router()


class PingIn(Schema):
    message: str = "ping"


class PingOut(Schema):
    message: str


# An example to copy, and to try the API with: delete it once the project has
# its own endpoints (and its line in config/urls.py).
@router.post("/ping", response=PingOut, auth=user_auth, tags=["core"])
def ping(request: HttpRequest, data: PingIn):
    """Answers "pong" to "ping", and echoes anything else."""
    return {"message": "pong" if data.message == "ping" else data.message}
