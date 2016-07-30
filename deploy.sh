#!/usr/bin/env bash

set -e
NAME=$1
PORT=$2

docker build -t $NAME .
docker rm -f $NAME 2>&1 || true
docker run -d --name $NAME -p $PORT:5000 -e "WALL_E_PWD=$WALL_E_PWD" wall-e
