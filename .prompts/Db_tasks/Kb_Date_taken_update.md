Previously opened folder:
When opening a previously opened folder : so metadata DB has been filled : if sorting is Date taken (set because it was the last sorting order) : the sorting seems to change quickly. First seems to be consistent with alphabetical order from what I see (although could be the scan order ie raw photos), then switched to the Date taken.
On open : should not have  2 steps ie show the raw ordering THEN switch to the saved sorting order. Instead determine the sorting order (if set as state + should be quick) : sort : then display according to the sorting order.

New folder:
when reading a **new** folder with a large number of photos and state of the app has sort order as Time taken: blink of the preview images. Seems to be replaced by another item : disappears then shows something else. The preview thumbnail (or more exactly the ref to the real image underneath) seems to change. the labels below the image (file name + date) seem to change as well.
=> Makes sense because the date taken is updated (read from the EXIF) and the sort order is based on it
=> 
=> If new : and date taken sort (if sort by filename or file name by folder; should be fine from the start since obtained from the start ie do the sort before displaying anything) display by scanned order then sort only when exiftool of all the files have been extracted after a load folder : so done at once. If selected keep in visible in new order
	Handle some errors for some file : must still sort after
=> or do this instead : sort either at the end or after processing x photos Runtime Settings (or when no more photos to process so not left hanging)  : if 0 : process only at the end
=> if new images added or deleted : resort when event received
