from app.domain.models import ProductCatalogEntry
from app.infrastructure.kamis_catalog_overrides import apply_verified_overrides
from tests.infrastructure.test_kamis_client import CATALOG_ROW


def test_verified_retail_rank_is_added_without_dropping_existing_metadata():
    entry = ProductCatalogEntry.from_api({**CATALOG_ROW, "itemcode": "430", "kindcode": "00", "retail_productrankcode": []})
    result = apply_verified_overrides([entry])[0]
    assert "04" in result.retail_rank_codes
    assert result.wholesale_rank_codes == entry.wholesale_rank_codes
    assert entry.retail_rank_codes == ()


def test_unverified_entry_is_unchanged():
    entry = ProductCatalogEntry.from_api(CATALOG_ROW)
    assert apply_verified_overrides([entry]) == [entry]
