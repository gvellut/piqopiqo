- "Flickr API key and Flickr API secret are empty.
Set them in Settings > External/Workflow > Flickr."

Add a button : Go to settings : it closes the dialog and opens the Settings Panel at the correct tab.
src/piqopiqo/flickr_upload/dialogs.py function launch_flickr_upload for the dialog

- Add a text field tp FlickrPreflightDialog  for adding the uploaded photos to an album : Add to album then text field wich takes the whole width of the dialog. 
The field is displayed only when ready : when the flickr has logged in : ie the button is Upload 
see how which album to choose : retrieve the album ID either from title or album ID for Flickr URL to album ID. If created : need a title
Flickr api utils : /Users/guilhem/Documents/projects/github/flickr_api_utils file flickr_api_utils/upload.py
If token is invalid : ie validate_token_or_cleanup is false : go back to the FlickrPreflightDialog : keep the string for the album. ( do not clear it). But otherwise same as now.
If text was recognized as album ID or Flickr URL to Album ID : but cannot find on Flickr before starting the Upload in FlickrUploadProgressDialog, show an error dialog then abort : go back to the the FlickrPreflightDialog and show an error message below the Text field (do not clear it). Similar to what is done in flickr_api_utils/upload.py : consider the album check as one of the steps. Then display the title of the album and if it is going to be created or simply added,  to below the progress bar : Creating album ... or Adding to album ... Not done in flickr_api_utils/upload.py : retrieve the album title if only the ID or URL was given and show that (not just the ID)
Then similar to what is done in flickr_api_utils/upload.py, add the photos to the album. Use the _add_to_album_group workflow. Reset the progress bar for this step and make it without total so full and spinning.

- Add a Folder data : FLICKR_ALBUM_ID with the album ID that was determined (either from the title, the album id or the URL) or returned from Flickr after creation. This will be set in the DB all the sub folders with photos of the current loaded folder (even if no photos were uploaded ie they were filtered). If album already exists : this data is set before the actual upload starts (after a click on the Upload button) and after the ID is determined (if text was entered) : it is overwritten at each upload (even if the same) : but only if the album ID is determined to be valid. If the album needs to be created : the folder data is set after the creation(and before the photos are added to it)
- Then, when calling the menu Upload to Flickr ... : when the dialog version with the Upload button (see above) is displayed : check in the DB before showing it that it is set for at least one of the folders. Then take the first value with that data (no need to check if different). Then query the Flickr API to get the title of the Album using flickr.photosets.getInfo that corresponds to the ID in the field for the dialog. Also add a text link (visibly clickable like HTML blue for example). And open the browser and point it to the flickr URL : on top of the album ID, you will also need the NSID of the logged in user. It is avaialble in the response to flickr.photosets.getInfo.  use the user_nsid to craft the URL :  eg https://flickr.com/photos/22539273@N00/albums/72177720331888267  : 22539273@N00 is the NSID and 72177720331888267 is the album ID. 
- You can remember the structure : album ID, URL, title : for display in this dialog and the next (actual upload in FlickrUploadProgressDialog) without having to make a query so 2 cases : either entered by the user and make the query in FlickrUploadProgressDialog or remembered from a previous query and just make use of it.
- 

- For the token validation : Reset the progress bar for this step and make it without total so full and spinning (not total = 1).
