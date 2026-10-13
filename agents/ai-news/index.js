// AI news agent: every 5 minutes, asks Claude (with web search) for the
// latest AI news, condensed to ~100 words, and appends it to a file on
// your desktop.
//
//   npm start        run on a schedule (default: every 5 minutes)
//   npm run once     save one digest now and exit

import { appendFile, mkdir } from "node:fs/promises"
import { homedir } from "node:os"
import { dirname, join } from "node:path"
import Anthropic from "@anthropic-ai/sdk"
import cron from "node-cron"

const SCHEDULE = process.env.CRON_SCHEDULE || "*/5 * * * *"
const OUTPUT_FILE =
  process.env.OUTPUT_FILE || join(homedir(), "Desktop", "ai-news.txt")
const MAX_CONTINUATIONS = 5

if (!process.env.ANTHROPIC_API_KEY) {
  console.error("Missing env var: ANTHROPIC_API_KEY (see .env.example)")
  process.exit(1)
}

const client = new Anthropic()

const SYSTEM = `You are a news agent that reports the latest developments in artificial intelligence.
Search the web for the most recent AI news (model releases, research, products, policy, funding).
Prefer items from the last 24 hours. Then write a digest of exactly about 100 words:
plain text, 3-5 short bullet points starting with "- ", each naming the source.
Output only the digest, with no preamble or closing remarks.`

async function getAiNews() {
  const messages = [
    {
      role: "user",
      content: `Today is ${new Date().toUTCString()}. Give me the latest AI news in about 100 words.`,
    },
  ]

  for (let i = 0; i <= MAX_CONTINUATIONS; i++) {
    const response = await client.beta.messages.create({
      model: "claude-opus-5-5",
      max_tokens: 16000,
      output_config: { effort: "low" },
      // If a safety classifier declines, retry on a fallback model server-side.
      betas: ["server-side-fallback-2026-07-01"],
      fallbacks: "default",
      system: SYSTEM,
      tools: [{ type: "web_search_20260209", name: "web_search", max_uses: 5 }],
      messages,
    })

    // Long server-tool turns can pause; send the content back to resume.
    if (response.stop_reason === "pause_turn") {
      messages.push({ role: "assistant", content: response.content })
      continue
    }

    if (response.stop_reason === "refusal") {
      throw new Error(
        `Request declined: ${response.stop_details?.explanation ?? "no details"}`
      )
    }

    const text = response.content
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("")
      .trim()
    if (!text) throw new Error(`Empty response (stop_reason: ${response.stop_reason})`)
    return text
  }

  throw new Error("Gave up after too many pause_turn continuations")
}

async function runOnce() {
  const started = new Date()
  try {
    const digest = await getAiNews()
    await mkdir(dirname(OUTPUT_FILE), { recursive: true })
    await appendFile(
      OUTPUT_FILE,
      `=== AI update - ${started.toLocaleString()} ===\n${digest}\n\n`
    )
    console.log(`[${started.toISOString()}] Saved digest to ${OUTPUT_FILE}`)
  } catch (error) {
    if (error instanceof Anthropic.RateLimitError) {
      console.error(`[${started.toISOString()}] Rate limited, will retry next run`)
    } else if (error instanceof Anthropic.APIError) {
      console.error(`[${started.toISOString()}] API error ${error.status}: ${error.message}`)
    } else {
      console.error(`[${started.toISOString()}] Failed:`, error.message)
    }
    if (process.argv.includes("--once")) process.exitCode = 1
  }
}

if (process.argv.includes("--once")) {
  await runOnce()
} else {
  let running = false
  const tick = async () => {
    // Skip a tick if the previous run is still going.
    if (running) return
    running = true
    try {
      await runOnce()
    } finally {
      running = false
    }
  }
  cron.schedule(SCHEDULE, tick)
  console.log(`AI news agent started (schedule: "${SCHEDULE}"). Ctrl+C to stop.`)
  await tick()
}
