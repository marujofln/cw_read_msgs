#!/bin/bash
# Test trigger from plan item 4: manually dispatch CONVERSATION_READ event
# to verify if the broadcast updates the Chatwoot UI in real-time.
#
# Usage: ./scripts/test_broadcast_trigger.sh [account_id] [conversation_display_id]
# Default: account_id=2, conversation_display_id=1112
#
# Run on the Chatwoot server (where docker has access to chatwoot-rails-1).

ACCOUNT_ID=${1:-2}
CONVERSATION_ID=${2:-1112}

RAILS_CODE="conv = Account.find($ACCOUNT_ID).conversations.find_by!(display_id: $CONVERSATION_ID); Rails.configuration.dispatcher.dispatch(Events::Types::CONVERSATION_READ, Time.zone.now, conversation: conv); puts 'Broadcast CONVERSATION_READ dispatched for conversation ' + conv.id.to_s"

docker exec -it chatwoot-rails-1 sh -c "RAILS_ENV=production bundle exec rails runner \"$RAILS_CODE\""

