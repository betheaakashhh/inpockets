import asyncio

import pytest

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
