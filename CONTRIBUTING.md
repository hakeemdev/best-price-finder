# Contributing

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check . && uv run ruff format .
```

- One provider per module under `src/pricefinder/providers/<vertical>/`. See `docs/PROVIDERS.md`.
- Providers must work with `respx`-mocked HTTP in tests; never hit the network in the test suite.
- Keep savings logic data-driven: new cards, coupons and portals go in `data/*.yaml` first.
- Prefer official APIs. Scraping adapters must respect robots.txt, rate limits and be marked `opt_in` when the source's terms forbid automation.
