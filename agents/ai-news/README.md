# AI news agent

Every 5 minutes, asks Claude (with web search) for the latest AI news,
condenses it to about 100 words, and saves it to `ai-news.txt` on your
desktop. Each run adds a new timestamped entry to the end of the file.

## Setup

Requires Node.js 20.6 or newer.

```bash
cd agents/ai-news
npm install
cp .env.example .env   # then fill in your API key
```

To save somewhere else, set `OUTPUT_FILE` in `.env` (useful on Windows if
your desktop is synced to OneDrive, e.g.
`OUTPUT_FILE=C:\Users\you\OneDrive\Desktop\ai-news.txt`).

## Run

```bash
npm run once   # save one digest now, to test your settings
npm start      # keep running and save a digest every 5 minutes
```

Change the interval with `CRON_SCHEDULE` in `.env` (cron syntax, e.g.
`0 * * * *` for hourly).

## Cost

Each run makes one Claude request with up to 5 web searches. At every
5 minutes that is 288 runs a day, so consider a longer interval if you
leave it running.
