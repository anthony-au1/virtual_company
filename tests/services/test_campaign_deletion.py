"""Lifecycle-safe Campaign deletion service behavior."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign
from virtual_company.services.campaign import (
    CampaignLifecycleConflictError,
    CampaignService,
)


def campaign() -> Campaign:
    now = datetime.now(UTC)
    return Campaign(
        id=uuid4(),
        name="Fintech",
        target_count=2,
        max_companies_to_research=10,
        status="DRAFT",
        keywords=["Java"],
        created_at=now,
        updated_at=now,
    )


def service_with(model: Campaign, *, has_run: bool = False) -> CampaignService:
    session = MagicMock(spec=AsyncSession)

    @asynccontextmanager
    async def transaction():
        yield

    session.begin.return_value = transaction()
    service = CampaignService(session)
    service._campaigns.get_by_id_for_update = AsyncMock(return_value=model)
    service._campaigns.delete = AsyncMock()
    service._targets.delete_by_campaign_id = AsyncMock()
    service._runs.exists_for_campaign = AsyncMock(return_value=has_run)
    service._companies.delete = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_delete_removes_only_campaign_and_campaign_owned_targets() -> None:
    model = campaign()
    service = service_with(model)

    assert await service.delete(model.id)

    service._campaigns.get_by_id_for_update.assert_awaited_once_with(model.id)
    service._runs.exists_for_campaign.assert_awaited_once_with(model.id)
    service._targets.delete_by_campaign_id.assert_awaited_once_with(model.id)
    service._campaigns.delete.assert_awaited_once_with(model)
    service._companies.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_any_research_run_blocks_deletion_without_touching_owned_data() -> None:
    model = campaign()
    service = service_with(model, has_run=True)

    with pytest.raises(CampaignLifecycleConflictError, match="used for research"):
        await service.delete(model.id)

    service._targets.delete_by_campaign_id.assert_not_awaited()
    service._campaigns.delete.assert_not_awaited()
    service._companies.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_returns_false_when_campaign_is_missing() -> None:
    model = campaign()
    service = service_with(model)
    service._campaigns.get_by_id_for_update = AsyncMock(return_value=None)

    assert await service.delete(model.id) is False

    service._runs.exists_for_campaign.assert_not_awaited()
    service._targets.delete_by_campaign_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_persistence_failure_escapes_transaction_for_rollback() -> None:
    model = campaign()
    service = service_with(model)
    service._campaigns.delete.side_effect = RuntimeError("flush failed")
    transaction_errors: list[type[BaseException] | None] = []

    @asynccontextmanager
    async def transaction():
        try:
            yield
        except BaseException as error:
            transaction_errors.append(type(error))
            raise
        else:
            transaction_errors.append(None)

    service._session.begin.return_value = transaction()

    with pytest.raises(RuntimeError, match="flush failed"):
        await service.delete(model.id)

    assert transaction_errors == [RuntimeError]
    service._targets.delete_by_campaign_id.assert_awaited_once_with(model.id)
    service._campaigns.delete.assert_awaited_once_with(model)
