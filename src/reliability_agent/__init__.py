"""Physical AI Reliability Agent.

Autonomous MAPE-K loop for camera-based perception pipelines:
Monitor (capture + probes) -> Analyze (baseline + fusion + FSM) -> Plan (NVIDIA Nemotron on
Nebius Token Factory, advisory only) -> Execute (policy gate + reversible actions) -> Verify
(commit or rollback) over a shared Knowledge store (SQLite event log).
"""

__version__ = "0.1.0"
