from PySide6.QtWidgets import QMessageBox

from piqopiqo.ssf.settings_state import APP_NAME

try:
    # generated in pyinstaller script
    import piqopiqo._build_info as build_info

except ImportError:
    build_info = None


def show_about(parent):
    # TODO setup in the setting ?
    github_url = "https://github.com/gvellut/piqopiqo"

    info = _info()
    link = f'<a href="{github_url}">{github_url}</a>'

    QMessageBox.about(
        parent,
        f"About {APP_NAME}",
        f"<b>{APP_NAME}</b><br/>{info}<br/>{link}",
    )


def _info():
    if build_info:
        version_text = (
            f"Version: <b>v{build_info.VERSION}</b><br/>"
            f"Build SHA: <b>{build_info.GIT_SHA}</b><br/>"
            f"Build date: <b>{build_info.BUILD_DATE}</b>"
        )

        return version_text
    else:
        return "<b>Development</b>"
