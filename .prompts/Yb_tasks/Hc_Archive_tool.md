Create an Archive tool : separate section : Tool > Archive...

- add a section in the Tool external tab : Archive : with "Desination" and choose folder button ; save it in the UserSettings

The tool will do : 
- First display a dialog to confirm : which fodler is going to be moved and where ; Cancel OK (ok default)
- add a checkbox for saving the exif during the copy ; save that checkbox state in the States
- takes into account the full folder (not just the visible / filtered photos)
- move the current folder to destination folder (to be set in the Settings panel) : if current folder is 20250502_annecy (with 2 subfolders xs20 and tz95) => copy 20250502_annecy below the destination folder
- if set : save the EXIF after the move or during : whatever takes the least step
- also delete cache + DB for all the current folders (xs20 and tz95 in the example above ; 20250502_annecy if there are photos too) ; not any other
- do the work in the background (do not block GUI Thread)
- at the end leave "No folder" as the state of the app