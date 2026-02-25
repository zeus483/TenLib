from abc import ABC, abstractmethod

class TokenEstimator(ABC):
    @abstractmethod
    def estimate(self, text: str) -> int: ...

class SimpleTokenEstimator(TokenEstimator):
    """
    Estimacion rapida sin dependencias externas
    Suficiente para el MVP. Error tipico < 10%.
    """
    def estimate(self, text: str) -> int:
        #Palabras * 1.3 cubre bien español e ingles.
        #Japones/chino necesita su propio factor  (1 char mas o menos 1-2 tokens)
        return int(len(text.split()) * 1.3)
    
class TikTokenEstimator(TokenEstimator):
    """
    Estimacion exacta usando tiktoken (libreria de OpenAI)
    Swap-in cuando se necesite precision real.
    """
    def __init__(self,model:str = "gpt-4"):
        import tiktoken
        self._enc = tiktoken.encoding_for_model(model)
    
    def estimate(self, text: str) -> int:
        return len(self._enc.encode(text))
