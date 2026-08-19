"""
Tests para la logica de descarga/cacheo del modelo de embeddings en
memory/postmortem_store.py. Mockea fastembed y boto3 -- nunca descarga
el modelo real (235MB) ni sale a la red durante los tests.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory.postmortem_store as pm_store


def _reset_global_cache(monkeypatch):
    monkeypatch.setattr(pm_store, "_embedding_model_instance", None)


def test_ensure_embedding_model_downloaded_descarga_archivos_del_prefijo(mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(pm_store, "EMBEDDING_MODEL_CACHE_DIR", str(tmp_path))

    mock_client = mocker.MagicMock()
    mock_paginator = mocker.MagicMock()
    mock_client.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {"Contents": [
            {"Key": f"{pm_store.EMBEDDING_MODEL_S3_PREFIX}/config.json"},
            {"Key": f"{pm_store.EMBEDDING_MODEL_S3_PREFIX}/model_optimized.onnx"},
        ]}
    ]

    pm_store._ensure_embedding_model_downloaded(s3_client=mock_client)

    assert mock_client.download_file.call_count == 2
    marker = tmp_path / ".download_complete"
    assert marker.exists()


def test_ensure_embedding_model_downloaded_no_redescarga_si_marcador_existe(mocker, monkeypatch, tmp_path):
    monkeypatch.setattr(pm_store, "EMBEDDING_MODEL_CACHE_DIR", str(tmp_path))
    (tmp_path / ".download_complete").write_text("ok")

    mock_client = mocker.MagicMock()

    pm_store._ensure_embedding_model_downloaded(s3_client=mock_client)

    mock_client.get_paginator.assert_not_called()
    mock_client.download_file.assert_not_called()


def test_get_embedding_model_cachea_instancia_entre_llamadas(mocker, monkeypatch, tmp_path):
    _reset_global_cache(monkeypatch)
    monkeypatch.setattr(pm_store, "_ensure_embedding_model_downloaded", mocker.MagicMock())

    mock_text_embedding_class = mocker.MagicMock()
    mocker.patch("fastembed.TextEmbedding", mock_text_embedding_class)

    model_1 = pm_store._get_embedding_model()
    model_2 = pm_store._get_embedding_model()

    assert model_1 is model_2
    mock_text_embedding_class.assert_called_once()


def test_embed_text_usa_modelo_cacheado_y_convierte_a_lista(mocker, monkeypatch):
    _reset_global_cache(monkeypatch)

    fake_embedding = mocker.MagicMock()
    fake_embedding.tolist.return_value = [0.1, 0.2, 0.3]

    fake_model = mocker.MagicMock()
    fake_model.embed.return_value = iter([fake_embedding])

    monkeypatch.setattr(pm_store, "_get_embedding_model", lambda s3_client=None: fake_model)

    result = pm_store._embed_text("texto de prueba")

    assert result == [0.1, 0.2, 0.3]
    fake_model.embed.assert_called_once_with(["texto de prueba"])
