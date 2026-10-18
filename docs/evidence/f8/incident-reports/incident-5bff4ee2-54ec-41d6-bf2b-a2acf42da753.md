# Incident 5bff4ee2-54ec-41d6-bf2b-a2acf42da753

**SIMULATION / EVENTSTORE DERIVED**

- Opened: 2026-10-18T11:20:42.035312+00:00
- Faults: blackout
- Planner source: rules
- Model / prompt: local-rules / None
- Tokens: 0 input, 0 output
- Estimated plan cost: $0
- Restart resolution: none

## Gate decisions

```json
[
  {
    "action": "set_exposure_bounded",
    "approved": true,
    "arguments": {
      "delta_ev": 2.0
    },
    "reasons": [
      "ok"
    ]
  }
]
```

## Execution and verification

```json
{
  "executions": [
    {
      "action": "set_exposure_bounded",
      "applied": {
        "exposure": 2.0
      },
      "arguments": {
        "delta_ev": 2.0
      },
      "error": null,
      "execution_id": "44ca22db-03d3-4aee-9da3-0f66b6146deb",
      "status": "success"
    }
  ],
  "rollbacks": [],
  "verifications": [
    {
      "after": {
        "task.latency_ms_p95": 0.5058837001342908,
        "task.success_rate": 1.0,
        "transport.capture_fps": 5.0
      },
      "before": {
        "task.latency_ms_p95": 0.31771040048624855,
        "task.success_rate": 0.0,
        "transport.capture_fps": 5.0
      },
      "reasons": [
        "task.success_rate: 0.000 -> 1.000 (rel +100%)"
      ],
      "status": "committed"
    }
  ]
}
```

Event count: 12.
