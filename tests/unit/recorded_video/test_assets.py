from __future__ import annotations

import errno
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vsa_agent.recorded_video.assets import LocalAssetStore
from vsa_agent.recorded_video.errors import ErrorCode, RecordedVideoError
from vsa_agent.recorded_video.models import Asset, AssetStatus, UploadSession
from vsa_agent.recorded_video.ports import AssetStore

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


async def test_unsafe_source_extension_has_stable_error_code(store: LocalAssetStore) -> None:
    session = _session(total_chunks=1)
    await store.write_chunk(session, 1, b"x")

    with pytest.raises(RecordedVideoError) as unsafe:
        await store.assemble_source(session, _asset(extension="../mkv"))

    assert unsafe.value.code is ErrorCode.UNSUPPORTED_MEDIA
    assert "UNSAFE_FILENAME" in str(unsafe.value)


async def test_open_media_range_reads_only_requested_bytes(store: LocalAssetStore) -> None:
    path = await store.write_atomic(store.root / "assets" / "asset-uuid" / "derived.bin", b"012345")

    assert await store.open_media_range(path, 1, 4) == b"123"


async def test_disk_full_os_error_has_explicit_testable_error_code(
    store: LocalAssetStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_space(_source: Path, _destination: Path) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("vsa_agent.recorded_video.assets.os.replace", no_space)

    with pytest.raises(RecordedVideoError) as disk_full:
        await store.write_chunk(_session(total_chunks=1), 1, b"x")

    assert disk_full.value.code is ErrorCode.DISK_FULL
    assert "DISK_FULL" in str(disk_full.value)


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
