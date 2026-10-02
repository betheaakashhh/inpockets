import asyncio

import pytest

from app.core.exceptions import AppException
from app.core.distributed_lock import (
    DistributedOperationLock,
    OperationAlreadyInProgressError,
)


@pytest.mark.asyncio
async def test_same_provider_operation_cannot_run_concurrently():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def first_operation():
        async with DistributedOperationLock("test:provider-operation:shared"):
            entered.set()
            await release.wait()

    first = asyncio.create_task(first_operation())
    await entered.wait()

    with pytest.raises(OperationAlreadyInProgressError):
        async with DistributedOperationLock("test:provider-operation:shared"):
            pass

    release.set()
    await first


@pytest.mark.asyncio
async def test_provider_operation_lock_is_released_after_failure():
    key = "test:provider-operation:failure"

    with pytest.raises(RuntimeError):
        async with DistributedOperationLock(key):
            raise RuntimeError("provider failed")

    async with DistributedOperationLock(key):
        pass


@pytest.mark.asyncio
async def test_lock_contention_is_a_retryable_409_app_exception():
    key = "test:provider-operation:contention"

    async with DistributedOperationLock(key):
        with pytest.raises(OperationAlreadyInProgressError) as exc_info:
            async with DistributedOperationLock(key):
                pass

    assert isinstance(exc_info.value, AppException)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "OPERATION_IN_PROGRESS"
    assert key not in exc_info.value.message


def test_identity_start_and_capture_share_one_lock_key():
    from uuid import uuid4

    from app.services.identity_verification import _identity_lock_key

    user_id = uuid4()
    assert _identity_lock_key(user_id) == f"provider-operation:identity:{user_id}"
