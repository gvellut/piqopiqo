Flickr api utils : /Users/guilhem/Documents/projects/github/flickr_api_utils file flickr_api_utils/upload.py

Upload photos to Flickr : so the upload.py is the only functionality that matters + auth

- You will need to redo the functionalities in this project. Do not make any code reference to that project : it will not be a dependency. You can look or copy the code and reapply it here.
- create a submodule called flickr_upload

- see .prompts/H_gpx2exif.md and gpx2exif submodule in piqopiqo. Relatively similar constraints  for settings, launch, dialogs. Process has nothing to do with flickr upload though.

- in the Flickr upload : only the filtered photos are uploaded (not all the photos / all the folders).
- Also sort order will change the order of upload to Flickr

- Flickr extracts some data from the exif : So before uploading a photo. You will need to copy it to a temporary file, update the tags based on the Metadata DB (see the src/piqopiqo/panels/save_exif_dialog.py but the whole upload will be done. Do this in the same process (outside the main app) that will do the upload so not another opool of multiprocessing. 

Data :
- 2 User settings : Flickr API key and Flickr API secret. both text, initially empty

GUI :

- In  settings : add a Flickr group in External / Workflow tab.
- 2 fields : Flickr API key and Flickr API secret. You can leave them in plain text (no need for password-like text field)

- separate section in Menu Tools : Upload to Flickr...
- If any of Flickr API key or Flickr API secret are empty : dialog with error. Saying those 2 fields are empty and set them in .... in Settings Panel. OK button
- Otherwise : dialog opens : indicates the number of currently visible photos (that will be uploaded). Will indicate if token file exists (see flickr_api_utils / flickr_api_utils/api_auth.py). The location of the token file will be in the  base cache folder chosen by the user (or default) in subfolder flickr (next to db or thumb folders). The token file should be named (by flickrapi python lib ) oauth-tokens.sqlite. Define a constant for it.
- There is a cancel button. 
- If the token file does not exist : the button next to Cancel is a Login to Flickr.
- if  Login to Flickr. : A dialog opens on top of the first one with a progress bar with no total : then it should do the same auth flow as the flickr_api_utils upload : using the flickrapi python lib (already installed). So use authenticate_via_browser in the background (so does not blocke the GUI) The result should be a token saved in the file mentioned above + cancel. There is a Cancel button : Make sure to clean on cancel (there should be a webserver listening for the callback of the login : make sure it is stopped). Cancel closes all the dialogs.
- Once done : the dialog closes and goes back to the the first dialog above : number of photos + presence of token (this text has been updated because of login + new token) + Cancel + Upload buttons
- If the token file exists : the button next to cancel is Upload
- if Upload : A new dialog opens ( the old closes) : 
- before the upload starts you will do a flickr.token_valid(perms="write") test in the background (QRunnable). Progress bar with no total.  If result not OK ((for example the token has expired) ): then error dialog that explaines token not valid + goes back to first dialog (the Upload dialog shows : it is like a click Upload to Flickr menu from the start ): with text updated : normally token_valid should have deleted the token if not valid and the button should be Login to Flickr
- If no problem : show progress bar with total number of photos. With a text label with top step : Upload, reset date , make public
- Before upload of single photo : make a copy of the photo to a temp location, set the exif (see src/piqopiqo/panels/save_exif_dialog.py) and upload. Set the same fields as the flickr_api_utils on top. Remove the temp file explicitly after uploads

- Do not deal with the Flickr albums for now : only the upload + set date uploaded + make public
- because of bugs in the Flickr API upload, there are a few complications (some photos need to be reuploaded) : follow what is done in the flickr_api_utils. Stop like the flickr_api_utils for some conditions
- Cancel stops the the upload or whatever was currently done (actual upload, public or set date).

- At the end : show if everything was OK, or if some photos could not be uploaded and how many or if some step failed. then OK button.

- define a flickr upload manager that will do the upload work using workers in multiprocessing. See maybe src/piqopiqo/background/media_man.py. But simmilar to what is done in flickr_api_utils already
