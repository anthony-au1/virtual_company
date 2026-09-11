"""Unit tests for campaign repository behavior."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign
from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.dtos import CampaignCreate, CampaignUpdate


def session_mock() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.scalars = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_flushes_and_refreshes_without_committing() -> None:
    session = session_mock()
    repository = CampaignRepository(session)

    campaign = await repository.create(
        CampaignCreate(name="APAC SaaS", target_count=25, status="DRAFT")
    )

    assert campaign.name == "APAC SaaS"
    session.add.assert_called_once_with(campaign)
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(campaign)
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_get_list_and_partial_update() -> None:
    session = session_mock()
    campaign = Campaign(name="Original", target_count=10, status="DRAFT")
    campaign_id = uuid4()
    session.get.return_value = campaign
    session.scalars.return_value = [campaign]
    repository = CampaignRepository(session)

    assert await repository.get_by_id(campaign_id) is campaign
    assert await repository.list() == [campaign]

    updated = await repository.update(
        campaign_id, CampaignUpdate(name="Renamed", target_count=None)
    )

    assert updated is campaign
    assert campaign.name == "Renamed"
    assert campaign.target_count == 10
    session.flush.assert_awaited_once()
    session.refresh.assert_awaited_once_with(campaign)


@pytest.mark.asyncio
async def test_update_returns_none_when_campaign_does_not_exist() -> None:
    session = session_mock()
    session.get.return_value = None
    repository = CampaignRepository(session)

    updated = await repository.update(uuid4(), CampaignUpdate(status="PAUSED"))

    assert updated is None
    session.flush.assert_not_awaited()
