# Broadcast Daemon

Runs as a Docker container alongside cw-read-msgs. Loads Chatwoot's Rails environment
and listens on Redis for broadcast triggers. When the cw-read-msgs Python app marks
a conversation as read and pushes `account_id` and `conversation_id` to the queue,
the daemon dispatches `Events::Types::CONVERSATION_READ` so the Chatwoot web UI
updates the unread counter in real time (without page refresh).

- **Queue**: `cw_read_msgs:conversation_read` (configurable via `BROADCAST_QUEUE_KEY`)
- **Payload**: `{"account_id": N, "conversation_id": N}` — `conversation_id` is the
  internal Chatwoot conversation id (as returned by the API).
- **Image**: Based on `chatwoot/chatwoot:v4.11.1-ce` — must match the running Chatwoot version.

Requires `REDIS_URL` and `DATABASE_URL` pointing to the same Redis and PostgreSQL
as Chatwoot. See the main README for configuration.
