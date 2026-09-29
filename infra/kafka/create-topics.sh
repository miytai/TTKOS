#!/usr/bin/env bash
# Создание Kafka-топиков ForumOS (см. TECHSPEC §13.1).
# Идемпотентно: если топик существует — конфигурация обновляется.
set -euo pipefail

BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-kafka:29092}"
BASE_PARTITIONS="${KAFKA_PARTITIONS:-3}"

# topic:partitions:retention_hours
TOPICS=(
  "thread.created:3:168"
  "thread.updated:3:168"
  "thread.deleted:3:168"
  "post.created:6:168"
  "post.updated:3:168"
  "post.deleted:3:168"
  "reaction.added:6:168"
  "reaction.removed:6:168"
  "user.joined:3:168"
  "user.online:6:24"
  "user.offline:6:24"
  "moderation.flag:3:720"
  "achievement.unlocked:3:720"
  "analytics.events:6:720"
)

echo "Waiting for Kafka at ${BOOTSTRAP} ..."
for _ in $(seq 1 60); do
  if kafka-topics --bootstrap-server "${BOOTSTRAP}" --list >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

create_topic() {
  local topic="$1" partitions="$2" retention_hours="$3"
  local retention_ms=$((retention_hours * 3600 * 1000))

  kafka-topics \
    --bootstrap-server "${BOOTSTRAP}" \
    --create --if-not-exists \
    --topic "${topic}" \
    --partitions "${partitions}" \
    --replication-factor 1 \
    --config "retention.ms=${retention_ms}" \
    --config "cleanup.policy=delete" >/dev/null

  # retention.ms нельзя изменить только при создании — выравниваем для существующих топиков
  kafka-configs --bootstrap-server "${BOOTSTRAP}" \
    --entity-type topics --entity-name "${topic}" \
    --alter --add-config "retention.ms=${retention_ms}" >/dev/null

  echo "  ✓ ${topic} (partitions=${partitions}, retention=${retention_hours}h)"
}

echo "Creating topics ..."
for entry in "${TOPICS[@]}"; do
  IFS=':' read -r topic partitions retention <<< "${entry}"
  create_topic "${topic}" "${partitions}" "${retention}"
done

echo "Dead-letter queues ..."
for entry in "${TOPICS[@]}"; do
  IFS=':' read -r topic _ _ <<< "${entry}"
  create_topic "${topic}.dlq" 1 720
done

echo "All topics are ready."
