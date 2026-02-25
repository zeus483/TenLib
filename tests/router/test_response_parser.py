import pytest
from tenlib.router.response_parser import parse_model_response


class TestResponseParser:

    def test_json_valido_directo(self):
        raw = '{"translation": "Hola mundo", "confidence": 0.95, "notes": "directa"}'
        result = parse_model_response(raw, "test_model")
        assert result["translation"] == "Hola mundo"
        assert result["confidence"] == 0.95

    def test_json_en_bloque_markdown(self):
        raw = '```json\n{"translation": "Texto", "confidence": 0.8, "notes": "ok"}\n```'
        result = parse_model_response(raw, "test_model")
        assert result["translation"] == "Texto"

    def test_json_en_bloque_markdown_sin_lenguaje(self):
        raw = '```\n{"translation": "Texto", "confidence": 0.8, "notes": "ok"}\n```'
        result = parse_model_response(raw, "test_model")
        assert result["translation"] == "Texto"

    def test_respuesta_totalmente_invalida_no_lanza_excepcion(self):
        raw = "Lo siento, no puedo traducir esto."
        result = parse_model_response(raw, "test_model")
        # Modo de emergencia: texto como traducción, confidence baja
        assert result["translation"] == raw
        assert result["confidence"] == 0.3
        assert "ADVERTENCIA" in result["notes"]

    def test_confidence_se_clampea(self):
        raw = '{"translation": "Texto", "confidence": 1.5, "notes": "test"}'
        result = parse_model_response(raw, "test_model")
        assert result["confidence"] == 1.0

    def test_confidence_negativa_se_clampea(self):
        raw = '{"translation": "Texto", "confidence": -0.2, "notes": "test"}'
        result = parse_model_response(raw, "test_model")
        assert result["confidence"] == 0.0

    def test_claves_faltantes_tienen_defaults(self):
        raw = '{"translation": "Solo la traducción"}'
        result = parse_model_response(raw, "test_model")
        assert result["confidence"] == 0.5
        assert result["notes"] != ""