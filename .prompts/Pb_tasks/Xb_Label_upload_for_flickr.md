Add a label to take into account for flickr upload  : 
- in User Settings and Tools >Flickr section : Text field ; filled with value or not (default is empty)
- if setting filled : default on Flickr Upload tool is to upload all the photos with that label (no matter what is visible through the filters when the Flickr Upload command is started). Essentially : it replaces the normal filter with a custom filter for label just for the Flickr Upload process
- Only if setting has a non text empty value : 
    - Display an additional checkbox in the flickr upload dialog : Upload all the <label> images (default checked since the label is filled)
        - if checked : upload the images with label, otherwise upload the photos that are filtered (visible) in the grid like now
        - If checked (default) Set the label with the number of photos in the dialog, to the number of  photos with the label. If unchecked, set to the number of filtered photos in the grid
        - if checkbox not there : do not make the dialog bigger ! Adjust the size always
    - on dialog open : Check if there are photos with the label. Sitll display the normal dialog  : but the checkbox is not checked and inactive. A Red text below indicated. No image with label


For the Keyword / title precheck if enabled by the user : change
Currently : does it in precheck before the standard dialog
Now : if enabled :and there are missing medatada
- Add a red message below the number of photos if some of the photos (list photos depend on either the label or visible photo chekbox) do not have the reuirements
    - Hide the label (and space ie adjust) if the other checkbox does not have that
- disable the button to upload if there are metadata missing with the chosen label / visible checkbox
- Also disable the text field with the Album name (so cannot be changed by the user)
- Only active element is the checkbox label / visible
    - but if change and there are no missing metadata : everything becomes active