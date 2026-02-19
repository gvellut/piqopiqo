- clean up main_window : too many unrelated stuff
for example :


move dialogs / components / callbacks that do significant work to submodules
like 
    def _on_copy_from_sd(self):
        from .copy_sd import launch_copy_sd

        launch_copy_sd(self)

like :
_on_apply_gpx => gpx2exif submodule

+ utility like ensure metadata db ready to metadata db module

- reorder the panels module : there are dialogs, screens ,... There is also a components module
make it coherents

propose a reorg plan. Do not add or remove any functionality. Just the physical reorganisation (although can add or remove parameters since change of scope)
