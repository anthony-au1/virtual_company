"""Unit tests for campaign-target composite key handling."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import CampaignTarget
from virtual_company.repositories.campaign_target import CampaignTargetRepository
from virtual_company.repositories.dtos import CampaignTargetCreate, CampaignTargetUpdate


def session_mock() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock()
    session.scalars = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_create_and_get_use_campaign_target_composite_key() -> None:
    session = session_mock()
    repository = CampaignTargetRepository(session)
    campaign_id = uuid4()
    company_id = uuid4()

    target = await repository.create(
        CampaignTargetCreate(
            campaign_id=campaign_id,
            company_id=company_id,
            score=Decimal("0.950"),
            status="qualified",
        )
    )
    session.get.return_value = target

    assert await repository.get_by_id(campaign_id, company_id) is target
    session.get.assert_awaited_once_with(CampaignTarget, (campaign_id, company_id))
    session.add.assert_called_once_with(target)


@pytest.mark.asyncio
async def test_update_returns_none_when_campaign_target_does_not_exist() -> None:
    session = session_mock()
    session.get.return_value = None
    repository = CampaignTargetRepository(session)

    updated = await repository.update(uuid4(), uuid4(), CampaignTargetUpdate())

    assert updated is None
    session.flush.assert_not_awaited()
