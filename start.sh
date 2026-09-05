#!/bin/bash
cd "$(dirname "$0")/gateway"
exec python3 gateway.py "$@"
