"""
Tests para onboarding/structural_scan.py -- scan_directory debe excluir
directorios de build/dependencias (bug real: el wizard de onboarding
detecto 744 funciones falsas de wrapt/aws-xray-sdk empaquetados en
terraform/build/, Paso 281 del proyecto).
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from onboarding.structural_scan import scan_directory, EXCLUDED_DIR_NAMES


def test_excluye_directorio_build():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "app").mkdir()
        (root / "app" / "handler.py").write_text("def real_function():\n    pass\n")

        (root / "terraform" / "build" / "package" / "wrapt").mkdir(parents=True)
        (root / "terraform" / "build" / "package" / "wrapt" / "core.py").write_text(
            "def fake_dependency_function():\n    pass\n" * 10
        )

        results = scan_directory(root)
        all_files_scanned = [r.file for r in results]

        assert any("app/handler.py" in f for f in all_files_scanned)
        assert not any("terraform/build" in f for f in all_files_scanned)


def test_excluye_venv_y_node_modules():
    assert ".venv" in EXCLUDED_DIR_NAMES
    assert "node_modules" in EXCLUDED_DIR_NAMES
    assert "__pycache__" in EXCLUDED_DIR_NAMES
    assert "build" in EXCLUDED_DIR_NAMES


def test_escanea_archivos_python_normales():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "handler.py").write_text(
            "def process_upload():\n"
            "    try:\n"
            "        pass\n"
            "    except:\n"
            "        pass\n"
        )

        results = scan_directory(root)
        assert len(results) == 1
        assert len(results[0].functions) == 1
        assert results[0].functions[0].name == "process_upload"
        assert results[0].error_blocks[0].risk == "alto"
