"""Campaign settings, isolated examples, and JSON replay diagnostics."""
from contextlib import contextmanager
from pathlib import Path
from collections import Counter
import json
import importlib.metadata
import sys
import os
import uuid

from hypothesis import settings
from hypothesis.database import DirectoryBasedExampleDatabase

PROFILES = {"smoke": (10, 20), "standard": (100, 50), "extended": (1000, 100)}


def campaign_settings(config):
    profile = os.environ.get("FYZZ_PROFILE", "standard")
    if profile not in PROFILES:
        raise ValueError(f"Unknown FYZZ_PROFILE: {profile}")
    examples, steps = PROFILES[profile]
    profile_path = Path(config["meta_dir"]) / "profiles.json"
    if profile_path.exists():
        selected = json.loads(profile_path.read_text())[profile]
        examples, steps = selected["max_examples"], selected["stateful_step_count"]
    examples = int(os.environ.get("FYZZ_MAX_EXAMPLES", examples))
    steps = int(os.environ.get("FYZZ_STEPS", steps))
    if examples < 1 or steps < 1:
        raise ValueError("FYZZ_MAX_EXAMPLES and FYZZ_STEPS must be positive")
    output = Path(os.environ.get("FYZZ_RUN_DIR", config["meta_dir"]))
    output.mkdir(parents=True, exist_ok=True)
    versions = {"python": sys.version.split()[0]}
    for distribution in ("hypothesis", "pytest", "titanoboa", "eth-ape", "ape-vyper", "moccasin", "vyper"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
    (output / "effective-settings.json").write_text(json.dumps({
        "profile": profile, "max_examples": examples, "stateful_step_count": steps,
        "deadline": None, "versions": versions,
    }, indent=2) + "\n")
    return settings(max_examples=examples, stateful_step_count=steps, deadline=None,
                    database=DirectoryBasedExampleDatabase(Path(config["meta_dir"]) / "hypothesis"))


def isolation(framework):
    if framework in {"boa", "moccasin"}:
        import boa
        return boa.env.anchor()
    if framework == "ape":
        return ape_isolation()
    raise ValueError(f"Unsupported framework: {framework}")


@contextmanager
def ape_isolation():
    """Use explicit public APIs: some Ape isolate versions suppress exceptions."""
    from ape import chain
    snapshot = chain.snapshot()  # Unsupported providers must fail before deployment.
    try:
        yield
    finally:
        chain.restore(snapshot)


def replay_value(value):
    """Reject opaque objects; record actors as addresses and contracts by stable keys."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, (list, tuple)):
        return [replay_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: replay_value(item) for key, item in value.items()}
    raise TypeError(f"Non-replayable action input: {type(value).__name__}")


class Diagnostics:
    def __init__(self, config):
        self.root = Path(os.environ.get("FYZZ_RUN_DIR", config["meta_dir"]))
        self.example_id = uuid.uuid4().hex
        self.actions = []
        self.counts = Counter()
        self.transitions = Counter()
        self.failure = None

    def save(self):
        directory = self.root / "reachability"
        directory.mkdir(parents=True, exist_ok=True)
        data = {"example_id": self.example_id, "counts": dict(self.counts),
                "transitions": dict(self.transitions)}
        (directory / f"{self.example_id}.json").write_text(json.dumps(data, indent=2) + "\n")
        if self.failure:
            directory = self.root / "traces"
            directory.mkdir(parents=True, exist_ok=True)
            data.update(actions=self.actions, failure=self.failure)
            (directory / f"{self.example_id}.json").write_text(json.dumps(data, indent=2) + "\n")

    @contextmanager
    def action(self, name, *, inputs, expected_revert=(), match=None, transition=None):
        """Enclose call AND postconditions. Expected reverts must be intentional cases.

        Ghost updates belong after successful calls. Never pass Exception or an
        assertion type as expected_revert. Inputs must include actor, value, and
        time changes when relevant; record concrete values, not random seeds.
        """
        if any(not isinstance(t, type) or not issubclass(t, Exception)
               or issubclass(AssertionError, t) or issubclass(t, AssertionError)
               for t in expected_revert):
            raise TypeError("Expected reverts must be narrow contract exception types")
        entry = {"action": name, "inputs": replay_value(inputs), "outcome": "started"}
        self.actions.append(entry)
        self.counts[f"{name}:attempts"] += 1
        try:
            try:
                yield
            except expected_revert as exc:
                if match is not None and match not in str(exc):
                    raise
                entry["outcome"] = "expected_revert"
                self.counts[f"{name}:expected_reverts"] += 1
            else:
                if expected_revert:
                    raise AssertionError(f"{name}: expected contract revert did not occur")
                entry["outcome"] = "success"
                self.counts[f"{name}:successes"] += 1
                if transition:
                    self.transitions[transition] += 1
        except BaseException as exc:
            entry["outcome"] = "failure"
            self.failure = {**(self.failure or {}), "action": name, "type": type(exc).__name__, "message": str(exc)}
            self.save()
            raise

    def check(self, spec_id, assertion):
        """Invoke a property assertion and retain its stable ID on failure."""
        try:
            assertion()
        except BaseException as exc:
            self.failure = {"spec_id": spec_id, "type": type(exc).__name__, "message": str(exc)}
            self.save()
            raise
