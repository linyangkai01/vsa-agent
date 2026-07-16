import pytest

from vsa_agent.recorded_video.models import AssetStatus, JobStatus

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    ("status", "error_code"),
    [(429, "MODEL_RATE_LIMIT"), (503, "MODEL_5XX")],
)
async def test_provider_failures_retry_without_duplicate_documents(recorded_video_stack, status, error_code):
    job = await recorded_video_stack.upload_and_complete(f"provider-{status}.mp4")
    recorded_video_stack.provider.fail_next("vision", status)

    retry_wait = await recorded_video_stack.worker.run_once()

    assert retry_wait.status is JobStatus.RETRY_WAIT
    assert retry_wait.attempt == 1
    assert retry_wait.last_error == error_code
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.source_path(job).is_file()
    assert recorded_video_stack.temporary_files() == set()

    completed = (await recorded_video_stack.wait_completed([job]))[0]
    assert completed.status is JobStatus.COMPLETED
    assert completed.attempt == 2
    assert await recorded_video_stack.es_ids() == await recorded_video_stack.expected_segment_ids([job])


async def test_partial_elasticsearch_bulk_failure_rolls_back_then_retries(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete("partial-es.mp4")
    recorded_video_stack.projection.partial_failure_once = True

    retry_wait = await recorded_video_stack.worker.run_once()

    assert retry_wait.status is JobStatus.RETRY_WAIT
    assert retry_wait.attempt == 1
    assert retry_wait.last_error == "ES_5XX"
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.temporary_files() == set()

    completed = (await recorded_video_stack.wait_completed([job]))[0]
    assert completed.attempt == 2
    assert await recorded_video_stack.es_ids() == await recorded_video_stack.expected_segment_ids([job])


async def test_worker_kill_reclaims_expired_lease_without_duplicate_segments(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete("worker-kill.mp4")

    abandoned = await recorded_video_stack.kill_worker()
    completed = (await recorded_video_stack.wait_completed([job]))[0]

    assert abandoned.status is JobStatus.RUNNING
    assert abandoned.attempt == 1
    assert completed.status is JobStatus.COMPLETED
    assert completed.attempt == 2
    assert await recorded_video_stack.es_ids() == await recorded_video_stack.expected_segment_ids([job])
    assert recorded_video_stack.temporary_files() == set()


async def test_disk_full_rejects_chunk_without_job_or_residual_file(recorded_video_stack):
    ticket = await recorded_video_stack.begin_upload("disk-full.mp4")
    type(recorded_video_stack.store).disk_full = True

    response = await recorded_video_stack.upload_chunk(ticket, b"video")

    assert response.status_code == 507
    assert response.json()["detail"]["error_code"] == "DISK_FULL"
    assert await recorded_video_stack.job_count(ticket.asset_id) == 0
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.files_for(ticket.asset_id) == set()
    assert recorded_video_stack.temporary_files() == set()


async def test_corrupt_media_is_terminal_and_preserves_source(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete("corrupt.mkv", content=b"CORRUPT-media")

    failed = await recorded_video_stack.worker.run_once()

    assert failed.status is JobStatus.FAILED
    assert failed.attempt == 1
    assert failed.last_error == "CORRUPT_MEDIA"
    assert (await recorded_video_stack.repository.get_asset(job.asset_id)).status is AssetStatus.FAILED
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.source_path(job).read_bytes() == job.content
    assert recorded_video_stack.temporary_files() == set()


async def test_cancelled_running_job_is_cleaned_after_lease_reclaim(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete("cancel.mp4")
    claimed = await recorded_video_stack.kill_worker()

    response = await recorded_video_stack.client.post(f"/api/v1/jobs/{job.job_id}/cancel")
    cancelled = await recorded_video_stack.worker.run_once()

    assert response.status_code == 200
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.attempt == claimed.attempt == 1
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.source_path(job).is_file()
    assert recorded_video_stack.temporary_files() == set()


async def test_delete_interruption_resumes_without_orphans(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete("delete.mp4")
    await recorded_video_stack.wait_completed([job])
    expected_ids = await recorded_video_stack.expected_segment_ids([job])
    recorded_video_stack.projection.delete_failure_once = True

    interrupted = await recorded_video_stack.client.delete(f"/api/v1/videos/{job.asset_id}")

    assert interrupted.status_code == 500
    assert await recorded_video_stack.es_ids() == expected_ids
    assert await recorded_video_stack.job_count(job.asset_id) == 1
    assert recorded_video_stack.files_for(job.asset_id)

    resumed = await recorded_video_stack.client.delete(f"/api/v1/videos/{job.asset_id}")
    repeated = await recorded_video_stack.client.delete(f"/api/v1/videos/{job.asset_id}")

    assert resumed.status_code == repeated.status_code == 204
    assert (await recorded_video_stack.repository.get_asset(job.asset_id)).status is AssetStatus.DELETED
    assert await recorded_video_stack.job_count(job.asset_id) == 0
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.files_for(job.asset_id) == set()
    assert recorded_video_stack.temporary_files() == set()
