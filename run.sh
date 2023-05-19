#!/usr/bin/env bash
$(cat .env | sed 's/^/export /')
if [ "$1" == "prod" ]; then
    docker build -t draw-card-bot -f dockerfile .
    docker stop draw-card-bot
    docker rm draw-card-bot
    docker run --env-file .env -v ./data:/app/data -d --name draw-card-bot --network host draw-card-bot
else
    ./app.py
fi