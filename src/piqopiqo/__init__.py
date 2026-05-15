"""PiqoPiqo photo viewer application."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("piqopiqo")
except PackageNotFoundError:
    __version__ = "0+unknown"
