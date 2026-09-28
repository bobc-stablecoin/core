"""Protocol-specific rules and invariants are supplied by the two mixins."""
from contextlib import ExitStack
from hypothesis.stateful import RuleBasedStateMachine
from .actions import Actions
from .properties import Properties
from .runtime import Diagnostics, isolation


class ProtocolMachine(Actions, Properties, RuleBasedStateMachine):
    def __init__(self, config, deployment_factory):
        # Hypothesis rejects an empty Actions mixin: an unfinished scaffold cannot pass.
        super().__init__()
        self.config = config
        self.diagnostics = Diagnostics(config)
        self._isolation = ExitStack()
        try:
            self._isolation.enter_context(isolation(config["framework"]))
            self.deployment = deployment_factory()
        except BaseException:
            self._isolation.close()
            raise

    def teardown(self):
        try:
            self.diagnostics.save()
        finally:
            self._isolation.close()
