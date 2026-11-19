from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import create_f2f, svc

ADMIN_ROUTES = [
    ("get", "/admin"),
    ("get", "/admin/templates/Digital"),
    ("post", "/admin/templates/Digital"),
    ("get", "/admin/f2f/new"),
    ("post", "/admin/f2f"),
]


def test_admin_routes_require_tl(client: TestClient) -> None:
    for method, path in ADMIN_ROUTES:
        r = getattr(client, method)(path)
        assert r.status_code == 403, path


def test_wrong_passcode_rejected(client: TestClient) -> None:
    r = client.post("/login", data={"passcode": "nope"})
    assert r.status_code == 401
    assert client.get("/admin").status_code == 403


def test_f2f_routes_require_tl(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    client.cookies.clear()
    for path in [
        f"/admin/f2f/{f2f_id}",
        f"/admin/f2f/{f2f_id}/collate",
        f"/admin/f2f/{f2f_id}/rollout",
        f"/admin/f2f/{f2f_id}/collated.pdf",
    ]:
        assert client.get(path).status_code == 403, path
    assert client.post(f"/admin/f2f/{f2f_id}/purge").status_code == 403
    assert client.post(f"/admin/f2f/{f2f_id}/invite").status_code == 403
    assert svc(client).store.get(f2f_id) is not None


def test_panel_token_does_not_grant_admin(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    client.cookies.clear()
    token = f.panelists[0].token
    assert client.get(f"/panel/{token}").status_code == 200
    assert client.get("/admin").status_code == 403
    assert client.get(f"/admin/f2f/{f2f_id}").status_code == 403


def test_panel_sees_only_own_assessment(client: TestClient) -> None:
    f2f_id = create_f2f(client)
    f = svc(client).store.get(f2f_id)
    assert f
    a, b = f.invitees
    q = f.template.questions[0]
    b.assessment.notes[q.id] = "SECRET-NOTE-OF-B"
    client.cookies.clear()
    page = client.get(f"/panel/{a.token}").text
    assert "SECRET-NOTE-OF-B" not in page
    assert a.name in page and b.email not in page
    assert "Close &amp; purge" not in page


def test_unknown_token_404(client: TestClient) -> None:
    assert client.get("/panel/not-a-real-token").status_code == 404


def test_logout_revokes_session(client: TestClient) -> None:
    create_f2f(client)
    assert client.get("/admin").status_code == 200
    client.post("/logout")
    assert client.get("/admin").status_code == 403
