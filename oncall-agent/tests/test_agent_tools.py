"""
Tests para core/agent_tools.py -- _normalizar_ruta arreglo un bug real
donde el LLM generaba rutas con prefijos de CI/CD (../external-projects/)
que no existen en S3 (Paso 427 del proyecto).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_tools import _normalizar_ruta


def test_normaliza_prefijo_external_projects():
    ruta = "../external-projects/moto-chatbot/app/api/routes.py"
    resultado = _normalizar_ruta("moto-chatbot", ruta)
    assert resultado == "app/api/routes.py"


def test_normaliza_prefijo_monitored_systems():
    ruta = "../monitored-systems/rag-demo/lambda/handler.py"
    resultado = _normalizar_ruta("rag-demo", ruta)
    assert resultado == "lambda/handler.py"


def test_normaliza_prefijo_nombre_proyecto_solo():
    ruta = "moto-chatbot/app/core/config.py"
    resultado = _normalizar_ruta("moto-chatbot", ruta)
    assert resultado == "app/core/config.py"


def test_ruta_ya_correcta_no_se_modifica():
    ruta = "app/api/routes.py"
    resultado = _normalizar_ruta("moto-chatbot", ruta)
    assert resultado == "app/api/routes.py"


def test_ruta_con_slash_inicial_se_limpia():
    ruta = "/app/api/routes.py"
    resultado = _normalizar_ruta("moto-chatbot", ruta)
    assert resultado == "app/api/routes.py"
