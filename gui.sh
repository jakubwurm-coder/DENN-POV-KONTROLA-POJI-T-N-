#!/bin/bash

cd "$(dirname "$0")"

source .venv/bin/activate

export FREETDSCONF="$PWD/freetds.conf"
export TDSVER="7.2"

python3 gui.py
