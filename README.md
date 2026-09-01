# a-stock-data - admin

This repository is the current harr1y/a-stock-data A-share research and market-structure application. The current repository is authoritative; upstream repositories are consulted selectively and never used to overwrite the existing backend or frontend.

## Features

- FastAPI backend and React/Vite frontend.
- A-share quotes, indices, ETFs, stocks, news and portfolio research pages.
- CFFEX IF/IH/IC/IM member long/short rankings, all-member and CITIC Futures summaries, retained history, weekly statistics and next-session Shanghai Composite validation.
- Real-source-first behavior with explicit no-data results instead of synthetic quotes.

## Quick start

```bash
cd /opt/code/a-stock/a-stock-data
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 8000

cd frontend
npm install
npm run dev
```

Run tests with `pytest -q`, `npm test`, and `npm run build`.

## Data policy

CFFEX ranking files are fetched on demand and retained with source URL, fetch time, hash and raw rows. Long/short interpretations are shown separately from the user-defined inverse T+1 Shanghai Composite heuristic: short-heavy maps to next-session bullish, long-heavy maps to next-session bearish, and close values map to hedge/neutral. This is research output, not investment advice.

## Version and contact

- Version: `admin`
- Maintainer/contact: `admin`
- Repository: `https://github.com/harr1y/a-stock-data`

Generated runtime databases, logs and caches are local artifacts and must not be committed.

This software is for research and objective data display only. It is not investment advice and makes no return guarantee.
