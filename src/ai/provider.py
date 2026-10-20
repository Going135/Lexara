from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def analyze(self, text, candidates, mode, limit):
        """Return structured context analysis and target recommendations."""


class LocalAIProvider(AIProvider):
    def analyze(self, text, candidates, mode, limit):
        raise NotImplementedError('Local model is deferred until after competition')
