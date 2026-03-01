# tests/context/test_bible.py
import pytest
from context.bible import BookBible, BibleUpdate


class TestBookBible:

    def test_bible_vacia_al_crear(self):
        bible = BookBible.empty()
        assert bible.is_empty()
        assert bible.glossary   == {}
        assert bible.characters == {}
        assert bible.decisions  == []

    def test_apply_agrega_glosario(self):
        bible  = BookBible.empty()
        update = BibleUpdate(glossary={"Naming": "Naming"})
        bible.apply(update)
        assert bible.glossary["Naming"] == "Naming"

    def test_apply_no_sobreescribe_existente(self):
        bible = BookBible.empty()
        bible.glossary["Sympathy"] = "Simpatía"

        update = BibleUpdate(glossary={"Sympathy": "Otro valor"})
        bible.apply(update)

        assert bible.glossary["Sympathy"] == "Simpatía"  # no cambió

    def test_apply_no_duplica_decisions(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(decisions=["mantener 'Naming'"]))
        bible.apply(BibleUpdate(decisions=["mantener 'Naming'"]))
        assert bible.decisions.count("mantener 'Naming'") == 1

    def test_apply_actualiza_last_scene(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(last_scene="Kvothe llegó a la Universidad"))
        assert "Universidad" in bible.last_scene

    def test_apply_sin_last_scene_no_cambia_anterior(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(last_scene="Escena anterior"))
        bible.apply(BibleUpdate(last_scene=None))
        assert "anterior" in bible.last_scene

    def test_apply_actualiza_voice_si_viene_en_update(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(voice="narrador en primera persona, tiempo pasado"))
        assert "primera persona" in bible.voice

    def test_apply_filtra_personajes_no_validos(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={
            "Rimuru": "ok",
            "Estaba": "ruido",
            "Eso": "ruido",
        }))
        assert "Rimuru" in bible.characters
        assert "Estaba" not in bible.characters
        assert "Eso" not in bible.characters

    def test_apply_acepta_ultima_como_nombre_valido(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={"Ultima": "demonio primordial"}))
        assert "Ultima" in bible.characters

    def test_apply_dedup_decisions_similares(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(decisions=[
            "Se mejoró la fluidez general y la puntuación."
        ]))
        bible.apply(BibleUpdate(decisions=[
            "Se mejoro la fluidez general y la puntuacion."
        ]))
        assert len(bible.decisions) == 1

    def test_apply_limita_decisions_para_controlar_tokens(self):
        bible = BookBible.empty()
        for i in range(30):
            bible.apply(BibleUpdate(decisions=[f"decisión {i}"]))
        assert len(bible.decisions) <= 18

    def test_apply_recorta_last_scene_muy_largo(self):
        bible = BookBible.empty()
        bible.apply(BibleUpdate(last_scene="x" * 1000))
        assert len(bible.last_scene) <= 420

    def test_serializa_y_deserializa(self):
        bible = BookBible(
            voice      = "tercera persona",
            decisions  = ["tutear al lector"],
            glossary   = {"Kvothe": "Kvothe"},
            characters = {"Kvothe": "habla directo"},
            last_scene = "Llegó a la Universidad",
        )
        restored = BookBible.from_json(bible.to_json())
        assert restored.voice            == bible.voice
        assert restored.glossary         == bible.glossary
        assert restored.characters       == bible.characters
        assert restored.decisions        == bible.decisions
        assert restored.last_scene       == bible.last_scene

    # ── Actualización de descripciones genéricas ──────────────────────────

    def test_apply_actualiza_descripcion_generica_con_info_real(self):
        """
        El detector local añade con descripción genérica.
        El AI extractor luego aporta una descripción real → debe actualizarse.
        """
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={"Rimuru": "personaje mencionado en esta escena"}))
        assert bible.characters["Rimuru"] == "personaje mencionado en esta escena"

        bible.apply(BibleUpdate(characters={"Rimuru": "protagonista slime, tono amigable y decidido"}))
        assert bible.characters["Rimuru"] == "protagonista slime, tono amigable y decidido"

    def test_apply_no_sobreescribe_descripcion_real_con_otra_real(self):
        """
        Una descripción real (no genérica) NO debe sobrescribirse con otra descripción.
        El primer valor real que se asigne es el que persiste.
        """
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={"Rimuru": "protagonista slime, tono amigable"}))
        bible.apply(BibleUpdate(characters={"Rimuru": "descripción alternativa diferente"}))
        assert bible.characters["Rimuru"] == "protagonista slime, tono amigable"

    def test_apply_no_sobreescribe_generica_con_generica(self):
        """
        Si la nueva descripción también es genérica, no reemplazar.
        """
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={"Rimuru": "personaje mencionado en esta escena"}))
        bible.apply(BibleUpdate(characters={"Rimuru": "personaje mencionado en esta escena"}))
        # Solo debe haber una entrada, sin cambio
        assert bible.characters["Rimuru"] == "personaje mencionado en esta escena"
        assert len(bible.characters) == 1

    # ── Campo rejected ────────────────────────────────────────────────────

    def test_apply_elimina_personaje_rechazado(self):
        """
        La IA indica que 'Tempest' no es un personaje real.
        Debe eliminarse de la Bible aunque haya sido añadido antes.
        """
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={"Tempest": "personaje mencionado en esta escena"}))
        assert "Tempest" in bible.characters

        bible.apply(BibleUpdate(rejected=["Tempest"]))
        assert "Tempest" not in bible.characters

    def test_apply_rejected_no_afecta_personajes_validos(self):
        """
        Rechazar un nombre no elimina otros personajes de la Bible.
        """
        bible = BookBible.empty()
        bible.apply(BibleUpdate(characters={
            "Rimuru": "protagonista",
            "Tempest": "personaje mencionado en esta escena",
        }))

        bible.apply(BibleUpdate(rejected=["Tempest"]))
        assert "Rimuru" in bible.characters
        assert "Tempest" not in bible.characters

    def test_apply_rejected_nombre_inexistente_no_falla(self):
        """
        Rechazar un nombre que nunca estuvo en la Bible no debe lanzar error.
        """
        bible = BookBible.empty()
        bible.apply(BibleUpdate(rejected=["Inexistente"]))  # no falla
