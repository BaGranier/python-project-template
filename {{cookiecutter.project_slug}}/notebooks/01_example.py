# %% [markdown]
# # Example notebook
# Keep reusable functions in src/; this text file is the Git source of truth.

# %%
from {{ cookiecutter.package_name }} import greet

print(greet("notebook"))
