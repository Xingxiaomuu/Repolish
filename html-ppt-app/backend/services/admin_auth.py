from fastapi import Header, HTTPException
from settings import settings


def verify_admin_password(x_admin_password: str = Header(None)):
    """FastAPI dependency: require X-Admin-Password header if password is configured."""
    if not settings.admin_password:
        return  # No password configured — allow all access
    if not x_admin_password or x_admin_password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid admin password")
