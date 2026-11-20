from ninja import Router

from . import auth, users

# One router per app, mounted without a prefix (see config/urls.py). Each file
# here covers one path (/auth, /users) and its decorators hold the full
# path (after /api), so searching for a URL finds its code.
router = Router()
router.add_router("", auth.router)
router.add_router("", users.router)
