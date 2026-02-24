import pytest
from unittest.mock import MagicMock, patch
from tenlib.router.router import Router, AllModelsExhaustedError
from tenlib.router.models import ModelResponse
import anthropic


def make_model(name: str, available: bool, response=None, raises=None):
    model = MagicMock()
    model.name = name
    model.is_available.return_value = available
    if raises:
        model.translate.side_effect = raises
    elif response:
        model.translate.return_value = response
    return model


def sample_response(model_name: str) -> ModelResponse:
    return ModelResponse(
        translation   = "Texto traducido",
        confidence    = 0.9,
        notes         = "ok",
        model_used    = model_name,
        tokens_input  = 100,
        tokens_output = 150,
    )


class TestRouter:

    def test_usa_primer_modelo_disponible(self):
        m1 = make_model("gemini", available=True, response=sample_response("gemini"))
        m2 = make_model("claude", available=True, response=sample_response("claude"))
        router = Router([m1, m2])

        result = router.translate("chunk", "system_prompt")

        assert result.model_used == "gemini"
        m2.translate.assert_not_called()

    def test_salta_modelo_no_disponible(self):
        m1 = make_model("gemini", available=False)
        m2 = make_model("claude", available=True, response=sample_response("claude"))
        router = Router([m1, m2])

        result = router.translate("chunk", "system_prompt")

        assert result.model_used == "claude"
        m1.translate.assert_not_called()

    def test_failover_por_error_de_red(self):
        m1 = make_model("gemini", available=True,
                        raises=ConnectionError("timeout"))
        m2 = make_model("claude", available=True,
                        response=sample_response("claude"))
        router = Router([m1, m2])

        result = router.translate("chunk", "system_prompt")

        assert result.model_used == "claude"

    def test_todos_no_disponibles_lanza_error(self):
        m1 = make_model("gemini", available=False)
        m2 = make_model("claude", available=False)
        router = Router([m1, m2])

        with pytest.raises(AllModelsExhaustedError):
            router.translate("chunk", "system_prompt")

    def test_error_de_contenido_no_hace_failover(self):
        error = anthropic.BadRequestError(
            message="content policy",
            response=MagicMock(),
            body={},
        )
        m1 = make_model("claude", available=True, raises=error)
        m2 = make_model("gemini", available=True, response=sample_response("gemini"))
        router = Router([m1, m2])

        with pytest.raises(anthropic.BadRequestError):
            router.translate("chunk", "system_prompt")

        m2.translate.assert_not_called()

    def test_router_sin_modelos_lanza_error(self):
        with pytest.raises(ValueError):
            Router([])

    def test_available_models_lista_correcta(self):
        m1 = make_model("gemini", available=True)
        m2 = make_model("claude", available=False)
        m3 = make_model("gpt",    available=True)
        router = Router([m1, m2, m3])

        available = router.available_models()
        assert available == ["gemini", "gpt"]