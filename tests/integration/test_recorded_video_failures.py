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

    assert retry_wait.status is JobStatus.RETRY_WAIT, retry_wait.last_error
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
    assert recorded_video_stack.projection.partial_backend is recorded_video_stack.projection.backend
    recorded_video_stack.inject_partial_bulk_failure()

    retry_wait = await recorded_video_stack.worker.run_once()

    assert retry_wait.status is JobStatus.RETRY_WAIT, retry_wait.last_error
    assert retry_wait.attempt == 1
    assert retry_wait.last_error == "ES_5XX"
    assert recorded_video_stack.partial_bulk_failures == 1
    assert len(recorded_video_stack.partial_bulk_success_ids) == 1
    assert await recorded_video_stack.es_ids() == set()
    assert recorded_video_stack.temporary_files() == set()

    completed = (await recorded_video_stack.wait_completed([job]))[0]
    assert completed.attempt == 2
    expected_ids = await recorded_video_stack.expected_segment_ids([job])
    assert recorded_video_stack.partial_bulk_success_ids < expected_ids
    final_ids = await recorded_video_stack.es_ids()
    assert final_ids == expected_ids
    assert len(final_ids) == len(expected_ids)


async def test_worker_kill_reclaims_expired_lease_without_duplicate_segments(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete("worker-kill.mp4")

    crash = await recorded_video_stack.kill_worker(job)

    assert crash.heartbeat_seen is True
    assert crash.abandoned.status is JobStatus.RUNNING
    assert crash.abandoned.attempt == 1
    assert crash.recovered.status is JobStatus.COMPLETED
    assert crash.recovered.attempt == 2
    assert await recorded_video_stack.projection_attempts() == {2}
    assert recorded_video_stack.attempt_files(job.asset_id, 1) == set()
    assert await recorded_video_stack.es_ids() == await recorded_video_stack.expected_segment_ids([job])
    assert recorded_video_stack.temporary_files() == set()


async def test_disk_full_rejects_chunk_without_job_or_residual_file(recorded_video_stack):
    ticket = await recorded_video_stack.begin_upload("disk-full.mp4")
    type(recorded_video_stack.store).disk_full = True

    response = await recorded_video_stack.upload_chunk(ticket, b"video")

    assert response.status_code == 507
    assert response.json()["detail"]["error_code"] == "DISK_FULL"
    assert await recorded_video_stack.job_count(ticket.asset_id) == 0
    assert await recorded_video_stack.reservation_count(ticket.session_id) == 0
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

    running, response, cancelled = await recorded_video_stack.cancel_running(job)

    assert response.status_code == 200
    assert running.status is JobStatus.RUNNING
    assert cancelled.status is JobStatus.CANCELLED
    assert cancelled.attempt == running.attempt == 1
    assert await recorded_video_stack.projection_attempts() == set()
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
