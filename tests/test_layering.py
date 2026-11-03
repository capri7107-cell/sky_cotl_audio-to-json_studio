import ast
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
RESTRICTED_PACKAGES = ("midi", "converter", "exporters")
FORBIDDEN_IMPORTS = {"torch", "PySide6"}


def test_core_packages_do_not_import_gui_or_ai_dependencies() -> None:
    violations: list[str] = []

    for package in RESTRICTED_PACKAGES:
        package_dir = PROJECT_ROOT / "src" / "sky_cotl_studio" / package
        assert package_dir.is_dir(), f"Missing package directory: {package_dir}"
        for source_file in package_dir.rglob("*.py"):
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
                    if root_module in FORBIDDEN_IMPORTS:
                        relative_path = source_file.relative_to(PROJECT_ROOT)
                        violations.append(
                            f"{relative_path}:{node.lineno}: forbidden import '{module}'"
                        )

    assert not violations, "\n".join(violations)
