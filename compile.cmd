echo off
uv run python -m nuitka --standalone --plugin-enable=pyside6 --output-dir=dist --windows-console-mode=disable main.py