"""Gmail adapter (Phase 1: read-only list/read; Phase 5: gated send/create).
Send/create paths MUST route through the action_queue — no autonomous sending.
"""
