import os
import tempfile
import time

from fastapi.testclient import TestClient

from app.api import main


def test_job_persistence_restart(monkeypatch):
    db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db.close()
    monkeypatch.setenv("SATQUERY_DB", db.name)
    os.environ["SATQUERY_DB"] = db.name
    import importlib
    from app.storage import jobs, history
    importlib.reload(jobs)
    importlib.reload(history)
    importlib.reload(main)
    job_id = "testjob123"
    jobs.create_job(job_id, "test query", {"operation": "INDEX_STATS"}, {"type": "Polygon", "coordinates": []})
    jobs.update_job(job_id, status="processing")
    jobs.update_job(job_id, status="completed", finished=jobs._now())
    importlib.reload(jobs)
    j = jobs.get_job(job_id)
    assert j is not None
    assert j["status"] == "completed"
    try:
        os.unlink(db.name)
    except Exception:
        pass
    try:
        os.unlink(db.name + "-wal")
    except Exception:
        pass
    try:
        os.unlink(db.name + "-shm")
    except Exception:
        pass



def test_mark_interrupted():
    db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db.close()
    os.environ["SATQUERY_DB"] = db.name
    import importlib
    from app.storage import jobs
    importlib.reload(jobs)
    job_id = "int1"
    jobs.create_job(job_id, "q", {"operation": "INDEX_STATS"}, {})
    jobs.update_job(job_id, status="processing")
    c = jobs.mark_interrupted_on_startup()
    assert c >= 1
    j = jobs.get_job(job_id)
    assert j["status"] == "interrupted"
    try:
        os.unlink(db.name)
    except Exception:
        pass
    try:
        os.unlink(db.name + "-wal")
    except Exception:
        pass
    try:
        os.unlink(db.name + "-shm")
    except Exception:
        pass



def test_invalid_transition_prevented():
    db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db.close()
    os.environ["SATQUERY_DB"] = db.name
    import importlib
    from app.storage import jobs
    importlib.reload(jobs)
    job_id = "t1"
    jobs.create_job(job_id, "q", {"operation": "INDEX_STATS"}, {})
    jobs.update_job(job_id, status="processing")
    jobs.update_job(job_id, status="completed")
    jobs.update_job(job_id, status="processing")  # should be ignored
    j = jobs.get_job(job_id)
    assert j["status"] == "completed"
    try:
        os.unlink(db.name)
    except Exception:
        pass
    try:
        os.unlink(db.name + "-wal")
    except Exception:
        pass
    try:
        os.unlink(db.name + "-shm")
    except Exception:
        pass

