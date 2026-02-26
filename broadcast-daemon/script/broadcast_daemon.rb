#!/usr/bin/env ruby
# frozen_string_literal: true

$stdout.sync = true  # Force unbuffered output for Docker logs

# Broadcast daemon: loads Rails once, then processes broadcast requests from Redis.
# Queue format: LPUSH queue_key '{"account_id":2,"conversation_id":123}'
# conversation_id is the display_id (from the Chatwoot API conversation URLs).
# Each item triggers CONVERSATION_READ dispatch for real-time Chatwoot UI update.

require_relative '../config/environment'

queue_key = ENV.fetch('BROADCAST_QUEUE_KEY', 'cw_read_msgs:conversation_read')
redis_url = ENV.fetch('REDIS_URL', 'redis://localhost:6379/0')
redis = Redis.new(url: redis_url)

# Debug: show Redis URL (password redacted)
redacted_url = redis_url.gsub(/:([^@\/:]+)@/, ':***@')
Rails.logger.info "[BroadcastDaemon] Redis connected: #{redacted_url}"
Rails.logger.info "[BroadcastDaemon] Listening on queue: #{queue_key}"

loop do
  _key, payload = redis.blpop(queue_key, timeout: 5)
  next if payload.nil?

  begin
    data = JSON.parse(payload)
    account_id = data['account_id']&.to_i
    conversation_id = data['conversation_id']&.to_i

    if account_id.nil? || account_id.zero? || conversation_id.nil? || conversation_id.zero?
      Rails.logger.warn "[BroadcastDaemon] Invalid payload: #{payload}"
      next
    end

    conv = Account.find(account_id).conversations.find_by!(display_id: conversation_id)
    Rails.configuration.dispatcher.dispatch(
      Events::Types::CONVERSATION_READ,
      Time.zone.now,
      conversation: conv
    )
    Rails.logger.info "[BroadcastDaemon] Dispatched CONVERSATION_READ for account=#{account_id} conv=#{conversation_id}"
  rescue ActiveRecord::RecordNotFound => e
    Rails.logger.warn "[BroadcastDaemon] Not found: #{e.message}"
  rescue StandardError => e
    Rails.logger.error "[BroadcastDaemon] Error: #{e.class} #{e.message}"
    Rails.logger.error e.backtrace.first(5).join("\n")
  end
end
