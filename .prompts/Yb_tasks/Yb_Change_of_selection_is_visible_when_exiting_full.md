When exiting fullscreen : when looping around all the images : 
a single item was selected in the grid when going fullscreen and a single item must be selected when exiting (the one last visible). However : when exiting the last item is not selected right away. Instead the original selected item (before the fullscreen) is seen as selected in the grid. Then very quickly, it is changed to the last item in fullscreen before exit. This change is incorrect.

Instead when exiting fullscreen, if looping around all the photos : the last selected image must be selected with no change visible from the POV user when exiting the fullscreen

See those commits 

d28c9528e58b6455340e938c4859625659879885
a9f7c0148db551e6ae1c9e20003568f18331cbd8

They possibly introduced the issue.

Also beware : the last image visible in fullscreen might be filtered out in the grid when exiting fullscreen (if its label was changed). There still must not be any visible change to the item actually selected when exiting fullscreen.