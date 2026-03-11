Check this prompt : .prompts/Db_tasks/Jb_Fix_visible_filtering_when_exiting_fullscreen.md

I still see photos moving when exiting fullscreen. It could be understandable if exiting right away after setting the label. But it is quite some time after. There should be no moving. 
After testing more : It seems it is the current selected photo : when I exit fullscreen, the selected effect (blue background for the item) is at its old position then is moved to its new position (its new position after the filtered out photos are removed seems to be processed on exit). It should be processed at the same time. So the selected item does not look like it is moving.

Again still note : Beware that with Filter in fullscreen set to false : the label for a photo can be changed so the photo is filtered out. However, the image is still in the fullscreen loop with that setting. So the user can go back to that image while in fullscreen and change the label again to something that is filtered in. 