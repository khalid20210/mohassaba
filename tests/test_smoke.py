from pathlib import Path


def test_project_layout_has_entrypoint():
    assert Path("app.py").exists()


def test_app_factory_is_importable():
    import modules

    assert callable(modules.create_app)
