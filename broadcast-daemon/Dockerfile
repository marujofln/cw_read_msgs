FROM chatwoot/chatwoot:v4.11.1-ce
# Build context is project root
COPY broadcast-daemon/script/ /app/script/
WORKDIR /app
ENV RAILS_ENV=production
CMD ["bundle", "exec", "ruby", "script/broadcast_daemon.rb"]
