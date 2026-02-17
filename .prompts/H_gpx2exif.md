Look at /Users/guilhem/Documents/projects/github/gpx2exif

- this project takes the existing photos based on the Date Time Original, optionally applies a time shift (if the times in the photo / camera and the times in the GPX do not correspond), reads the position at the time from the GPX and sets the GPS EXIF tags in the image files
- You will need to redo the functionalities in this project. Do not make any code reference to that project : it will not be a dependency. You can look or copy the code and reapply it here.

!!!! Contrary to the reference gpx2exif : in piqopiqo there is no EXIF processed. The time taken (for reading) is in the Metadata DB + the latitude / longitude also are (for writing). So update the SQLLIte DB, not the image files. !!!!

- There are 2 workflows that piqopiqo needs to have and that you will implement :
- read the time in an image using GCP Cloud Vision : gpx2exif has this in time_extractor.py.
- sets the GPS EXif tags on the photos using an input GPX :  gpx2exif has this in common.py and gpx2exif.py

piqopiqo should use similar input (but selected or set  in the GUI at specific locations like described below) but the process really should be similar to what gpx2exif does.

The flickr position tagging is not reproduced here : only files so the code related to it in gpx2exif must be ignored.

create a submodule called gpx2exif (evewn though it will not deal with the EXIF).
The doc below will mention some CLI option or parameter. It is just to specify the behaviour : there should be no CLI option in piqopiqo : there will be parameters to the functions that do the work


Data setup :

- read the  /Users/guilhem/Documents/projects/github/gpx2exif/scripts/batch.sh script. It applies the processing described above to multiple folders: the folders have a different time shift (determined usually by taking a photo of the time of the GPX recorder and reading both the EXzIF tag and OCR'ing the time of the clock of the recorded)
- So you will need for  each folder : a time shift (in the format specified in gpx2exif)
- that time shift will be persisted in the Metadata DB for the folder (where metadata for all the photos in the folder is written). It is for the whole folder, so a new table will need to be created : with 2 columns : Data, Value. In this case the data will be TIME_SHIFT and the value the actual time shift
- in the example below : there are 2 folders 
d_tz95="-1h16m5s"
d_rx100="16:18:56-17:15:03"
d_xs20="-59m9s"

- There will be a User Setting src/piqopiqo/settings_state.py that will take the time zone (just a text string ; default empty) and an Ignore Offset checkbox (default unchecked) and a KML folder path (initially empty)

- for the time_extractor : there needs to be a User setting GCP project (just a string : it can be empty) + path to SA JSON key (the path can be empty : it will take the current gcloud credentials of the machine)

GUI :

- The Settingg panel src/piqopiqo/settings_panel src/piqopiqo/settings_panel/schema.py : will add a Timezone field in the External/Workflow tab
- There will be a separate section in the Tools menu of the app. It will have an entry with label : GPS Time shift...  This will open a dialog with as many entries as they are folders in the current session (see the source_folders src/piqopiqo/main_window.py). The name of each folder (just the part relative to the loaded folder) + a field to enter a timeshift in the same format as gpx2exif. h + m + s in tha order. possibly with a - before. There will be a Save and Cancel (no confirmation dialog). The formats will need to be valid (otherwise vlaidation failed red border aorund the field + Save not enabled). Empty is fine (it will mean : no time shift). 

- In the grid, the right click  menu will have an additional item : Extract GPS Time shift. On the menu click : there needs to be a dialog : that reminds :which folder (the folder where the image is located), if there is already a value set for the time shift for that folder (show the value) + warning that it will be erased if there is. Then OK / Cancel. On OK, this will call in the background the gcloud vision api using the Python lib like the code in time_extractor.py. See src/piqopiqo/copy_sd.py for the background. Do not block the GUI thread while doing the call. With a progress bar (with undetermined total: it just shows while the call is made). Then on return it either shows the error message. Or shows the computed time shift. Then only OK. If hte time shift has been successfully completed : set it as the timeshift for the folder in the SQLlite db.

- In the tools Menu : in the section mentioned before : you will have an Apply GPX... menu. This will open a dialog with 3 sections
- a section that reminds of the values for the time shifts for each of the folders (separately). If no value : will be NOT SET (define a constant for the label) + in red. (if 0 : will be showed as 0 with no color). When NOT SET : will be like 0 in the run later.
- a section that will show the path to a GPX : initally empty. There will be a browse button to allow the selection of a gpx file.
- some settings below : a combobox that shows 2 choices : Only generate KML (this is the equivalent of the  --no-update-images option in the CLI : this is the default) and "Update images" (without --no-update-images but with --clear  --update-time ). Boith options will generate a KML (equivalent of options --kml --kml_thumbnail_size 350) and the KML will be output in the chosen User setting KML folder using a similar convention for the name (based on the name of the  loaded folder + subfolders)
- If the KML folder path setting is empty in the settings. Show a warning below : the KML will be written in the photo folder and use the base photo folder (the root folder open in piqopiqo ; not each fodler / subfolder with images)
- OK / Cancel.
- When OK : launched in th e background. A new modal dialog opens with a progress bar (size determined by the number of photos in the folders summed up). Show a string in the dialog to know which folder is being processed. Do each folder in turn one after the other. That new dialog has a Cancel, which closes the dialog.
- When finished, display the number of photos processed + the paths to the KML with an show in Finder button and OK is enabled. 

- Note that the process  has changed the time taken  : the grid should be reordered (model and view) if needed (if the sort is time taken) + the currently selected items will need to refresh their data from the Metadata DB (date, + latitude / longitude)

- All the current folders are processed and all the photos in those folders are processed. The selected items or the filtered items are completely irrelevant.


```sh
== 
top_photo_folder="/Volumes/CrucialX8/photos"
folder="20251108_arve"
gpx="/Users/guilhem/Library/CloudStorage/GoogleDrive-guilhem.vellut@gmail.com/My Drive/___gpx/20251108-083447.gpx"

d_tz95="-1h16m5s"
d_xs20="-59m9s"

# not in piqopiqo
f_tz95=1
f_xs20=1

folder_tz95=1
folder_xs20=1

tz="Europe/Paris"

update=1

cmd="uv run python"
params="-m gpx2exif.main image --tz $tz --clear --ignore-offset --update-time --kml_thumbnail_size 350 \"$gpx\""
if [[ $update -eq 0 ]];
then
    params+=" --no-update-images"
fi

base_folder="$top_photo_folder/$folder"

if [ $f_tz95 -eq 1 ]
then
    if [ $folder_tz95 -ne 0 ]
    then
        p_folder="$base_folder/tz95"
    else
        p_folder="$base_folder"
    fi
    params_tz95="$params $p_folder -d $d_tz95 --kml ../temp/photos_${folder}_tz95.kml"
    echo "$cmd $params_tz95"

    eval "$cmd $params_tz95"

    echo -e "\n===============\n"
fi


if [ $f_rx100 -eq 1 ]
then
  ....

  ```