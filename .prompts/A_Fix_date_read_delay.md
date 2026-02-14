- Copy SD : OK after first dialog seems to make the GUI lag and unresponsive : because reads all the photos on SD to extract created Date (file system)  => it takes time for 8000 files. Do in background thread not the GUI thread ?

to_dates function called :

try:
            dates = to_dates(date_spec, volume)
        except ValueError:
            QMessageBox.warning(
                parent, "Copy from SD", "Invalid date spec. Please try again."
            )
            continue

in src/piqopiqo/copy_sd.py inside launch_copy_sd function