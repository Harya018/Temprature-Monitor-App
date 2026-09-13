#!/bin/bash
# SentinelEdge stop script
pkill -f "uvicorn backend.main:app" 2>/dev/null && echo "SentinelEdge stopped." || echo "SentinelEdge was not running."
