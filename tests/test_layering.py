import ast
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
TORCH_FORBIDDEN_PACKAGES = {"gui", "pipeline", "midi", "converter", "exporters"}


def test_core_packages_do_not_import_gui_or_ai_dependencies() -> None:
    violations: list[str] = []

    source_root = PROJECT_ROOT / "src" / "sky_cotl_studio"
    assert (source_root / "gui").is_dir()
    for source_file in source_root.rglob("*.py"):
        relative_package = source_file.relative_to(source_root).parts[0]
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules = (alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules = (node.module,)
            else:
                continue

            for module in imported_modules:
                root_module = module.split(".", maxsplit=1)[0]
                forbidden = (
                    root_module == "PySide6" and relative_package != "gui"
                ) or (
                    root_module == "torch"
                    and relative_package in TORCH_FORBIDDEN_PACKAGES
                )
                if forbidden:
                    relative_path = source_file.relative_to(PROJECT_ROOT)
                    violations.append(
                        f"{relative_path}:{node.lineno}: forbidden import '{module}'"
                    )

    assert not violations, "\n".join(violations)
