from __future__ import annotations

import asyncio
import errno
import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, AssetStatus, UploadSession
from vsa_agent.recorded_video.ports import AssetStore
from vsa_agent.recorded_video.repository import JobRepository

NOW = datetime(2026, 7, 13, 9, 0, tzinfo=UTC)


def _session(
    *,
    session_id: str = "sid",
    asset_id: str = "asset-uuid",
    total_chunks: int = 2,
    filename: str = "../../evil.mkv",
    expires_at: datetime | None = None,
) -> UploadSession:
    return UploadSession(
        session_id=session_id,
        identifier="upload-identifier",
        asset_id=asset_id,
        total_chunks=total_chunks,
        filename=filename,
        temp_dir=f"ignored/{session_id}",
        status=AssetStatus.UPLOADING,
        expires_at=expires_at or NOW + timedelta(hours=1),
    )


def _asset(*, asset_id: str = "asset-uuid", extension: str = "mkv") -> Asset:
    return Asset(
        asset_id=asset_id,
        display_filename="../../evil.mkv",
        safe_filename="evil.mkv",
        size_bytes=2,
        sha256="sha256",
        mime_type="video/x-matroska",
        source_extension=extension,
        timeline_origin=NOW,
        status=AssetStatus.UPLOADING,
        created_at=NOW,
        updated_at=NOW,
    )


def _write_chunk_in_worker(
    store: LocalAssetStore,
    session: UploadSession,
    data: bytes,
) -> str:
    return asyncio.run(store.write_chunk(session, 1, data))


def _assemble_source_in_worker(store: LocalAssetStore, session: UploadSession, asset: Asset) -> str:
    return asyncio.run(store.assemble_source(session, asset))


def _write_atomic_in_worker(store: LocalAssetStore, destination: Path, data: bytes) -> str:
    return asyncio.run(store.write_atomic(destination, data))


class WindowsDiskFullError(OSError):
    @property
    def winerror(self) -> int:
        return 112


@pytest.fixture
def store(tmp_path: Path) -> LocalAssetStore:
    return LocalAssetStore(tmp_path)


async def test_store_implements_asset_store_protocol(store: LocalAssetStore) -> None:
    assert isinstance(store, AssetStore)


async def test_create_session_builds_only_the_controlled_chunk_layout(store: LocalAssetStore) -> None:
    session_dir = await store.create_session(_session())

    assert session_dir == store.root / "uploads" / "sid"
    assert (session_dir / "chunks").is_dir()


async def test_free_bytes_reports_root_filesystem_capacity(
    store: LocalAssetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = shutil._ntuple_diskusage(total=100, used=60, free=40)
    monkeypatch.setattr("vsa_agent.recorded_video.assets.shutil.disk_usage", lambda path: usage)

    assert await store.free_bytes() == 40


async def test_store_never_uses_user_filename_in_physical_path(store: LocalAssetStore) -> None:
    session = _session(total_chunks=1)

    await store.write_chunk(session, 1, b"x")
    source = Path(await store.assemble_source(session, _asset()))

    assert source.is_relative_to(store.root / "assets" / "asset-uuid")
    assert "evil" not in source.parts
    assert source.name == "original.mkv"


async def test_duplicate_chunk_is_idempotent_but_conflicting_content_is_rejected(
    store: LocalAssetStore,
) -> None:
    session = _session(total_chunks=1)

    first = await store.write_chunk(session, 1, b"same")
    second = await store.write_chunk(session, 1, b"same")

    assert first == second
    with pytest.raises(RecordedVideoError) as conflict:
        await store.write_chunk(session, 1, b"different")
    assert conflict.value.code is ErrorCode.CORRUPT_MEDIA


async def test_assemble_source_requires_all_chunks_and_atomically_publishes(
    store: LocalAssetStore,
) -> None:
    session = _session()
    await store.write_chunk(session, 1, b"a")

    with pytest.raises(RecordedVideoError) as missing:
        await store.assemble_source(session, _asset())
    assert missing.value.code is ErrorCode.CORRUPT_MEDIA

    await store.write_chunk(session, 2, b"b")
    source = Path(await store.assemble_source(session, _asset()))

    assert source.read_bytes() == b"ab"
    assert not source.with_name(f"{source.name}.tmp").exists()


async def test_concurrent_source_assembly_is_idempotent_and_leaves_no_temp_files(
    store: LocalAssetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(total_chunks=1)
    asset = _asset()
    await store.write_chunk(session, 1, b"complete-source")
    replace = os.replace
    temporary_sources: list[Path] = []

    def synchronized_replace(source: str | Path, destination: str | Path) -> None:
        temporary_sources.append(Path(source))
        replace(source, destination)

    monkeypatch.setattr("vsa_agent.recorded_video.assets.os.replace", synchronized_replace)

    results = await asyncio.gather(
        *(asyncio.to_thread(_assemble_source_in_worker, store, session, asset) for _ in range(8)),
        return_exceptions=True,
    )

    destination = store.root / "assets" / "asset-uuid" / "source" / "original.mkv"
    assert results == [str(destination)] * 8
    assert len(set(temporary_sources)) == 8
    assert destination.read_bytes() == b"complete-source"
    assert not list(destination.parent.glob("*.tmp"))


async def test_write_atomic_rejects_paths_outside_root_with_stable_error_code(
    store: LocalAssetStore,
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "escaped.bin"

    with pytest.raises(RecordedVideoError) as unsafe:
        await store.write_atomic(outside, b"no")

    assert unsafe.value.code is ErrorCode.UNSUPPORTED_MEDIA
    assert "UNSAFE_FILENAME" in str(unsafe.value)
    assert not outside.exists()


async def test_concurrent_atomic_writes_publish_only_complete_payloads_without_temp_files(
    store: LocalAssetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = store.root / "assets" / "asset-uuid" / "derived.bin"
    replace = os.replace
    temporary_sources: list[Path] = []

    def synchronized_replace(source: str | Path, target: str | Path) -> None:
        temporary_sources.append(Path(source))
        replace(source, target)

    monkeypatch.setattr("vsa_agent.recorded_video.assets.os.replace", synchronized_replace)
    results = await asyncio.gather(
        *(asyncio.to_thread(_write_atomic_in_worker, store, destination, byte * 4096) for byte in (b"a", b"b") * 4),
        return_exceptions=True,
    )

    assert results == [str(destination)] * 8
    assert len(set(temporary_sources)) == 8
    assert destination.read_bytes() in {b"a" * 4096, b"b" * 4096}
    assert not list(destination.parent.glob("*.tmp"))


async def test_unsafe_source_extension_has_stable_error_code(store: LocalAssetStore) -> None:
    session = _session(total_chunks=1)
    await store.write_chunk(session, 1, b"x")

    with pytest.raises(RecordedVideoError) as unsafe:
        await store.assemble_source(session, _asset(extension="../mkv"))

    assert unsafe.value.code is ErrorCode.UNSUPPORTED_MEDIA
    assert "UNSAFE_FILENAME" in str(unsafe.value)


@pytest.mark.parametrize("extension", ["exe", "avi"])
async def test_assemble_source_rejects_non_allowlisted_extension_without_writing_media(
    store: LocalAssetStore,
    extension: str,
) -> None:
    session = _session(total_chunks=1)
    await store.write_chunk(session, 1, b"x")

    with pytest.raises(RecordedVideoError) as unsupported:
        await store.assemble_source(session, _asset(extension=extension))

    assert unsupported.value.code is ErrorCode.UNSUPPORTED_MEDIA
    assert not (store.root / "assets" / "asset-uuid").exists()


async def test_concurrent_identical_chunk_writes_are_idempotent_without_temp_files(
    store: LocalAssetStore,
) -> None:
    session = _session(total_chunks=1)

    paths = await asyncio.gather(
        *(asyncio.to_thread(_write_chunk_in_worker, store, session, b"same") for _ in range(8))
    )

    chunk = store.root / "uploads" / "sid" / "chunks" / "000001.part"
    assert paths == [str(chunk)] * 8
    assert chunk.read_bytes() == b"same"
    assert not list(chunk.parent.glob("*.tmp"))


async def test_concurrent_conflicting_chunk_writes_report_domain_conflict_without_temp_files(
    store: LocalAssetStore,
) -> None:
    session = _session(total_chunks=1)

    results = await asyncio.gather(
        asyncio.to_thread(_write_chunk_in_worker, store, session, b"first"),
        asyncio.to_thread(_write_chunk_in_worker, store, session, b"second"),
        return_exceptions=True,
    )

    successes = [result for result in results if isinstance(result, str)]
    conflicts = [result for result in results if isinstance(result, RecordedVideoError)]
    chunk = store.root / "uploads" / "sid" / "chunks" / "000001.part"
    assert successes == [str(chunk)]
    assert len(conflicts) == 1
    assert conflicts[0].code is ErrorCode.CORRUPT_MEDIA
    assert chunk.read_bytes() in {b"first", b"second"}
    assert not list(chunk.parent.glob("*.tmp"))


async def test_open_media_range_reads_only_requested_bytes(store: LocalAssetStore) -> None:
    path = await store.write_atomic(store.root / "assets" / "asset-uuid" / "derived.bin", b"012345")

    assert await store.open_media_range(path, 1, 4) == b"123"


@pytest.mark.parametrize(
    "storage_error",
    [
        OSError(errno.ENOSPC, "No space left on device"),
        OSError(getattr(errno, "EDQUOT", 122), "Disk quota exceeded"),
        WindowsDiskFullError("The disk is full"),
    ],
)
async def test_disk_full_os_errors_have_explicit_permanent_error_code(
    store: LocalAssetStore,
    monkeypatch: pytest.MonkeyPatch,
    storage_error: OSError,
) -> None:
    def no_space(_source: Path, _destination: Path) -> None:
        raise storage_error

    monkeypatch.setattr("vsa_agent.recorded_video.assets.os.link", no_space)

    with pytest.raises(RecordedVideoError) as disk_full:
        await store.write_chunk(_session(total_chunks=1), 1, b"x")

    assert disk_full.value.code is ErrorCode.DISK_FULL
    assert "DISK_FULL" in str(disk_full.value)


async def test_unsupported_hard_link_error_is_a_configuration_error(
    store: LocalAssetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link_error = OSError(errno.EXDEV, "Invalid cross-device link")

    def unsupported_link(_source: Path, _destination: Path) -> None:
        raise link_error

    monkeypatch.setattr("vsa_agent.recorded_video.assets.os.link", unsupported_link)

    with pytest.raises(RecordedVideoError) as error:
        await store.write_chunk(_session(total_chunks=1), 1, b"x")

    assert error.value.code is ErrorCode.CONFIGURATION
    assert error.value.__cause__ is link_error


class CleanupRepository:
    def __init__(self, candidates: list[UploadSession]) -> None:
        self.candidates = candidates
        self.calls: list[datetime] = []

    async def list_expired_unreferenced_sessions(self, now: datetime) -> list[UploadSession]:
        self.calls.append(now)
        return self.candidates


async def test_cleanup_only_deletes_repository_proven_candidates(tmp_path: Path) -> None:
    expired = _session(session_id="expired", expires_at=NOW - timedelta(seconds=1))
    repository = CleanupRepository([expired])
    store = LocalAssetStore(tmp_path, cleanup_repository=repository)
    expired_dir = store.root / "uploads" / "expired"
    active_dir = store.root / "uploads" / "active"
    expired_dir.mkdir(parents=True)
    active_dir.mkdir(parents=True)
    (expired_dir / "data").write_bytes(b"old")
    (active_dir / "data").write_bytes(b"keep")

    removed = await store.cleanup_expired_sessions(NOW)

    assert repository.calls == [NOW]
    assert removed == ["expired"]
    assert not expired_dir.exists()
    assert active_dir.exists()


async def test_cleanup_rejects_unsafe_repository_candidate_without_deleting_outside(
    tmp_path: Path,
) -> None:
    unsafe = _session(session_id="../outside", expires_at=NOW - timedelta(seconds=1))
    repository = CleanupRepository([unsafe])
    store = LocalAssetStore(tmp_path / "root", cleanup_repository=repository)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_bytes(b"keep")

    with pytest.raises(RecordedVideoError) as error:
        await store.cleanup_expired_sessions(NOW)

    assert error.value.code is ErrorCode.CONFIGURATION
    assert outside.exists()


async def test_cleanup_accepts_a_real_job_repository_collaborator(tmp_path: Path) -> None:
    repository = JobRepository(tmp_path / "jobs.sqlite3", clock=lambda: NOW)
    await repository.initialize()
    session = _session(total_chunks=1, expires_at=NOW - timedelta(seconds=1))
    session.status = AssetStatus.READY
    await repository.create_upload_session(_asset(), session)
    await repository.record_chunk(session.session_id, 1, "checksum", path="000001.part")

    store = LocalAssetStore(tmp_path / "assets", cleanup_repository=repository)
    session_dir = await store.create_session(session)
    (session_dir / "data").write_bytes(b"expired")

    assert await store.cleanup_expired_sessions(NOW) == [session.session_id]
    assert not session_dir.exists()
