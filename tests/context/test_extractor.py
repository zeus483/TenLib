# tests/context/test_extractor.py
import pytest
from unittest.mock import MagicMock
from tenlib.context.extractor import BibleExtractor
from tenlib.context.bible import BibleUpdate
from router.models import ModelResponse


def make_model(json_response: str) -> MagicMock:
    model = MagicMock()
    model.translate.return_value = ModelResponse(
        translation   = json_response,
        confidence    = 0.9,
        notes         = "ok",
        model_used    = "gemini",
        tokens_input  = 50,
        tokens_output = 80,
    )
    return model


class TestBibleExtractor:

    def test_siempre_extrae_en_chunk_cero(self):
        model     = make_model('{"glossary": {}, "characters": {}, "decisions": [], "last_scene": "inicio"}')
        extractor = BibleExtractor(model)

        result = extractor.extract("original", "traducción", "", chunk_index=0)

        assert result is not None
        model.translate.assert_called_once()

    def test_no_extrae_en_chunk_normal_sin_notas(self):
        model     = make_model("{}")
        extractor = BibleExtractor(model, extract_every_n=5)

        result = extractor.extract("original", "traducción", "todo bien", chunk_index=3)

        assert result is None
        model.translate.assert_not_called()

    def test_extrae_si_modelo_reporto_terminos_nuevos(self):
        json_resp = '{"glossary": {"Chandrian": "Chandrian"}, "characters": {}, "decisions": [], "last_scene": "escena"}'
        model     = make_model(json_resp)
        extractor = BibleExtractor(model, extract_every_n=10)

        result = extractor.extract(
            "original", "traducción",
            notes       = "encontré término nuevo: Chandrian",
            chunk_index = 2,
        )

        assert result is not None
        assert result.glossary["Chandrian"] == "Chandrian"

    def test_extrae_cada_n_chunks(self):
        model     = make_model('{"glossary": {}, "characters": {}, "decisions": [], "last_scene": "s"}')
        extractor = BibleExtractor(model, extract_every_n=3)

        extractor.extract("o", "t", "sin novedades", chunk_index=1)
        extractor.extract("o", "t", "sin novedades", chunk_index=2)
        result = extractor.extract("o", "t", "sin novedades", chunk_index=3)

        assert result is not None

    def test_falla_silenciosamente_si_modelo_falla(self):
        model = MagicMock()
        model.translate.side_effect = ConnectionError("timeout")
        extractor = BibleExtractor(model)

        result = extractor.extract("o", "t", "notas", chunk_index=0)

        assert result is None   # no lanza excepción

    def test_respuesta_invalida_devuelve_update_vacio(self):
        model     = make_model("esto no es JSON")
        extractor = BibleExtractor(model)

        result = extractor.extract("o", "t", "notas", chunk_index=0)

        assert result is not None
        assert result.glossary   == {}
        assert result.characters == {}

    def test_parsea_json_en_markdown(self):
        json_in_md = '```json\n{"voice":"primera persona","glossary": {"Naming": "Naming"}, "characters": {}, "decisions": [], "last_scene": "s"}\n```'
        model      = make_model(json_in_md)
        extractor  = BibleExtractor(model)

        result = extractor.extract("o", "t", "nuevo: Naming", chunk_index=0)

        assert result.glossary["Naming"] == "Naming"
        assert "primera persona" in result.voice

    def test_parsea_json_anidado_en_bloque_markdown(self):
        """
        El JSON del extractor tiene objetos anidados (glossary, characters).
        El regex greedy debe capturar el JSON completo sin truncarlo.
        """
        json_in_md = (
            "```json\n"
            '{"voice": "tercera persona", '
            '"glossary": {"Naming": "Naming", "Sympathy": "Simpatía"}, '
            '"characters": {"Kvothe": "protagonista"}, '
            '"decisions": [], "last_scene": "llegó"}\n'
            "```"
        )
        model     = make_model(json_in_md)
        extractor = BibleExtractor(model)

        result = extractor.extract("o", "t", "nuevo: Naming", chunk_index=0)

        assert result.glossary["Naming"] == "Naming"
        assert result.glossary["Sympathy"] == "Simpatía"
        assert result.characters["Kvothe"] == "protagonista"

    # ── Validación de candidatos ──────────────────────────────────────────

    def test_incluye_candidatos_en_prompt_cuando_se_proveen(self):
        """
        Cuando se pasan character_candidates, el prompt debe incluir la
        sección de candidatos para que la IA los valide.
        """
        json_resp = '{"glossary": {}, "characters": {"Rimuru": "protagonista"}, "decisions": [], "last_scene": "s"}'
        model     = make_model(json_resp)
        extractor = BibleExtractor(model, extract_every_n=1)

        candidates = {
            "Rimuru": "personaje mencionado en esta escena",
            "Tempest": "personaje mencionado en esta escena",
        }
        extractor.extract("o", "t", "ok", chunk_index=1, character_candidates=candidates)

        prompt_usado = model.translate.call_args[0][0]
        assert "CANDIDATOS" in prompt_usado
        assert "Rimuru" in prompt_usado
        assert "Tempest" in prompt_usado

    def test_sin_candidatos_no_incluye_seccion_candidatos(self):
        """
        Sin character_candidates, el prompt NO debe incluir la sección de candidatos.
        """
        model     = make_model('{"glossary": {}, "characters": {}, "decisions": [], "last_scene": "s"}')
        extractor = BibleExtractor(model, extract_every_n=1)

        extractor.extract("o", "t", "ok", chunk_index=1, character_candidates=None)

        prompt_usado = model.translate.call_args[0][0]
        assert "CANDIDATOS" not in prompt_usado

    def test_candidatos_vacios_no_incluye_seccion(self):
        """
        Con un dict vacío de candidatos, tampoco debe incluirse la sección.
        """
        model     = make_model('{"glossary": {}, "characters": {}, "decisions": [], "last_scene": "s"}')
        extractor = BibleExtractor(model, extract_every_n=1)

        extractor.extract("o", "t", "ok", chunk_index=1, character_candidates={})

        prompt_usado = model.translate.call_args[0][0]
        assert "CANDIDATOS" not in prompt_usado

    def test_personajes_validados_por_ia_se_devuelven_en_update(self):
        """
        La IA confirma solo a Rimuru (descartó Tempest).
        El BibleUpdate debe contener solo a Rimuru con descripción real.
        """
        json_resp = '{"glossary": {}, "characters": {"Rimuru": "protagonista slime, amigable"}, "decisions": [], "last_scene": "escena"}'
        model     = make_model(json_resp)
        extractor = BibleExtractor(model, extract_every_n=1)

        candidates = {
            "Rimuru":  "personaje mencionado en esta escena",
            "Tempest": "personaje mencionado en esta escena",
        }
        result = extractor.extract("o", "t", "ok", chunk_index=1, character_candidates=candidates)

        assert result is not None
        assert "Rimuru" in result.characters
        assert result.characters["Rimuru"] == "protagonista slime, amigable"
        # Tempest no fue confirmado por la IA → no debe estar en el update
        assert "Tempest" not in result.characters

    # ── Campo rejected ────────────────────────────────────────────────────

    def test_candidato_rechazado_incluido_en_rejected(self):
        """
        Si la IA devuelve 'rejected': ['Tempest'], el BibleUpdate debe
        incluirlo en el campo rejected para que la Bible lo elimine.
        """
        json_resp = (
            '{"glossary": {}, "characters": {"Rimuru": "protagonista"}, '
            '"rejected": ["Tempest", "Guardianes"], "decisions": [], "last_scene": "s"}'
        )
        model     = make_model(json_resp)
        extractor = BibleExtractor(model, extract_every_n=1)

        result = extractor.extract("o", "t", "ok", chunk_index=1)

        assert result is not None
        assert "Tempest" in result.rejected
        assert "Guardianes" in result.rejected
        assert "Rimuru" not in result.rejected

    def test_sin_rejected_en_json_devuelve_lista_vacia(self):
        """
        Si la IA no incluye 'rejected' en el JSON, el campo debe ser lista vacía.
        """
        json_resp = '{"glossary": {}, "characters": {}, "decisions": [], "last_scene": "s"}'
        model     = make_model(json_resp)
        extractor = BibleExtractor(model, extract_every_n=1)

        result = extractor.extract("o", "t", "ok", chunk_index=1)

        assert result is not None
        assert result.rejected == []

