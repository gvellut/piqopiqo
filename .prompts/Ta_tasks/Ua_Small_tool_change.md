
Copy SD : 
- Verify what happens after OK and before copy starts : seems to have something but not visible. Make it part of the file copy (display the label for the copy stage and do that work) : no specific label (too quick to see)
x
- change wording for since:last : if  no new photo : message is weird : says that no photo and message about sd card inserted and mounted
make no mention of SD Card inserted (it was checked before)
Specific message for since:last (if no photo found : is probably because no actual photos on disk sin the last date, possibly return context from the check if needed to get certain)

- When checking the dates (first step) with since:last : display progress bar, with no total

- In the copy stage : make sure the nubmer of files to copy + done is shown along with the progress bar.


gpx2exif

when applying GPX : dialog too big at first : Apply GPX too much space for a second => should adjust size OR show the progress bar (empty) from the start
When indicating folder : starts with - before real folder : Display nothing until first folder

add a clear GPX menu : in the tools Menu in same section as the Apply GPX. Add confirmation. Then remove the GPX lat lon from the metadata db. Keep the metadata edit view synced after the clear (panel must not show GPS).


flickr upload 

- check status (after upload proper) : indicate num of check so there is progress + progress bar transformed to no total for this : so shows something is going on. Until the next step (reset dates) Otherwise looks blocked on the upload.


- when OK Verify what happens after OK and before upload proper starts : seems to have something but not visible (too fast). It makes it look like a glitch
fix with same as Copy SD : Show the step as Upload but do that work in there

- when progress upload :  self.progress_bar.setFormat("0/%v")
But nothing is displayed except the step above the progress bar : 
the x/total would be a good indicator for progress
