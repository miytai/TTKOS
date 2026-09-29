#!/bin/sh
# Создание бакета MinIO для медиа (аватары, вложения) и lifecycle для каталогов.
set -eu

BUCKET="${MINIO_BUCKET:-forumos-media}"

echo "Waiting for MinIO ..."
for _ in $(seq 1 30); do
  if mc alias set local http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

mc alias set local http://minio:9000 "${MINIO_ROOT_USER}" "${MINIO_ROOT_PASSWORD}"

if mc ls "local/${BUCKET}" >/dev/null 2>&1; then
  echo "Bucket ${BUCKET} already exists"
else
  mc mb "local/${BUCKET}"
  echo "Bucket ${BUCKET} created"
fi

mc anonymous set download "local/${BUCKET}/public" 2>/dev/null || true

echo "MinIO is ready."
