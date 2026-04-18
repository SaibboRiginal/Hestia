"""Hestia-Argus — all-seeing system watchman.

Monitors the entire Hestia ecosystem by polling service health endpoints and
tailing Docker container logs. Surfaces issues proactively via Oracle/Hermes
and exposes an on-demand analysis API for Telegram commands and Oracle tools.

Registered in Hub as service name ``argus`` with tags [core, monitoring].
"""
