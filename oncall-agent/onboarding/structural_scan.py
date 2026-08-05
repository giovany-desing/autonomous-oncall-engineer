"""
Pasada 1 del onboarding: análisis estructural vía Tree-sitter.
Cataloga funciones, bloques de manejo de errores clasificados por riesgo,
y llamadas salientes a servicios externos.
"""
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from tree_sitter_language_pack import get_parser

RISK_HIGH = "alto"
RISK_MEDIUM = "medio"
RISK_LOW = "bajo"

DIRECT_CALL_MARKERS = {
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "httpx.get", "httpx.post", "psycopg2.connect", "pymongo.MongoClient",
}

CLIENT_FACTORY_MARKERS = {
    "boto3.client", "boto3.resource",
}


@dataclass
class ErrorHandlingBlock:
    file: str
    line_start: int
    line_end: int
    exception_type: str
    has_logging: bool
    has_reraise: bool
    is_bare_except: bool
    risk: str
    enclosing_function: str


@dataclass
class FunctionInfo:
    file: str
    name: str
    line_start: int
    line_end: int
    external_calls: list = field(default_factory=list)
    source_code: str = ""


@dataclass
class ScanResult:
    file: str
    functions: list
    error_blocks: list


def _node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf8")


def _find_enclosing_function(node, source: bytes) -> str:
    current = node.parent
    while current is not None:
        if current.type == "function_definition":
            name_node = current.child_by_field_name("name")
            if name_node:
                return _node_text(name_node, source)
        current = current.parent
    return "<module>"


def _build_client_symbol_table(root, source: bytes) -> dict:
    """
    Recorre todo el árbol buscando asignaciones del tipo:
        s3 = boto3.client("s3")
        table = boto3.resource("dynamodb").Table("x")
    y devuelve {nombre_variable: "boto3.client(...)"} para poder
    reconocer después llamadas como s3.get_object(...) como externas.
    """
    symbols = {}

    def walk(node):
        if node.type == "assignment":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is not None and right is not None and left.type == "identifier":
                right_text = _node_text(right, source)
                for marker in CLIENT_FACTORY_MARKERS:
                    if marker in right_text:
                        var_name = _node_text(left, source)
                        symbols[var_name] = marker
                        break
        for child in node.children:
            walk(child)

    walk(root)
    return symbols


def _detect_external_calls(node, source: bytes, client_symbols: dict) -> list:
    calls = []
    if node.type == "call":
        func_node = node.child_by_field_name("function")
        call_text = _node_text(node, source)

        if func_node is not None and func_node.type == "attribute":
            obj_node = func_node.child_by_field_name("object")
            if obj_node is not None and obj_node.type == "identifier":
                var_name = _node_text(obj_node, source)
                if var_name in client_symbols:
                    calls.append(_node_text(func_node, source))

        for marker in DIRECT_CALL_MARKERS:
            if marker in call_text:
                calls.append(call_text.split("(")[0])
                break

    for child in node.children:
        calls.extend(_detect_external_calls(child, source, client_symbols))
    return calls


def _classify_risk(except_clause, source: bytes) -> tuple:
    has_logging = False
    has_reraise = False
    is_bare = except_clause.child_by_field_name("type") is None

    body = None
    for child in except_clause.children:
        if child.type == "block":
            body = child
            break

    if body is not None:
        body_text = _node_text(body, source)
        if any(kw in body_text for kw in ["log.", "logger.", "logging.", "print("]):
            has_logging = True
        if "raise" in body_text:
            has_reraise = True
        if body_text.strip() == "pass" or body_text.strip() == "":
            has_logging = False

    if is_bare and not has_logging and not has_reraise:
        risk = RISK_HIGH
    elif not has_logging and not has_reraise:
        risk = RISK_MEDIUM
    elif has_logging or has_reraise:
        risk = RISK_LOW
    else:
        risk = RISK_MEDIUM

    return is_bare, has_logging, has_reraise, risk


def scan_file(filepath: Path) -> ScanResult:
    parser = get_parser("python")
    source = filepath.read_bytes()
    tree = parser.parse(source)
    root = tree.root_node

    client_symbols = _build_client_symbol_table(root, source)

    functions = []
    error_blocks = []

    def walk(node):
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source) if name_node else "<anon>"
            external_calls = _detect_external_calls(node, source, client_symbols)
            function_source = _node_text(node, source)
            if len(function_source) > 3000:
                function_source = function_source[:3000] + "\n... (truncado)"
            functions.append(FunctionInfo(
                file=str(filepath),
                name=name,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                external_calls=external_calls,
                source_code=function_source,
            ))

        if node.type == "except_clause":
            type_node = node.child_by_field_name("type")
            exc_type = _node_text(type_node, source) if type_node else "Exception (bare)"
            is_bare, has_log, has_reraise, risk = _classify_risk(node, source)
            error_blocks.append(ErrorHandlingBlock(
                file=str(filepath),
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                exception_type=exc_type,
                has_logging=has_log,
                has_reraise=has_reraise,
                is_bare_except=is_bare,
                risk=risk,
                enclosing_function=_find_enclosing_function(node, source),
            ))

        for child in node.children:
            walk(child)

    walk(root)
    return ScanResult(file=str(filepath), functions=functions, error_blocks=error_blocks)


EXCLUDED_DIR_NAMES = {
    ".venv", "venv", "__pycache__", "node_modules", "build", "dist",
    "site-packages", ".git", ".terraform",
}


def scan_directory(root: Path) -> list:
    results = []
    for py_file in root.rglob("*.py"):
        if any(part in EXCLUDED_DIR_NAMES for part in py_file.parts):
            continue
        results.append(scan_file(py_file))
    return results


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    results = scan_directory(target)
    output = [
        {"file": r.file, "functions": [asdict(f) for f in r.functions],
         "error_blocks": [asdict(e) for e in r.error_blocks]}
        for r in results
    ]
    print(json.dumps(output, indent=2, ensure_ascii=False))
# CI/CD verificado: Mon Jul 27 13:50:52 -05 2026
