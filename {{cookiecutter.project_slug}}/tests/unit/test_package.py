from {{ cookiecutter.package_name }} import __version__, greet


def test_package() -> None:
    assert __version__ == "0.1.0"
    assert greet("Python") == "Hello, Python!"
