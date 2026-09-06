#!/bin/bash

set -e

cd "$(dirname "$0")"

source .venv/bin/activate

export FREETDSCONF="$PWD/freetds.conf"
export TDSVER="7.2"

python3 main.py
