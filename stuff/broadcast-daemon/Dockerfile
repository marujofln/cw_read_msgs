FROM chatwoot/chatwoot:v4.11.1-ce
# Build context is project root; script lives under stuff/broadcast-daemon/
COPY stuff/broadcast-daemon/script/ /app/script/
WORKDIR /app
ENV RAILS_ENV=production
CMD ["bundle", "exec", "ruby", "script/broadcast_daemon.rb"]
