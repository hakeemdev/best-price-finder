from decimal import Decimal

import httpx
import pytest
import respx

from pricefinder.config import Settings
from pricefinder.core.models import Query, SellerType
from pricefinder.fetch.http import HttpClient
from pricefinder.providers.base import ProviderContext
from pricefinder.providers.goods.bestbuy import BestBuyProvider

PRODUCTS = {
    "products": [
        {
            "sku": 6505727,
            "name": "Sony WH-1000XM5 Wireless Headphones - Black",
            "salePrice": 279.99,
            "regularPrice": 399.99,
            "onlineAvailability": True,
            "inStoreAvailability": True,
            "url": "https://www.bestbuy.com/site/6505727.p",
            "upc": "027242923447",
            "modelNumber": "WH1000XM5/B",
            "customerReviewAverage": 4.7,
            "customerReviewCount": 3200,
            "condition": "new",
            "freeShipping": True,
        },
        {
            "sku": 6505728,
            "name": "Sony WH-1000XM5 - Open Box",
            "salePrice": 219.99,
            "onlineAvailability": True,
            "inStoreAvailability": False,
            "url": "https://www.bestbuy.com/site/6505728.p",
            "condition": "open-box",
            "shippingCost": 5.99,
            "freeShipping": False,
        },
    ]
}
STORES = {
    "products": [
        {
            "sku": 6505727,
            "salePrice": 279.99,
            "stores": [
                {
                    "storeId": 1021,
                    "name": "Austin South",
                    "distance": 3.1,
                    "city": "Austin",
                    "region": "TX",
                    "postalCode": "78745",
                },
                {
                    "storeId": 1022,
                    "name": "Round Rock",
                    "distance": 18.4,
                    "city": "Round Rock",
                    "region": "TX",
                    "postalCode": "78664",
                },
            ],
        }
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_bestbuy_online_and_store_offers():
    search = respx.get(url__regex=r"https://api\.bestbuy\.com/v1/products\(\(search=.*").mock(
        return_value=httpx.Response(200, json=PRODUCTS)
    )
    stores = respx.get(
        url__regex=r"https://api\.bestbuy\.com/v1/products\(sku=6505727\)\+stores\(area\(78701,\d+\)\).*"
    ).mock(return_value=httpx.Response(200, json=STORES))
    settings = Settings(bestbuy_api_key="k", home_postal_code="78701")
    ctx = ProviderContext(settings=settings, http=HttpClient(settings))
    offers = await BestBuyProvider().search(Query(raw="x", item="sony wh-1000xm5", max_drive_km=40), ctx)
    await ctx.http.aclose()

    assert search.called and stores.called
    online = [o for o in offers if o.seller.type == SellerType.RETAILER]
    local = [o for o in offers if o.seller.type == SellerType.LOCAL_STORE]
    assert len(online) == 2 and len(local) == 2
    assert online[0].identifiers["upc"] == "027242923447"
    assert online[0].shipping.amount == 0 and online[1].shipping.amount == Decimal("5.99")
    assert online[1].condition.value == "open_box"
    assert local[0].distance_km == 5.0 and local[0].location.city == "Austin"
    assert "search=sony&search=wh-1000xm5" in str(search.calls[0].request.url)
    assert "apiKey=k" in str(search.calls[0].request.url)


@pytest.mark.asyncio
@respx.mock
async def test_bestbuy_skips_store_lookup_without_postal_code():
    respx.get(url__regex=r"https://api\.bestbuy\.com/v1/products\(\(search=.*").mock(
        return_value=httpx.Response(200, json=PRODUCTS)
    )
    stores = respx.get(url__regex=r".*\+stores.*").mock(return_value=httpx.Response(200, json=STORES))
    settings = Settings(bestbuy_api_key="k", home_postal_code=None)
    ctx = ProviderContext(settings=settings, http=HttpClient(settings))
    offers = await BestBuyProvider().search(Query(raw="x", item="sony wh-1000xm5"), ctx)
    await ctx.http.aclose()
    assert not stores.called and len(offers) == 2
