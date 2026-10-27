"""Who made the data: the person on this laptop, and each project's metadata.

The person (``AppSettings``) signs reviews and is a new project's first
contributor. A project's metadata is what its exported packages say about the
study and its team. Design:
docs/specs/v3/features/2026-10-27-package-metadata-design.md.
"""

from __future__ import annotations

import getpass
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session

from .models import AppSettings, Project
from .schemas import Contributor, PackageMetadata, ProjectInfo


def settings(session: Session) -> AppSettings:
    """The single settings row; unsaved defaults until the person sets any."""
    return session.get(AppSettings, 1) or AppSettings()


def signed_as(session: Session) -> str:
    """The name reviews are signed with: the person's, else the login name."""
    return settings(session).name or getpass.getuser()


def default_metadata(session: Session, project_name: str) -> PackageMetadata:
    """A new project's metadata: its name as the title, you as contributor."""
    you = settings(session)
    return PackageMetadata(
        project=ProjectInfo(title=project_name),
        contributors=[Contributor(
            title=signed_as(session), email=you.email, organization=you.organization,
        )],
    )


def stored(metadata: PackageMetadata) -> dict[str, Any]:
    """As kept on the project and written to ``datapackage.json``.

    Unset fields are left out: Camtrap has no use for null emails.
    """
    return metadata.model_dump(exclude_none=True)


def project_metadata(session: Session, project: Project) -> PackageMetadata:
    if project.package_metadata:
        return PackageMetadata.model_validate(project.package_metadata)
    return default_metadata(session, project.name)


def from_package(meta: dict[str, Any], problems: list[str]) -> dict[str, Any] | None:
    """The project and contributors of an imported ``datapackage.json``.

    Untrusted, so it goes through the same checks as the settings page and
    only the fields it defines are kept. Problems are added to ``problems``.
    """
    try:
        metadata = PackageMetadata.model_validate(
            {"project": meta.get("project"), "contributors": meta.get("contributors")}
        )
    except ValidationError as exc:
        for error in exc.errors():
            where = ".".join(str(part) for part in error["loc"])
            problems.append(f"metadata {where}: {error['msg']}")
        return None
    return stored(metadata)
