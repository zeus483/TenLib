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

    # ── Robustez ante respuestas markdown ─────────────────────────────────

    def test_json_anidado_en_bloque_markdown(self):
        """
        El JSON del extractor tiene objetos anidados (glossary, characters).
        El regex greedy debe capturarlos correctamente.
        """
        raw = (
            "```json\n"
            '{"translation": "El texto", "confidence": 0.85, '
            '"notes": "Sin notas.", "extra": {"a": "b"}}\n'
            "```"
        )
        result = parse_model_response(raw, "test_model")
        assert result["translation"] == "El texto"
        assert result["confidence"] == 0.85

    def test_json_con_texto_extra_antes_y_despues(self):
        """El parser debe encontrar el JSON aunque haya texto libre alrededor."""
        raw = (
            "Aquí está mi respuesta:\n"
            '{"translation": "Texto traducido", "confidence": 0.9, "notes": "ok"}\n'
            "Espero que sea útil."
        )
        result = parse_model_response(raw, "test_model")
        assert result["translation"] == "Texto traducido"

    def test_respuesta_markdown_con_secciones(self):
        """
        Modelo responde con secciones ## en lugar de JSON.
        El parser extrae traducción, confianza y notas de los headers.
        """
        raw = (
            "## Traducción\n"
            "El texto fue traducido correctamente al español.\n\n"
            "## Confianza\n"
            "0.82\n\n"
            "## Notas\n"
            "Se mantuvo el tono narrativo original."
        )
        result = parse_model_response(raw, "test_model")
        assert "traducido correctamente" in result["translation"]
        assert result["confidence"] == 0.82
        assert "tono narrativo" in result["notes"]

    def test_respuesta_markdown_translation_en_ingles(self):
        """El regex de secciones también reconoce 'Translation' en inglés."""
        raw = (
            "## Translation\n"
            "This is the translated text.\n\n"
            "## Confidence\n"
            "0.75"
        )
        result = parse_model_response(raw, "test_model")
        assert "translated text" in result["translation"]
        assert result["confidence"] == 0.75

    def test_fallback_strips_markdown_headers(self):
        """
        Si nada funciona, el fallback limpia encabezados markdown del texto
        en lugar de devolverlos crudos.
        """
        raw = "## Respuesta\nEsto no tiene formato esperado."
        result = parse_model_response(raw, "test_model")
        assert "##" not in result["translation"]
        assert result["confidence"] == 0.3