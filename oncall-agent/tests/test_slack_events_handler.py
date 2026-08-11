"""
Tests para core/slack_events_handler.py -- _looks_like_malformed_function_call
evita que respuestas rotas del LLM se guarden en el historial de
conversacion y contaminen preguntas futuras del mismo hilo (bug real
encontrado en el Paso 443 del proyecto).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.slack_events_handler import _looks_like_malformed_function_call


def test_detecta_function_call_malformada():
    texto = '<function>leer_archivo{"ruta_relativa":"app/services/db_service.py"}</function>'
    assert _looks_like_malformed_function_call(texto) is True


def test_detecta_variante_con_igual():
    texto = '<function=leer_archivo{"ruta_relativa": "app/services/db_service.py"}</function>'
    assert _looks_like_malformed_function_call(texto) is True


def test_respuesta_normal_no_se_marca_como_malformada():
    texto = "La funcion que causo el error es 'chat' en app/api/routes.py, linea 66."
    assert _looks_like_malformed_function_call(texto) is False


def test_texto_vacio_se_considera_malformado():
    assert _looks_like_malformed_function_call("") is True
    assert _looks_like_malformed_function_call(None) is True


def test_respuesta_larga_normal_no_se_marca():
    texto = (
        "El archivo app/core/config.py define DATABASE_URL como una "
        "propiedad calculada. Aqui esta el codigo relevante:\n\n"
        "def database_url(self) -> str:\n    return f'postgresql://...'"
    )
    assert _looks_like_malformed_function_call(texto) is False
