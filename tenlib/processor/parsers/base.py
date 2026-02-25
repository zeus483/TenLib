from abc import ABC, abstractmethod
from tenlib.processor.models import RawBook

class BaseParser(ABC):
    @abstractmethod
    def can_handle(slef, file_path:str) -> bool:
        """Devuelve true si el parser puede manejar el archivo"""
        raise NotImplementedError
    
    @abstractmethod
    def parse(self, file_path:str) -> RawBook:
        """Parsea el archivo y devuelve un RawBoo limpio"""
        raise NotImplementedError