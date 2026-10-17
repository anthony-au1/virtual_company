"""Campaign definition immutability after the first research run starts."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from virtual_company.db.models import Campaign
from virtual_company.repositories.campaign import CampaignRepository
from virtual_company.repositories.dtos import CampaignUpdate
from virtual_company.services.campaign import CampaignSealedError, CampaignService


def campaign(*, sealed_at: datetime | None = None) -> Campaign:
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
        sealed_at=sealed_at,
    )


def service_with(campaign_model: Campaign) -> CampaignService:
    session = MagicMock(spec=AsyncSession)
    service = CampaignService(session)
    service._campaigns.get_by_id_for_update = AsyncMock(return_value=campaign_model)
    service._campaigns.update = AsyncMock(return_value=campaign_model)
    return service


@pytest.mark.asyncio
async def test_seal_for_research_persists_first_start_time() -> None:
    model = campaign()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=model)
    session.flush = AsyncMock()

    result = await CampaignRepository(session).seal_for_research(model.id)

    assert result is model
    assert model.sealed_at is not None
    assert model.sealed_at.tzinfo is not None
    session.scalar.assert_awaited_once()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_campaign_definition_is_editable_before_first_run() -> None:
    model = campaign()
    service = service_with(model)

    result = await service.update(model.id, CampaignUpdate(target_market="Australia"))

    assert result is model
    service._campaigns.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_sealed_campaign_rejects_definition_changes_but_allows_status() -> None:
    model = campaign(sealed_at=datetime.now(UTC))
    service = service_with(model)

    with pytest.raises(CampaignSealedError, match="research definition is sealed"):
        await service.update(model.id, CampaignUpdate(keywords=["Go"]))
    service._campaigns.update.assert_not_awaited()

    result = await service.update(model.id, CampaignUpdate(status="PAUSED"))
    assert result is model
    service._campaigns.update.assert_awaited_once()
