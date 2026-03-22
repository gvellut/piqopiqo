When exiting fullscreen : when looping around all the images : 
a single item is selected when exiting. However : when exiting the last item is not selected right away. Instead the original selected item (before the fullscreen) is selected. Then very quickly, it is changed to the last item in fullscreen before exit. THis change is incorrect.

See those commits 

d28c9528e58b6455340e938c4859625659879885
a9f7c0148db551e6ae1c9e20003568f18331cbd8

They possibly introduced the issue.

Instead when exiting fullscreen, if looping around all the photos : the last selected image must be selected with no change visible from the POV user,s