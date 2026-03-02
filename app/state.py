# app/state.py
# Global application state (keeps singletons without circular imports)

from __future__ import annotations

from typing import Optional

from app.services.orchestrator import Orchestrator

orchestrator: Optional[Orchestrator] = None