# Chatwoot Read Sync

Bidirectional read sync between Chatwoot and WhatsApp via Evolution API.

## Problem

1. **WhatsApp → Chatwoot**: When a business owner reads incoming WhatsApp messages on their phone instead of in Chatwoot, the conversations remain "unread" in Chatwoot.
2. **Chatwoot → WhatsApp**: When an agent reads or replies in Chatwoot, the customer's WhatsApp still shows gray checkmarks (unread). Evolution API's `CHATWOOT_MESSAGE_READ=true` has known bugs and does not work reliably.

## How it works

### WhatsApp → Chatwoot (existing)

1. Evolution API fires a `MESSAGES_UPDATE` webhook when a message status changes
2. This service receives the webhook and filters for incoming messages (`fromMe=false`) that were read
3. It searches Chatwoot for the contact, finds the conversation, and calls `update_last_seen`
4. If `REDIS_URL` is set, the **broadcast daemon** dispatches `CONVERSATION_READ` for real-time UI update

### Chatwoot → WhatsApp (new)

**Layer 1 — Agent replies**: When Chatwoot sends a `message_created` webhook (agent sends a reply), this service fetches incoming messages, extracts WhatsApp message IDs, and calls Evolution API `markMessageAsRead` to send blue checkmarks.

**Layer 2 — Agent views (no reply)**: A PostgreSQL trigger on Chatwoot's `conversations` table notifies when `agent_last_seen_at` changes. This service listens via LISTEN/NOTIFY and marks the corresponding WhatsApp messages as read.

## Quick start

```bash
# 1. Copy and edit the environment file
cp .env.example .env

# 2. Build and run
docker compose up -d

# 3. Follow post-deployment steps (see below)
```

## Environment variables

Configure these in `.env` before running the service.

### Required

| Variable | Description | Example |
|---|---|---|
| `CHATWOOT_BASE_URL` | Chatwoot base URL (use internal hostname when in Docker network) | `http://chatwoot_rails_1:3000` |
| `CHATWOOT_API_TOKEN` | Agent or admin API access token | `your-agent-or-admin-api-token` |
| `CHATWOOT_ACCOUNT_IDS` | Chatwoot account IDs as JSON array | `[1]` or `[1,2,5]` |

### Required for Chatwoot → WhatsApp read sync

| Variable | Description | Example |
|---|---|---|
| `EVOLUTION_API_URL` | Evolution API base URL | `http://evolution_api:8080` |
| `EVOLUTION_API_KEY` | Evolution API key (apikey header) | `your-evolution-api-key` |

### Optional

| Variable | Description | Example |
|---|---|---|
| `CHATWOOT_DATABASE_URL` | Same PostgreSQL as Chatwoot — enables Layer 2 (agent view without reply) | `postgresql://postgres:PASSWORD@chatwoot-postgres-1:5432/chatwoot` |
| `REDIS_URL` | Same Redis as Chatwoot — enables real-time UI broadcast | `redis://:PASSWORD@chatwoot-redis-1:6379/0` |
| `LOG_LEVEL` | Logging level | `INFO` (default), `DEBUG` |
| `PORT` | Service port | `3100` (default) |

### Example `.env` (Chatwoot → WhatsApp full setup)

```bash
CHATWOOT_BASE_URL=http://chatwoot_rails_1:3000
CHATWOOT_API_TOKEN=your-agent-or-admin-api-token
CHATWOOT_ACCOUNT_IDS=[1]

EVOLUTION_API_URL=http://evolution_api:8080
EVOLUTION_API_KEY=your-evolution-api-key

# Layer 2: detect when agent views conversation (no reply)
CHATWOOT_DATABASE_URL=postgresql://postgres:POSTGRES_PASSWORD@chatwoot-postgres-1:5432/chatwoot

# Real-time UI update for WhatsApp→Chatwoot
REDIS_URL=redis://:REDIS_PASSWORD@chatwoot-redis-1:6379/0
```

## Post-deployment steps (Chatwoot → WhatsApp)

Evolution API’s built-in `CHATWOOT_MESSAGE_READ=true` does not reliably mark WhatsApp messages as read because (1) it only runs when an agent *replies*, not when they just view the conversation; (2) its database query is incorrect and can target the wrong contact; (3) it only marks a single message. Chatwoot also has no webhook for “conversation read”, so we use a two-layer approach. These steps wire everything together.

| Step | Action | Why |
|------|--------|-----|
| **1** | Add Chatwoot webhook (Settings → Integrations → Webhooks): URL `http://cw-read-msgs:3100/chatwoot-webhook`, event `message_created` | **Layer 1** — When an agent sends a reply, Chatwoot fires `message_created`. This service receives it, fetches the conversation’s incoming messages, and calls Evolution API `markMessageAsRead` so the customer sees blue checkmarks. |
| **2** | Run the PostgreSQL trigger: `psql $CHATWOOT_DATABASE_URL -f scripts/create_pg_trigger.sql` | **Layer 2** — When an agent only opens/views a conversation (no reply), Chatwoot updates `agent_last_seen_at` directly in the DB and does not send any webhook. The trigger detects that change and notifies this service via `pg_notify`, which then sends read receipts to WhatsApp. |
| **3** | Ensure Evolution API sends `MESSAGES_UPDATE` to this service (see [Evolution API webhook setup](#evolution-api-webhook-setup-whatsapp--chatwoot)) | Needed for **WhatsApp → Chatwoot**: when the user reads messages on their phone, Evolution sends `messages.update`; this service marks the Chatwoot conversation as read. |

### Step 1 — Chatwoot webhook

1. In Chatwoot: **Settings** → **Integrations** → **Webhooks**
2. Add webhook:
   - **URL**: `http://cw-read-msgs:3100/chatwoot-webhook` (adjust host/port if needed)
   - **Subscribed events**: `message_created`
3. Save

### Step 2 — PostgreSQL trigger

From a host that can reach the Chatwoot PostgreSQL database:

```bash
psql $CHATWOOT_DATABASE_URL -f scripts/create_pg_trigger.sql
```

Ensure `CHATWOOT_DATABASE_URL` is set in `.env` so the service can connect to the same database and start the LISTEN task.

### Step 3 — Evolution API webhook

Configure Evolution API to send `MESSAGES_UPDATE` events to this service. See [Evolution API webhook setup](#evolution-api-webhook-setup-whatsapp--chatwoot) below.

### Broadcast daemon (real-time UI)

The `update_last_seen` API clears the badge, but the Chatwoot web UI may not update until the page is refreshed. The **broadcast daemon** fixes this by dispatching `CONVERSATION_READ` via ActionCable.

The daemon runs as a container and must connect to the same Redis and PostgreSQL as Chatwoot, and needs `SECRET_KEY_BASE`. Add these to `.env` (copy values from your Chatwoot `.env`):

```
REDIS_URL=redis://:REDIS_PASSWORD@chatwoot-redis-1:6379/0
DATABASE_URL=postgresql://postgres:POSTGRES_PASSWORD@chatwoot-postgres-1:5432/chatwoot
SECRET_KEY_BASE=<copy from Chatwoot .env>
```

`docker compose up -d` starts both `cw-read-msgs` and `broadcast-daemon`. Both must be on the `chatwoot_default` network.

### Evolution API (LID resolution)

If read receipts use **Linked ID (LID)** JIDs (e.g. `54958938411215@lid` instead of phone JIDs), set `EVOLUTION_API_URL` and `EVOLUTION_API_KEY` to enable LID-to-phone resolution. Without these, the service logs "Evolution API not configured — LID resolution disabled" and LID receipts may not match Chatwoot contacts.

### Getting the Chatwoot API token

1. Log in to Chatwoot as an admin or agent
2. Go to **Settings > Profile**
3. Copy the **Access Token**

## Evolution API webhook setup (WhatsApp → Chatwoot)

Configure Evolution API to send `MESSAGES_UPDATE` events to this service.

### Option A: Global webhook (all instances)

Add these environment variables to the Evolution API container:

```
WEBHOOK_GLOBAL_URL=http://cw-read-msgs:3100/evolution-webhook
WEBHOOK_GLOBAL_ENABLED=true
WEBHOOK_EVENTS_MESSAGES_UPDATE=true
```

### Option B: Per-instance webhook (API call)

```bash
curl -X POST "http://localhost:8080/webhook/set/YOUR_INSTANCE_NAME" \
  -H "apikey: YOUR_EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "url": "http://cw-read-msgs:3100/evolution-webhook",
    "events": ["MESSAGES_UPDATE"]
  }'
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/evolution-webhook` | Receives Evolution API webhook events |
| `POST` | `/chatwoot-webhook` | Receives Chatwoot webhooks (message_created) |
| `GET` | `/health` | Liveness probe |
| `GET` | `/docs` | Interactive API docs (Swagger UI) |

## Development

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
# Install dependencies (creates .venv automatically)
uv sync

# Run locally
uv run uvicorn app.main:app --reload --port 3100

# Run tests
uv run pytest tests/ -v
```

## Important notes

- If Evolution API has **"Read Messages"** auto-read enabled on an instance,
  Baileys reads all incoming messages immediately and no phone-read event will
  fire. Make sure this setting is **disabled** for read sync to work.
- Supports multiple Chatwoot accounts. On startup the service queries each
  account for its API-channel inboxes and builds an automatic
  `inbox_name -> account_id` mapping. The Evolution instance name in each
  webhook is used to route to the correct account.
- Calling `update_last_seen` is idempotent; duplicate webhooks are harmless.
