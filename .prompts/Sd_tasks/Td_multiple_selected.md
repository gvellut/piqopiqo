Cmd+A in the grid + current photos has its Keywords field filled multiline => the metadata panel gets shorter (the keyword panel gets emptied) + the EXIF panel gets shorter : N photos selected (updating...)`  appears TWICE between them taking space.
The text appears without photos even being updated.
When the process finds out all the keywords are the same : the keywords expand again : so very ugly : quick succession of : normal keyword text field size (filled multilines), then after Cmd+A : the keyword text field is emptied and gets smaller + the labels Updating appears and the panels resize, then quickly, it exapnds again, the labels disappear and the panels resize again.

If pressing cmd + A multiple times, with no action in between : the same resizing occurs.


In agents.md :
- Large grid selections (for example `Cmd+A`) use a responsive-first panel update path in `MainWindow`: visible grid selection highlights refresh immediately without a full grid render, while Metadata/EXIF panel aggregation is deferred/coalesced with a short single-shot timer and panels show a temporary `N photos selected (updating...)` summary.

=> not correct : Change :


When cmd+a is pressed OR the selection of multiple items happen (with Shift or Cmd): do not empty the keyword field. Keep the keyword field like it was until it can be decided which one it is : the keywords are all the same and the keywords field keeps the same size (ie all the selected photos have the same keywords : only decided at the end), or the keywords are not the same and the field is a siongle line with <Multiple values> (decided as soon as there is a photo with a different keyword field) then in the latter case, the size changes ONCE until the end of the Cmd A / multi selection process. IOn the former case, the size of the keywords field never changes.

When doing Cmd A multiple times : the size does not change multiple times (this is just a consequecne of the above , not something special done).

The label `N photos selected (updating...)` is not shown in either EXIF or metadata panels and the panels do not resize because of them. Instead, you can update the status bar : there is already something done (progress bar) for when the photos are loaded in a new folder on the right side. Use the progress bar for indicating the update : No text, only the progress bar, without total count for the selection processing (it is too fast otherwise with a count : impossible to view actual progress). Like for when loading the folder, the progress bar disappears when it is done. If loading and selection : the loading takes precedence.