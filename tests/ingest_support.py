"""Small deterministic fake transport shared by the ingest tests."""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from agent2learn.api import DownloadResult
from agent2learn.calibrate import CourseRef
from agent2learn.schools.uwaterloo import UWaterloo


@dataclass
class FakeSession:
    """The attributes the ingest layer needs from a calibrated API client."""

    base_url: str = "https://learn.example.test"


DownloadHandler = Callable[[str, Path, object | None], DownloadResult]


class FakeClient:
    """A no-network client with endpoint payloads and controllable download behavior."""

    def __init__(
        self,
        courses: list[CourseRef],
        *,
        tocs: Mapping[int, object] | None = None,
        responses: Mapping[str, object] | None = None,
        download_handler: DownloadHandler | None = None,
    ) -> None:
        self.school = UWaterloo()
        self.session = FakeSession()
        self.lp_version = "1.62"
        self.le_version = "1.96"
        self.download_template: str | None = None
        self.courses = list(courses)
        self.tocs = dict(tocs or {})
        self.responses = dict(responses or {})
        self.download_handler = download_handler or self._default_download
        self.json_calls: list[str] = []
        self.download_calls: list[str] = []

    def get_json(self, path: str) -> object:
        self.json_calls.append(path)
        route = urlsplit(path).path
        if "/content/toc" in route:
            org_unit = int(route.split("/")[-3])
            return copy.deepcopy(self.tocs.get(org_unit, {"Modules": []}))
        for suffix, payload in self.responses.items():
            if route.endswith(suffix):
                return copy.deepcopy(payload)
        if route.endswith("/dropbox/folders/") or route.endswith("/news/"):
            return []
        if route.endswith("/quizzes/"):
            return {"Next": None, "Objects": []}
        return []

    def download(
        self,
        url: str,
        temp: Path,
        *,
        prior: object | None = None,
        max_bytes: int = 2_147_483_648,
        is_html_topic: bool = False,
    ) -> DownloadResult:
        del max_bytes, is_html_topic
        self.download_calls.append(url)
        return self.download_handler(url, temp, prior)

    @staticmethod
    def _default_download(url: str, temp: Path, prior: object | None) -> DownloadResult:
        del prior
        payload = f"synthetic source for {urlsplit(url).path}".encode()
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(payload)
        return DownloadResult(
            temp=temp,
            sha256=sha256(payload).hexdigest(),
            size=len(payload),
            etag=None,
            last_modified=None,
            not_modified=False,
        )


def course(org_unit_id: int = 111111, *, code: str = "COURSE101") -> CourseRef:
    return CourseRef(
        org_unit_id=org_unit_id,
        code=code,
        name="Synthetic Course",
        term="1261",
        is_active=True,
    )
