# Notebooks

`notebooks/*.py` in Jupytext `py:percent` format is the versioned source.
`.ipynb` files and checkpoint directories are ignored.

```bash
uv run jupytext --to ipynb notebooks/01_example.py
make notebook
```

Open the paired notebook in JupyterLab; saving updates the paired `.py` via
`jupytext.toml`. Outside Jupyter, synchronize explicitly with
`uv run jupytext --sync notebooks/01_example.ipynb`.
After editing text externally, synchronize before reopening the notebook.
Only the text file belongs in Git. The installed editable package is directly
importable using `from {{ cookiecutter.package_name }} import greet`.
Move reusable code to src rather than copying notebook cells.
