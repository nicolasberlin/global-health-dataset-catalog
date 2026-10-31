
import pytest
from app.db.collection.traces.reading import read_collection_trace
from app.db.collection.traces.sanitization import safe_url
from app.db.collection.traces.writing import write_collection_trace
from helpers.workflows import claimed, observation

from collector.storage.models import CollectionReport, CollectionResult

pytestmark = pytest.mark.anyio


async def test_reinitialization_preserves_completed_job(database):
    job, version = await claimed(database)
    await database.complete_collection_job(
        job["id"],
        CollectionResult([], report=CollectionReport(verification_complete=True)),
        expected_updated_at=version,
    )
    await database.close_database_pool()
    await database.open_database_pool()
    await database.init_database()
    stored = await database.get_collection_job(job["id"])
    assert stored["status"] == "done" and stored["outcome"] == "empty"
    assert (await read_collection_trace(job["id"], "alice"))["method_attempts"] == []


async def test_ipv6_diagnostic_urls_survive_storage_and_repeated_sanitization(database):
    job, version = await claimed(database)
    raw_url = "https://user:secret@[2001:db8::1]:8443/data?token=secret&id=123#private"
    expected = "https://[2001:db8::1]:8443/data?id=123"
    value = observation()
    value.update(requested_url=raw_url, final_url=raw_url)
    value["checks"] = [{"url": raw_url, "resource_key": raw_url, "status": "available"}]

    assert await write_collection_trace(job["id"], version, 0, value)
    trace = await read_collection_trace(job["id"], "alice")
    method = trace["method_attempts"][0]
    assert method["requested_url"] == method["final_url"] == expected
    assert method["checks"][0]["url"] == method["checks"][0]["resource_key"] == expected
    assert "secret" not in str(trace) and "private" not in str(trace)

    assert await write_collection_trace(job["id"], version, 0, method)
    reread = (await read_collection_trace(job["id"], "alice"))["method_attempts"][0]
    assert reread["requested_url"] == reread["final_url"] == expected
    assert reread["checks"] == method["checks"]
    assert safe_url("https://[invalid-address]/data") == ""
    assert safe_url("https://[2001:db8::1]:invalid/data") == ""
