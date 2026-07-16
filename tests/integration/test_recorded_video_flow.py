import asyncio

import pytest

from vsa_agent.recorded_video.models import JobStatus

pytestmark = pytest.mark.integration


async def test_three_uploads_create_exactly_one_document_per_segment(recorded_video_stack):
    jobs = await asyncio.gather(
        *(recorded_video_stack.upload_and_complete(name) for name in ("a.mp4", "b.mp4", "c.mkv"))
    )

    completed = await recorded_video_stack.wait_completed(jobs)

    assert await recorded_video_stack.es_ids() == await recorded_video_stack.expected_segment_ids(jobs)
    persisted_jobs = await asyncio.gather(*(recorded_video_stack.repository.get_job(job.job_id) for job in jobs))
    assert all(job.status is JobStatus.COMPLETED and job.attempt == 1 for job in completed)
    assert all(job.status is JobStatus.COMPLETED and job.attempt == 1 for job in persisted_jobs)
    segments_by_asset = [await recorded_video_stack.repository.list_segments(job.asset_id) for job in jobs]
    assert [len(segments) for segments in segments_by_asset] == [2, 2, 2]
    assert sum(map(len, segments_by_asset)) == 6
    assert recorded_video_stack.temporary_files() == set()


async def test_repeated_chunk_and_complete_are_idempotent(recorded_video_stack):
    job = await recorded_video_stack.upload_and_complete(
        "retry.mp4",
        content=b"idempotent-video",
        duplicate_chunk=True,
        duplicate_complete=True,
    )

    completed = (await recorded_video_stack.wait_completed([job]))[0]

    assert completed.attempt == 1
    assert await recorded_video_stack.job_count(job.asset_id) == 1
    assert recorded_video_stack.source_path(job).read_bytes() == job.content
    assert await recorded_video_stack.es_ids() == await recorded_video_stack.expected_segment_ids([job])
    assert recorded_video_stack.temporary_files() == set()
