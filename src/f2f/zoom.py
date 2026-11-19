"""Meeting links for F2F invites.

v1 uses the Zoom link the TL pastes. Creating meetings through the Zoom API is deferred; ZoomApiProvider
marks where a Server-to-Server OAuth integration (POST /v2/users/me/meetings) would go.
"""

from __future__ import annotations

from typing import Protocol

from f2f.models import F2F


class MeetingProvider(Protocol):
    async def meeting_link(self, f2f: F2F) -> str: ...


class PastedLinkProvider:
    async def meeting_link(self, f2f: F2F) -> str:
        return f2f.zoom_link


class ZoomApiProvider:
    async def meeting_link(self, f2f: F2F) -> str:
        raise NotImplementedError("Zoom API meeting creation is not implemented; paste a Zoom link instead")
