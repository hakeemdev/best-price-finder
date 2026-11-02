from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from pricefinder.config import Settings
from pricefinder.core.llm_parser import LLMQueryParser, ParsedQuery, build_parser
from pricefinder.core.models import Condition, Vertical
from pricefinder.core.query import RuleBasedQueryParser

TODAY = date(2026, 11, 2)


class FakeMessages:
    def __init__(self, parsed=None, exc=None, stop_reason="end_turn"):
        self.parsed, self.exc, self.stop_reason = parsed, exc, stop_reason
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return SimpleNamespace(parsed_output=self.parsed, stop_reason=self.stop_reason)


def _client(**kw):
    return SimpleNamespace(messages=FakeMessages(**kw))


def test_llm_result_is_merged_over_rules():
    parsed = ParsedQuery(
        vertical="goods",
        item="LG C4 65 inch OLED TV",
        brand="LG",
        model="OLED65C4",
        max_price=1500,
        conditions=["new", "open_box"],
        location_text="Austin, TX",
        wants_pickup_today=True,
        attributes={"size": "65"},
    )
    client = _client(parsed=parsed)
    parser = LLMQueryParser(Settings(anthropic_api_key="x"), client=client, model="claude-opus-5-5")
    q = parser.parse("a 65 inch lg oled tv under 1500 i can grab today in Austin TX", today=TODAY)
    assert q.vertical == Vertical.GOODS
    assert q.item == "LG C4 65 inch OLED TV"
    assert q.max_price and q.max_price.amount == Decimal("1500")
    assert q.conditions == [Condition.NEW, Condition.OPEN_BOX]
    assert q.location and q.location.text == "Austin, TX"
    assert q.include_online is False and q.attributes["pickup_today"] is True
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is ParsedQuery
    assert "2026-11-02" in call["messages"][0]["content"]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_llm_travel_fields():
    parsed = ParsedQuery(
        vertical="flight",
        item="AUS -> LHR",
        origin_iata="aus",
        destination_text="London",
        destination_iata="lhr",
        start_date=date(2027, 3, 10),
        end_date=date(2027, 3, 20),
        adults=2,
        cabin="business",
    )
    parser = LLMQueryParser(Settings(), client=_client(parsed=parsed))
    q = parser.parse("two business class tickets austin to london march 10-20", today=TODAY)
    assert q.vertical == Vertical.FLIGHT
    assert q.origin and q.origin.iata == "AUS"
    assert q.destination and q.destination.iata == "LHR"
    assert q.dates and q.dates.nights == 10
    assert q.travelers.adults == 2 and q.cabin == "business"


def test_falls_back_to_rules_on_error_and_refusal():
    text = "flights SFO to JFK Dec 12 to Dec 19"
    expected = RuleBasedQueryParser().parse(text, today=TODAY)
    for client in (_client(exc=RuntimeError("boom")), _client(parsed=None, stop_reason="refusal")):
        q = LLMQueryParser(Settings(), client=client).parse(text, today=TODAY)
        assert q.model_dump() == expected.model_dump()


def test_build_parser_respects_mode(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(build_parser(Settings(query_parser="rules", anthropic_api_key="k")), RuleBasedQueryParser)
    assert isinstance(build_parser(Settings(query_parser="auto")), RuleBasedQueryParser)
    assert isinstance(build_parser(Settings(query_parser="auto", anthropic_api_key="k")), LLMQueryParser)
    assert isinstance(build_parser(Settings(query_parser="llm")), LLMQueryParser)
