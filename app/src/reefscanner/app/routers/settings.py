"""Settings: the person using this laptop, who signs reviews, and how the
app looks."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from .. import metadata
from ..deps import get_session
from ..models import AppSettings
from ..schemas import Appearance, SettingsRead, SettingsWrite

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _read(session: Session) -> SettingsRead:
    you = metadata.settings(session)
    return SettingsRead(
        name=you.name, email=you.email, organization=you.organization,
        signed_as=metadata.signed_as(session),
    )


@router.get("", response_model=SettingsRead)
def get_settings(session: Session = Depends(get_session)) -> SettingsRead:
    return _read(session)


@router.put("", response_model=SettingsRead)
def put_settings(
    payload: SettingsWrite, session: Session = Depends(get_session)
) -> SettingsRead:
    """Replace the settings. Blank fields are cleared; a blank name falls back
    to the login name. Existing projects keep their contributors."""
    you = session.get(AppSettings, 1) or AppSettings(id=1)
    for key, value in payload.model_dump().items():
        setattr(you, key, (value or "").strip() or None)
    session.add(you)
    session.commit()
    return _read(session)


@router.get("/appearance", response_model=Appearance)
def get_appearance(session: Session = Depends(get_session)) -> Appearance:
    you = metadata.settings(session)
    return Appearance(mode=you.appearance_mode, translucency=you.translucency)


@router.put("/appearance", response_model=Appearance)
def put_appearance(
    payload: Appearance, session: Session = Depends(get_session)
) -> Appearance:
    you = session.get(AppSettings, 1) or AppSettings(id=1)
    you.appearance_mode = payload.mode
    you.translucency = payload.translucency
    session.add(you)
    session.commit()
    return payload
