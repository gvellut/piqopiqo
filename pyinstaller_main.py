import multiprocessing

from piqopiqo.__main__ import cli

if __name__ == "__main__":
    multiprocessing.freeze_support()
    cli()
