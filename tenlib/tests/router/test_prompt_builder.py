# tests/router/test_prompt_builder.py
import pytest
from tenlib.router.prompt_builder import build_translate_prompt


class TestPromptBuilder:

    def test_contiene_idiomas(self):
        prompt = build_translate_prompt("ja", "es")
        assert "ja" in prompt
        assert "es" in prompt

    def test_sin_parametros_opcionales_usa_fallbacks(self):
        prompt = build_translate_prompt("en", "es")
        # Nunca deja secciones vacías
        assert "Sin glosario" in prompt
        assert "Ninguna todavía" in prompt
        assert "Sin perfiles" in prompt
        assert "Inicio del libro" in prompt

    def test_glosario_se_formatea_correctamente(self):
        glossary = {"Naming": "Naming", "Sympathy": "Simpatía"}
        prompt = build_translate_prompt("en", "es", glossary=glossary)
        assert "Naming → Naming" in prompt
        assert "Sympathy → Simpatía" in prompt

    def test_personajes_se_incluyen(self):
        characters = {
            "Kvothe":     "protagonista, habla directo y sin rodeos",
            "Chronicler": "escriba, tono formal y observador",
        }
        prompt = build_translate_prompt("en", "es", characters=characters)
        assert "Kvothe" in prompt
        assert "directo y sin rodeos" in prompt
        assert "Chronicler" in prompt

    def test_orden_cot_en_json_schema(self):
        """notes debe aparecer antes que translation en el schema."""
        prompt = build_translate_prompt("en", "es")
        pos_notes       = prompt.index('"notes"')
        pos_confidence  = prompt.index('"confidence"')
        pos_translation = prompt.index('"translation"')
        assert pos_notes < pos_confidence < pos_translation

    def test_chunk_no_esta_en_el_prompt(self):
        """
        El fragmento viaja como mensaje de usuario, no en el system prompt.
        Verificamos que no hay placeholder {chunk_text} sin resolver.
        """
        prompt = build_translate_prompt("en", "es")
        assert "{chunk_text}" not in prompt
        assert "chunk_text" not in prompt

    def test_decisions_se_listan(self):
        decisions = ["tutear al lector", "mantener 'Naming' sin traducir"]
        prompt = build_translate_prompt("en", "es", decisions=decisions)
        assert "tutear al lector" in prompt
        assert "mantener 'Naming' sin traducir" in prompt

    def test_last_scene_se_incluye(self):
        prompt = build_translate_prompt(
            "en", "es",
            last_scene="Kvothe acaba de llegar a la Universidad"
        )
        assert "Kvothe acaba de llegar a la Universidad" in prompt