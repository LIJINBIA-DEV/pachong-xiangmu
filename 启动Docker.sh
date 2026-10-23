#!/bin/sh
set -eu
cd "$(dirname "$0")"
docker info >/dev/null
if [ "$(docker info --format '{{.OSType}}')" != 'linux' ]; then
    echo 'This package requires Linux containers.' >&2
    exit 1
fi
if [ ! -f .env.portable ]; then
    umask 077
    password=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
    sed "s/^BROWSER_PASSWORD=$/BROWSER_PASSWORD=$password/" .env.portable.example >.env.portable
    echo 'Created .env.portable. Configure model API keys there; keep this file private.'
fi
image=$(docker compose --env-file .env.portable -f compose.portable.yaml config --images)
if ! docker image inspect "$image" >/dev/null 2>&1; then
    for archive in mediacrawler-image.tar ../mediacrawler-image.tar; do
        if [ -f "$archive" ]; then
            docker load -i "$archive"
            break
        fi
    done
fi
if [ "${1:-}" = '--rebuild' ]; then
    docker compose --env-file .env.portable -f compose.portable.yaml build
fi
docker compose --env-file .env.portable -f compose.portable.yaml up -d --wait --wait-timeout 180
echo 'Started. Default workbench: http://127.0.0.1:18180'
echo 'Browser password: BROWSER_PASSWORD in .env.portable. Data stays in Docker volumes.'
