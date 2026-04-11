When using the archive tool and saving the EXIF :

- fix the progress dialog : when exif is performed, the dialog is not resize an button. That can cancel the Saving + moving.d there is a lot of white space. Adjust the size of dialog.
- Also, on that dialog : add the number of photos and the # of the current photo being processed. See the Flickr upload dialog (count / total above the progress bar on the right, on the same line as the text of the action being performed)
- Suspend the watchfiles while saving the exif. The files are going to be archived so there is no point in running the watchfiles watcher
- When saving the EXIF : while it is being performed, instead of an inactive OK button, make it an active Cancel