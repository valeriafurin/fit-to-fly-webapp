from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from f2f.models import F2F, PillarTemplate, Question
from f2f.store import Store
from tests.conftest import create_f2f, svc


def _f2f() -> F2F:
    t = PillarTemplate(
        key="Digital",
        scenario="x",
        thresholds={"IE1": 1, "IE2": 2, "Senior IE": 3},
        questions=[Question(id="q1", section="S", text="Q", priority=1)],
    )
    return F2F(
        template=t,
        ie_level="IE1",
        candidate_name="C",
        candidate_email="c@x.com",
        date="2026-11-10",
        start_time="10:00",
        tl_name="T",
        tl_email="t@x.com",
    )


def test_ttl_purge() -> None:
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    store = Store(ttl_hours=12, clock=lambda: now[0])
    f = _f2f()
    f.created_at = now[0]
    store.add(f)
    purged: list[str] = []
    store.on_purge.append(purged.append)
    now[0] += timedelta(hours=11)
    assert store.get(f.id) is not None
    now[0] += timedelta(hours=2)
    assert store.get(f.id) is None
    assert purged == [f.id]


def test_close_and_purge_removes_everything(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    token = f.panelists[0].token
    client.post(f"/admin/f2f/{f2f_id}/invite")
    assert svc(client).jobs.for_f2f(f2f_id)
    r = client.post(f"/admin/f2f/{f2f_id}/purge", follow_redirects=False)
    assert r.status_code == 303
    assert svc(client).store.get(f2f_id) is None
    assert svc(client).jobs.for_f2f(f2f_id) == []
    assert client.get(f"/panel/{token}").status_code == 404
    assert client.get(f"/admin/f2f/{f2f_id}").status_code == 404


def test_templates_file_has_no_candidate_data(client: TestClient) -> None:
    create_f2f(client)
    text = svc(client).settings.templates_path.read_text()
    assert "Casey" not in text and "casey@example.com" not in text
