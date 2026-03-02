Flickr upload : Add user Setting : list of metadata that needs to be filled or upload will be rejected => just a checkbox to have title + keywords filled

When launching Flickr Upload tool :  Check first in background that title + keywords are present on all photo to be uploaded : do not block the GUI : do it before current first dialog (should be fast) without showing a progress bar or dialog.  If rejected show error dialog with message + OK. 
If not rejected : do like now : show upload dialog

On OK after rejection dialog : (clear current selection) and select just the items with missing (either title or keyword) when exiting the dialog
