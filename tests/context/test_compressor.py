# tests/context/test_compressor.py
from tenlib.context.bible import BookBible
from tenlib.context.compressor import BibleCompressor


class TestBibleCompressor:

    def setup_method(self):
        self.compressor = BibleCompressor()
        self.bible = BookBible(
            voice      = "tercera persona",
            decisions  = ["mantener 'Naming'"],
            glossary   = {
                "Kvothe":     "Kvothe",
                "Chronicler": "Chronicler",
                "Sympathy":   "Simpatía",
            },
            characters = {
                "Kvothe":     "habla directo",
                "Chronicler": "tono formal",
            },
            last_scene = "Kvothe llegó.",
        )

    def test_filtra_glosario_por_aparicion(self):
        chunk = "Kvothe practicó Sympathy toda la tarde."
        result = self.compressor.compress(self.bible, chunk)

        assert "Kvothe"     in result.glossary
        assert "Sympathy"   in result.glossary
        assert "Chronicler" not in result.glossary

    def test_filtra_personajes_por_aparicion(self):
        chunk = "Kvothe habló sin pausas."
        result = self.compressor.compress(self.bible, chunk)

        assert "Kvothe"     in result.characters
        assert "Chronicler" not in result.characters

    def test_decisions_siempre_presentes(self):
        result = self.compressor.compress(self.bible, "texto sin nombres")
        assert result.decisions == self.bible.decisions

    def test_decisions_se_recortan_si_exceden_limite(self):
        bible = BookBible(
            voice="tercera persona",
            decisions=[f"d{i}" for i in range(20)],
            glossary={},
            characters={},
            last_scene="escena",
        )
        result = self.compressor.compress(bible, "texto")
        assert len(result.decisions) == 8
        assert result.decisions[0] == "d12"

    def test_last_scene_siempre_presente(self):
        result = self.compressor.compress(self.bible, "texto sin nombres")
        assert result.last_scene == self.bible.last_scene

    def test_last_scene_se_trunca_para_prompt(self):
        bible = BookBible(
            voice="tercera persona",
            decisions=[],
            glossary={},
            characters={},
            last_scene="x" * 800,
        )
        result = self.compressor.compress(bible, "texto")
        assert len(result.last_scene) <= 320

    def test_no_modifica_bible_original(self):
        original_len = len(self.bible.glossary)
        self.compressor.compress(self.bible, "texto sin nombres")
        assert len(self.bible.glossary) == original_len

    def test_bible_vacia_pasa_sin_cambios(self):
        bible  = BookBible.empty()
        result = self.compressor.compress(bible, "cualquier texto")
        assert result.is_empty()

    def test_compression_ratio_bible_vacia(self):
        bible = BookBible.empty()
        ratio = self.compressor.compression_ratio(bible, bible)
        assert ratio == 1.0

    def test_compression_ratio_reduccion(self):
        chunk      = "Kvothe caminó."
        compressed = self.compressor.compress(self.bible, chunk)
        ratio      = self.compressor.compression_ratio(self.bible, compressed)
        assert ratio < 1.0

