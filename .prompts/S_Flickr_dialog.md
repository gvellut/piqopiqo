Change the Flickr upload dialog. 

When launching the upload FlickrUploadProgressDialog in src/piqopiqo/tools/flickr_upload/dialogs.py

Make the height of the dialog as big as it needs to be to contain the content but no more. adjust the size when the content of the dialog changes
The text of the previous step is displayed while the next step is being performed
At the end : the Add to album progress bar (progress bar with no total : OK) is still running even when it is done. When it is done : that progress bar should be removed. Only the summary should be shown 