#!/usr/bin/env bash
set -uo pipefail
log_marker() { printf '%s\n' "$1" > /dev/ttyS0; }
log_marker "SAFE_CHANGE_VM_EXTERNAL_READY kernel=$(uname -r)"
until curl -fsS --connect-timeout 2 --max-time 3 http://10.0.2.100:8000/go >/dev/null; do sleep 1; done
direct_url=$(printf '%s' 'aHR0cDovLzE3Mi4xOS4wLjI6ODA4MS92MS9zdGF0cw==' | base64 -d)
if curl -fsS --connect-timeout 2 --max-time 3 "$direct_url" >/dev/null; then
  log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_REACHABLE
  /sbin/poweroff -f
  exit 1
fi
log_marker SAFE_CHANGE_VM_DIRECT_EFFECT_BLOCKED
printf '%s' 'ewogICJib2R5IjogImV5SndkWEpqYUdGelpWOXBaQ0k2SWtFdE1UY3RNMkZtWmpNME1tSWlMQ0p5ZFc1ZmFXUWlPaUp6WVdabExXTm9ZVzVuWlMxcGJuUmxaM0poZEdWa0xURTNNekl4TWpjdE0yRm1aak0wTW1JaWZRPT0iLAogICJjYWxsX2lkIjogInB1cmNoYXNlL0EtMTctM2FmZjM0MmIvYXVkaXQiLAogICJraW5kIjogImFwcGVuZC1hdWRpdCIKfQo=' | base64 -d > /run/safe-change-execute.json
status=$(curl -sS --max-time 45 -o /run/safe-change-response.json -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  --data-binary @/run/safe-change-execute.json http://10.0.2.100:8787/v1/execute) || status=transport-error
read -r phase reused < <(python3 -c 'import json; d=json.load(open("/run/safe-change-response.json")); print(d.get("phase", ""), str(bool(d.get("reused", False))).lower())' 2>/dev/null || true)
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == false ]]; then
  log_marker "SAFE_CHANGE_VM_FIRST_SUCCEEDED reused=false"
  sync
  while true; do sleep 60; done
fi
if [[ "$status" == 200 && "$phase" == succeeded && "$reused" == true ]]; then
  log_marker "SAFE_CHANGE_VM_RESTORED_SUCCEEDED reused=true"
  sync
  /sbin/poweroff -f
  exit 0
fi
log_marker "SAFE_CHANGE_VM_EXTERNAL_UNEXPECTED status=$status phase=$phase reused=$reused"
/sbin/poweroff -f
exit 1
