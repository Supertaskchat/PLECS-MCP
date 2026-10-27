"""Tiny in-memory model registry (name <-> path, dirty flag from our own writes)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ModelState:
    name: str
    path: str
    dirty: bool = False


@dataclass
class CrashRecord:
    """One PLECS process death, keyed by the model file that triggered it."""

    model: str
    path: str
    fingerprint: str
    method: str
    dump: str | None
    at: float


@dataclass
class SessionState:
    models: dict[str, ModelState] = field(default_factory=dict)
    crashes: dict[str, CrashRecord] = field(default_factory=dict)

    def record_crash(self, record: CrashRecord) -> None:
        self.crashes[record.fingerprint] = record

    def crash_for(self, fingerprint: str | None) -> CrashRecord | None:
        return self.crashes.get(fingerprint) if fingerprint else None

    def clear_crash(self, fingerprint: str | None) -> None:
        if fingerprint:
            self.crashes.pop(fingerprint, None)

    def loaded(self, name: str, path: str) -> ModelState:
        state = ModelState(name=name, path=path)
        self.models[name] = state
        return state

    def get(self, name: str) -> ModelState | None:
        return self.models.get(name)

    def path_for(self, name: str) -> str | None:
        state = self.models.get(name)
        return state.path if state else None

    def mark_dirty(self, component_path: str) -> None:
        model = component_path.split("/", 1)[0]
        state = self.models.get(model)
        if state is not None:
            state.dirty = True

    def saved(self, name: str) -> None:
        if name in self.models:
            self.models[name].dirty = False

    def renamed(self, old: str, new: str) -> None:
        state = self.models.pop(old, None)
        if state is not None:
            state.name = new
            self.models[new] = state

    def closed(self, name: str) -> None:
        self.models.pop(name, None)


STATE = SessionState()
