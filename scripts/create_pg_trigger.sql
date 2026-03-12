-- Create a PostgreSQL trigger to notify when an agent views a conversation
-- (agent_last_seen_at or assignee_last_seen_at is updated).
--
-- Run this against the Chatwoot database:
--   psql $DATABASE_URL -f scripts/create_pg_trigger.sql
--
-- The cw-read-msgs service listens on the 'cw_conversation_read' channel
-- and marks corresponding WhatsApp messages as read via Evolution API.

CREATE OR REPLACE FUNCTION cw_read_msgs_notify_conversation_read()
RETURNS TRIGGER AS $$
BEGIN
  IF (OLD.agent_last_seen_at IS DISTINCT FROM NEW.agent_last_seen_at)
     OR (OLD.assignee_last_seen_at IS DISTINCT FROM NEW.assignee_last_seen_at) THEN
    PERFORM pg_notify(
      'cw_conversation_read',
      json_build_object(
        'conversation_id', NEW.id,
        'account_id', NEW.account_id
      )::text
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Drop if exists to allow idempotent re-run
DROP TRIGGER IF EXISTS cw_conversation_read_trigger ON conversations;

CREATE TRIGGER cw_conversation_read_trigger
  AFTER UPDATE ON conversations
  FOR EACH ROW
  EXECUTE PROCEDURE cw_read_msgs_notify_conversation_read();
