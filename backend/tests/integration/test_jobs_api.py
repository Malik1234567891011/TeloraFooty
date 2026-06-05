from __future__ import annotations

from app.services import job_service


def test_job_lifecycle(client):
    job = job_service.create_job("demo_clip", message="queued")
    resp = client.get(f"/api/jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job.id
    assert body["status"] == "queued"
    assert body["progress"] == 0

    job_service.update_job(job.id, status="completed", progress=100, message="done")
    body2 = client.get(f"/api/jobs/{job.id}").json()
    assert body2["status"] == "completed"
    assert body2["progress"] == 100
    assert body2["completed_at"] is not None


def test_job_not_found(client):
    resp = client.get("/api/jobs/nope")
    assert resp.status_code == 404
