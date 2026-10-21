# Chatwoot Read Sync

Marks Chatwoot conversations as read when WhatsApp messages are read on the
phone, using Evolution API webhooks.

## Problem

When a business owner reads incoming WhatsApp messages on their phone instead of
in Chatwoot, the conversations remain "unread" in Chatwoot. Neither Evolution
API's built-in Chatwoot integration nor Chatwoot itself syncs read status in
this direction.

## How it works

1. Evolution API fires a `MESSAGES_UPDATE` webhook when a message status changes
2. This service receives the webhook and filters for incoming messages
   (`fromMe=false`) that were read (`status >= 3`)
3. It searches Chatwoot for the contact by phone number, finds the matching
   conversation in the correct inbox, and calls `update_last_seen` to clear the
   unread badge
4. If `REDIS_URL` is set, it pushes a trigger to Redis; the **broadcast daemon**
   consumes it and dispatches `CONVERSATION_READ` so the Chatwoot web UI updates
   the unread counter in real time (without page refresh)

## Quick start

```bash
git clone https://github.com/marujofln/cw_read_msgs.git
cd cw_read_msgs

# 1. Copy and edit the environment file
cp .env.example .env

# 2. Build and run
docker compose up -d

# 3. Configure Evolution API webhook (see below)
```

## Configuration

| Variable | Required | Description | Example |
|---|---|---|---|
| `CHATWOOT_BASE_URL` | yes | Chatwoot internal URL | `http://chatwoot_rails_1:3000` |
| `CHATWOOT_API_TOKEN` | yes | Agent or admin API token | `abc123...` |
| `CHATWOOT_ACCOUNT_IDS` | yes | Chatwoot account IDs (JSON list) | `[1]` or `[1,2,5]` |
| `EVOLUTION_API_URL` | no | Evolution API base URL — enables LID resolution | `http://evolution_api:8080` |
| `EVOLUTION_API_KEY` | no | Evolution API key (required if URL is set) | `your-evolution-api-key` |
| `REDIS_URL` | no | Same Redis as Chatwoot — enables broadcast triggers for real-time UI | `redis://:PASSWORD@chatwoot-redis-1:6379/0` |
| `LOG_LEVEL` | no | Logging level (default: `INFO`) | `DEBUG` |
| `PORT` | no | Service port (default: `3100`) | `3100` |

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

## Evolution API webhook setup

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
