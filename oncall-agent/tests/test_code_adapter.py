"""
Tests para adapters/code_adapter.py -- search_functions_by_keyword debe
buscar por palabras individuales, no por frase exacta (bug real: la
consulta "configuracion de la base de datos" nunca encontraba
database_url porque buscaba la frase literal completa, Paso 376 del
proyecto).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adapters.code_adapter import search_functions_by_keyword


def _fake_knowledge_base():
    return {
        "funciones": [
            {
                "name": "database_url",
                "file": "app/core/config.py",
                "source_code": "def database_url(self) -> str:\n    return f'postgresql://{self.DB_HOST}'",
            },
            {
                "name": "get_connection",
                "file": "app/services/db_service.py",
                "source_code": "def get_connection():\n    return psycopg2.connect(database_url())",
            },
            {
                "name": "send_notification",
                "file": "app/services/notifier.py",
                "source_code": "def send_notification(msg):\n    requests.post(SLACK_URL, json={'text': msg})",
            },
        ]
    }


def test_busqueda_frase_natural_encuentra_por_palabras_individuales():
    kb = _fake_knowledge_base()
    results = search_functions_by_keyword(kb, "configuracion de la base de datos")

    names = [r["name"] for r in results]
    assert "database_url" in names, "Deberia encontrar database_url por la palabra 'base'/'datos'"


def test_stopwords_no_generan_falsos_positivos():
    kb = _fake_knowledge_base()
    # "de la" son puras stopwords -- sin ninguna palabra real de busqueda,
    # no deberia devolver resultados masivos irrelevantes
    results = search_functions_by_keyword(kb, "de la")
    # con el fallback de usar la frase completa como ultimo recurso,
    # esto no debe encontrar coincidencias reales
    assert len(results) == 0 or all(
        "de la" in r.get("source_code", "").lower() for r in results
    )


def test_busqueda_no_relacionada_no_encuentra_nada_relevante():
    kb = _fake_knowledge_base()
    results = search_functions_by_keyword(kb, "autenticacion oauth")
    names = [r["name"] for r in results]
    assert "database_url" not in names
    assert "send_notification" not in names


def test_resultados_rankeados_por_relevancia():
    kb = _fake_knowledge_base()
    results = search_functions_by_keyword(kb, "database connection")
    names = [r["name"] for r in results]
    # get_connection menciona "database_url" Y "connect" -- deberia
    # rankear al menos tan alto como database_url solo
    assert names[0] in ("get_connection", "database_url")
