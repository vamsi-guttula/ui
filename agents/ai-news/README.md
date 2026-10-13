# AI news agent

Every 5 minutes, asks Claude (with web search) for the latest AI news,
condenses it to about 100 words, and emails it to you.

## Setup

Requires Node.js 20.6 or newer.

```bash
cd agents/ai-news
npm install
cp .env.example .env   # then fill in your API key and SMTP details
```

For Gmail, set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=465` and use an
[App Password](https://myaccount.google.com/apppasswords) as `SMTP_PASS`.

## Run

```bash
npm run once   # send one digest now, to test your settings
npm start      # keep running and send a digest every 5 minutes
```

Change the interval with `CRON_SCHEDULE` in `.env` (cron syntax, e.g.
`0 * * * *` for hourly).

## Cost

Each run makes one Claude request with up to 5 web searches. At every
5 minutes that is 288 runs a day, so consider a longer interval if you
leave it running.
