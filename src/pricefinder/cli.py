"""`pf` command line interface."""

from __future__ import annotations

import asyncio
import json
import logging

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .core.engine import SearchEngine
from .core.llm_parser import build_parser
from .core.models import CardHolding, SearchResult, UserProfile, Vertical
from .core.query import RuleBasedQueryParser
from .core.registry import default_registry
from .storage.repository import Repository

app = typer.Typer(help="Hunt down the best effective price for anything.", no_args_is_help=True)
profile_app = typer.Typer(help="Manage saved profiles (cards, memberships, home location).")
app.add_typer(profile_app, name="profile")
console = Console()


def _repo() -> Repository:
    return Repository()


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )


@app.command()
def search(
    text: str = typer.Argument(
        ..., help='e.g. "sony wh-1000xm5 under $300 near Austin" or "flights SFO to JFK Dec 12 to Dec 19"'
    ),
    vertical: Vertical | None = typer.Option(None, help="Force a vertical instead of auto-detecting"),
    provider: list[str] = typer.Option([], "--provider", "-p", help="Only query these providers"),
    profile: str = typer.Option("default", help="Profile id for rewards / memberships"),
    limit: int = typer.Option(15, help="Rows to display"),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
    no_store: bool = typer.Option(False, help="Do not record results to the price history DB"),
) -> None:
    """Search every available source and rank by effective price."""
    query = build_parser().parse(text)
    if vertical:
        query.vertical = vertical
    query.profile_id = profile
    engine = SearchEngine(repository=None if no_store else _repo())
    result = asyncio.run(engine.search(query, providers=provider or None))
    if as_json:
        console.print_json(result.model_dump_json(exclude={"offers": {"__all__": {"offer": {"raw"}}}}))
        return
    _render(result, limit)


@app.command()
def parse(text: str, rules_only: bool = typer.Option(False, help="Skip the LLM parser even if configured")) -> None:
    """Show how free text is interpreted (vertical, dates, locations, constraints)."""
    parser = RuleBasedQueryParser() if rules_only else build_parser()
    console.print_json(parser.parse(text).model_dump_json())


@app.command()
def providers() -> None:
    """List providers, what they cover, and whether they are configured."""
    settings = get_settings()
    table = Table(title="Providers")
    for col in ("name", "kind", "verticals", "status", "description"):
        table.add_column(col)
    for p in sorted(default_registry().all(), key=lambda p: p.name):
        if p.is_available(settings):
            status = "[green]ready[/green]"
        elif getattr(p, "planned_approach", None):
            status = "[yellow]planned[/yellow]"
        elif p.opt_in:
            status = "[yellow]opt-in[/yellow]"
        else:
            status = f"[red]missing {', '.join(p.missing_settings(settings))}[/red]"
        table.add_row(p.name, p.kind.value, ", ".join(sorted(v.value for v in p.verticals)), status, p.description)
    console.print(table)


@app.command()
def history(item: str, days: int = 90, limit: int = 30) -> None:
    """Show recorded prices for an item from past searches."""
    rows = _repo().history(item, days=days, limit=limit)
    if not rows:
        console.print("no history yet")
        return
    table = Table(title=f"Price history: {item}")
    for col in ("observed", "provider", "seller", "title", "sticker", "effective"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r.observed_at.strftime("%Y-%m-%d %H:%M"),
            r.provider,
            r.seller,
            r.title[:60],
            f"{r.sticker_total:.2f}",
            f"{r.effective_total:.2f}",
        )
    console.print(table)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Run the HTTP API."""
    import uvicorn

    uvicorn.run("pricefinder.api.app:app", host=host, port=port, reload=reload)


@profile_app.command("show")
def profile_show(profile_id: str = "default") -> None:
    p = _repo().get_profile(profile_id) or UserProfile(id=profile_id)
    console.print_json(p.model_dump_json())


@profile_app.command("add-card")
def profile_add_card(card_id: str, profile_id: str = "default") -> None:
    """Add a card from data/cards.yaml (e.g. chase_sapphire_preferred) to a profile."""
    repo = _repo()
    p = repo.get_profile(profile_id) or UserProfile(id=profile_id)
    if card_id not in {c.card_id for c in p.cards}:
        p.cards.append(CardHolding(card_id=card_id))
    repo.save_profile(p)
    console.print(f"profile {profile_id}: cards = {[c.card_id for c in p.cards]}")


@profile_app.command("set")
def profile_set(key: str, value: str, profile_id: str = "default") -> None:
    """Set a profile field: willing_to_open_cards=true, memberships=costco,prime, currency=USD."""
    repo = _repo()
    p = repo.get_profile(profile_id) or UserProfile(id=profile_id)
    data = p.model_dump()
    if key not in data:
        raise typer.BadParameter(f"unknown field {key}; one of {sorted(data)}")
    current = data[key]
    if isinstance(current, bool):
        data[key] = value.lower() in ("1", "true", "yes", "y")
    elif isinstance(current, list):
        data[key] = [v.strip() for v in value.split(",") if v.strip()]
    elif isinstance(current, dict):
        data[key] = json.loads(value)
    else:
        data[key] = value
    repo.save_profile(UserProfile.model_validate(data))
    console.print(f"profile {profile_id}: {key} = {data[key]}")


def _details(po) -> str:
    """One dim line of vertical-specific facts pulled from offer attributes."""
    a = po.offer.attributes
    v = po.offer.vertical
    parts: list[str] = []
    if v == Vertical.CAR_RENTAL:
        if a.get("per_day"):
            parts.append(f"${a['per_day']:.2f}/day")
        if a.get("agency"):
            parts.append(f"agency: {a['agency']}")
        if a.get("pickup_note"):
            parts.append(a["pickup_note"].lower())
        if a.get("passengers"):
            parts.append(f"{a['passengers']} seats")
        if a.get("free_cancellation"):
            parts.append("free cancellation")
        if a.get("kayak_score"):
            parts.append(f"kayak score {a['kayak_score']}")
    elif v == Vertical.FLIGHT:
        if a.get("airlines"):
            parts.append(", ".join(a["airlines"]))
        if a.get("stops") is not None:
            parts.append("nonstop" if a["stops"] == 0 else f"{a['stops']} stop(s)")
        if a.get("total_duration_min"):
            parts.append(f"{a['total_duration_min']} min")
    elif v == Vertical.HOTEL:
        if a.get("nightly"):
            parts.append(f"${a['nightly']:.2f}/night")
        if a.get("hotel_class"):
            parts.append(f"{a['hotel_class']}-star")
        if a.get("kind"):
            parts.append(str(a["kind"]).lower())
        if a.get("rating"):
            parts.append(f"{a['rating']}/5 ({a.get('reviews') or 0} reviews)")
        elif a.get("score"):
            parts.append(f"{a['score']}/10 ({a.get('reviews') or 0} reviews)")
        if a.get("distance"):
            parts.append(str(a["distance"]))
        if a.get("free_cancellation"):
            parts.append("free cancellation")
        if a.get("price_note"):
            parts.append(str(a["price_note"]))
    return " · ".join(parts)


def _render(result: SearchResult, limit: int) -> None:
    q = result.query
    console.print(
        f"[bold]{q.vertical.value}[/bold]: {q.item}   providers: {', '.join(result.providers_queried) or 'none'}"
    )
    for name, err in result.providers_failed.items():
        console.print(f"[red]{name} failed:[/red] {err}")
    if not result.offers:
        console.print("[yellow]No offers found.[/yellow] Run `pf providers` to see which sources are configured.")
        return
    table = Table(show_lines=False)
    for col, justify in (
        ("#", "right"),
        ("effective", "right"),
        ("sticker", "right"),
        ("seller", "left"),
        ("cond", "left"),
        ("title", "left"),
        ("savings applied", "left"),
    ):
        table.add_column(col, justify=justify)
    for i, po in enumerate(result.offers[:limit], 1):
        savings = "; ".join(f"-{a.amount.amount:.2f} {a.description}" for a in po.adjustments if a.is_savings)
        notes = ", ".join(po.rank_reasons)
        details = _details(po)
        extra = "".join(f"\n[dim]{line}[/dim]" for line in (details, notes) if line)
        table.add_row(
            str(i),
            f"[green]{po.effective_total.amount:.2f}[/green]",
            f"{po.sticker_total.amount:.2f}",
            po.offer.seller.name,
            po.offer.condition.value if po.offer.vertical == Vertical.GOODS else "-",
            po.offer.title[:90] + extra,
            savings[:120],
        )
    console.print(table)
    if result.best_ever:
        console.print(f"best effective price ever recorded for this item: [green]{result.best_ever}[/green]")
    best = result.best
    if best and best.offer.url:
        console.print(f"[bold]best:[/bold] {best.offer.url}")


if __name__ == "__main__":
    app()
