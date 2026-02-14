In src/piqopiqo/copy_sd.py in CopySdWorker run : eject_volume is called at the end (if not cancelled)
The decision to eject is made in original dialog :
CopySdInputDialog constuctor :

        self.eject_checkbox = QCheckBox("Eject SD card after copy")
        self.eject_checkbox.setChecked(should_eject)
        layout.addWidget(self.eject_checkbox)

However : I would like for the checkbox to eject to be shown to the user at the end : 
in CopySdWorker  _on_finished : change the dialog and add the checkbox (depending on the value that came from should_eject)
(not when cancelled : never ejected like now)

And the ejection to happen on OK by the user and after the dialog close, with another dialog shown if the ejection could not be performed, instead of being done at the end of the copy