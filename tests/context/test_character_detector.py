from tenlib.context.character_detector import extract_character_mentions


class TestCharacterDetector:

    def test_filtra_ruido_capitalizado(self):
        text = (
            "Estaba oscuro. Eso fue todo. "
            "Rimuru avanzó. Rimuru respiró hondo."
        )
        result = extract_character_mentions("", text)
        assert "Rimuru" in result
        assert "Estaba" not in result
        assert "Eso" not in result

    def test_preserva_nombre_valido_ultima(self):
        text = (
            "Ultima atacó primero. "
            "Luego Ultima dijo que no retrocedería."
        )
        result = extract_character_mentions("", text)
        assert "Ultima" in result

    def test_personaje_conocido_se_mantiene_aunque_tenga_poca_evidencia(self):
        existing = {"Luminas": "líder reservada"}
        text = "Nadie podía competir con Luminas en ese terreno."
        result = extract_character_mentions("", text, existing_characters=existing)
        assert "Luminas" in result

    def test_respeta_max_characters(self):
        text = (
            "Rimuru avanzó. Benimaru respondió. Souei observó. "
            "Shion gritó. Veldora rió. Hinata atacó. Diablo sonrió."
        )
        result = extract_character_mentions("", text, max_characters=3)
        assert len(result) == 3

    # ── Filtro genitivo (de/del = lugar/organización) ─────────────────────

    def test_no_detecta_organizacion_solo_contexto_genitivo(self):
        """
        "Tempest" aparece exclusivamente después de "de" →
        señal de organización/lugar, no de personaje individual.
        """
        text = (
            "Los ejecutivos de Tempest decidieron actuar. "
            "El director de Tempest firmó el documento."
        )
        result = extract_character_mentions("", text)
        assert "Tempest" not in result

    def test_personaje_tras_preposicion_no_genitiva_no_es_filtrado(self):
        """
        "a Diego" usa la preposición personal (no genitiva).
        El filtro de de/del no debe aplicarse aquí.
        """
        text = (
            "María miró a Diego con curiosidad. "
            "Después, María volvió a mirar a Diego."
        )
        result = extract_character_mentions("", text)
        assert "Diego" in result

    def test_nombre_con_ocurrencias_mixtas_no_es_filtrado(self):
        """
        "Feldway" aparece tanto tras "a" como tras "de".
        Como no es 100% genitivo, no debe filtrarse.
        """
        text = (
            "¿Y luego vas a desafiar a Feldway? "
            "Al bastardo de Feldway no le importará. "
            "Intentaremos encargarnos de Feldway juntos."
        )
        result = extract_character_mentions("", text)
        assert "Feldway" in result

    # ── NON_CHARACTER_WORDS: títulos de grupo y números ───────────────────

    def test_no_detecta_titulo_de_grupo_guardianes(self):
        """
        "Guardianes" es un sustantivo colectivo, no un personaje individual.
        Debe estar en la lista de stopwords.
        """
        text = (
            "Los Doce Guardianes del Laberinto estaban reunidos. "
            "Los Guardianes asistieron a la reunión."
        )
        result = extract_character_mentions("", text)
        assert "Guardianes" not in result

    def test_no_detecta_numero_como_personaje(self):
        """
        "Doce" (número que aparece capitalizado como parte de un título)
        no debe ser detectado como personaje.
        """
        text = (
            "Los Doce Guardianes del Laberinto estaban presentes. "
            "Los Doce acordaron la estrategia."
        )
        result = extract_character_mentions("", text)
        assert "Doce" not in result

    def test_no_detecta_angeles_como_personaje(self):
        """
        "Ángeles" es un título colectivo, no un personaje individual.
        """
        text = (
            "Los Siete Ángeles de la Muerte marchaban juntos. "
            "Los Ángeles atacaron el laberinto."
        )
        result = extract_character_mentions("", text)
        assert "Ángeles" not in result
        assert "Angeles" not in result

    # ── Test con texto real del prólogo ───────────────────────────────────

    def test_prologo_malo_detecta_personajes_principales(self):
        """
        Usando fragmentos representativos del prólogo real (versión mala),
        los personajes con suficiente contexto narrativo deben detectarse
        y las organizaciones/colectivos no.

        Nota: un personaje que aparece solo una vez al inicio de frase no tiene
        suficiente evidencia para ser detectado de forma segura (evita ruido).
        """
        prologo_malo = (
            # Rimuru → muchas menciones, contexto fuerte
            "Se dieron cuenta de que Rimuru era su única esperanza. "
            "Souei les dijo que Rimuru había desaparecido. "
            "Souei le dijo que Rimuru había desaparecido. "
            # Souei → diálogos y acciones
            "\"Sí... Estoy seguro.\" Souei responde con una voz llena de pesar. "
            "Souei, que suele mantener la calma, rompió el escritorio en un ataque de ira. "
            # Diablo → diálogo y acción
            "Diablo dejó escapar un suspiro de alivio. "
            "\"No seas tan engreído, Souei.\" dijo Diablo. "
            # Zegion → discurso y movimiento
            "Zegion se movió. Zegion dijo con gravedad: Tonterías. "
            # Benimaru → múltiples menciones con acción y diálogo
            "Benimaru apretó los puños con fuerza. "
            "Benimaru estuvo de acuerdo con un gran movimiento de cabeza. "
            "\"Bueno, tenemos que demostrarle a Rimuru-sama.\" Dijo Benimaru. "
            # Organización → solo genitivo, debe filtrarse
            "Los ejecutivos de Tempest comenzaron a moverse. "
            "Los altos funcionarios de Tempest se pusieron en marcha."
        )
        result = extract_character_mentions("", prologo_malo)

        # Personajes reales con evidencia suficiente → deben detectarse
        assert "Rimuru" in result
        assert "Souei" in result
        assert "Diablo" in result
        assert "Zegion" in result
        assert "Benimaru" in result

        # Organización (solo aparece tras "de") → NO debe detectarse
        assert "Tempest" not in result
