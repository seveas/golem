#!/bin/bash

cd "$(git rev-parse --show-toplevel)"

export PYTHONPATH=.
if [ -z "$STY" ]; then
    exec screen "$0" "$@"
fi

screen bin/golem --master
for worker in golem/worker/[a-z]*.py; do
    worker=${worker##*\/}
    worker=${worker%.py}
    worker=${worker//_/-}
    screen bin/golem --worker $worker
done
