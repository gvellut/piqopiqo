Something weird : fullscreen : changing labels with shortcut : sometimes gets stuck. Seems to be related to filters : If changing label from 
For example : 
1st selecting 2 images ; Going fullscreen with space. I can change the first photos between 2 labels : the one in the filter, and one outside the filter. That first photo does not get stuck. Move to the second : Changing to the label NOT in the filter. Then trying to change back : not possible. It seems stuck (color stays the same) as the label not in filter. If I move back to the first image then go back to that image : the label has changed to the label in the filter (which I tried to set previously).
2nd example : 1 selecting 2 images ; Going fullscreen with space. I can change the first photos between 2 labels : the one in the filter, and one outside the filter. That first photo does not get stuck. Move to the second : Changing to the label NOT in the filter. Then trying to change back : not possible. It seems stuck (color stays the same) as the label not in filter. If I exit at that point : the image will have disappeared from the grid. BUT If change the filter for example by filtering in the label on which it was stuck. Then the image becomes vibible : but it has the first label (the one that was filtered in previously before the change of filter ; the one I tried to set back in fuillscreen).

That stuck label change seems to happen for the LAST photo only. But not if I select only one photo (no issue there it seems). If I select more than 2 photos : The 2nd one does not have the issue, only hte last one.

Try to see in the code, where the issue could be and fix.

May be related to (882d3a65876998b1d9bd055b14becd4e47b641d4 or ffadfc651dae3bcccdceeb8495cbad4d65fe8f02 ; change + fix) or fdf3bd3706af74bfc9d5eb3e792c6cf310cf66bf (latest change ; probalby not related but you can check)
