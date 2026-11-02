import base64

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from pricefinder.config import Settings
from pricefinder.core.models import Query, SellerType
from pricefinder.fetch.http import HttpClient
from pricefinder.providers.base import ProviderContext
from pricefinder.providers.goods.walmart import WalmartProvider, sign_request

ITEMS = {
    "items": [
        {
            "itemId": 1,
            "name": "Sony WH-1000XM5 Headphones",
            "salePrice": 299.0,
            "msrp": 399.99,
            "upc": "027242923447",
            "productUrl": "https://www.walmart.com/ip/1",
            "stock": "Available",
            "freeShippingOver35Dollars": True,
            "customerRating": "4.6",
            "numReviews": 120,
            "marketplace": False,
        },
        {
            "itemId": 2,
            "name": "Sony WH-1000XM5 (marketplace)",
            "salePrice": 259.0,
            "standardShipRate": 7.5,
            "productUrl": "https://www.walmart.com/ip/2",
            "stock": "Available",
            "marketplace": True,
            "sellerInfo": "AudioDeals LLC",
        },
    ]
}


@pytest.fixture
def key_pair(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem_path = tmp_path / "wm.pem"
    pem_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return key, pem_path


def test_signature_verifies(key_pair):
    key, pem_path = key_pair
    headers = sign_request("cid", "1", pem_path.read_bytes(), timestamp_ms=1700000000000)
    canonical = b"cid\n1700000000000\n1\n"
    key.public_key().verify(
        base64.b64decode(headers["WM_SEC.AUTH_SIGNATURE"]), canonical, padding.PKCS1v15(), hashes.SHA256()
    )
    assert headers["WM_CONSUMER.ID"] == "cid" and headers["WM_SEC.KEY_VERSION"] == "1"


@pytest.mark.asyncio
@respx.mock
async def test_walmart_search(key_pair):
    _, pem_path = key_pair
    route = respx.get("https://developer.api.walmart.com/api-proxy/service/affil/product/v2/search").mock(
        return_value=httpx.Response(200, json=ITEMS)
    )
    settings = Settings(walmart_consumer_id="cid", walmart_private_key_path=str(pem_path))
    ctx = ProviderContext(settings=settings, http=HttpClient(settings))
    offers = await WalmartProvider().search(Query(raw="x", item="sony wh-1000xm5"), ctx)
    await ctx.http.aclose()

    req = route.calls[0].request
    assert req.headers["WM_CONSUMER.ID"] == "cid" and req.headers["WM_SEC.AUTH_SIGNATURE"]
    assert "query=sony+wh-1000xm5" in str(req.url)
    assert len(offers) == 2
    first, second = offers
    assert first.seller.type == SellerType.RETAILER and first.shipping.amount == 0
    assert second.seller.type == SellerType.RESELLER and second.seller.name == "AudioDeals LLC"
    assert second.shipping.amount == 7.5
    assert first.identifiers["upc"] == "027242923447"
