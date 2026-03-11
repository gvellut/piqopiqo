The model/filter refresh timing was already fixed. The remaining issue is different:
when a fullscreen label change affects filtering, the hidden grid selection highlight
can still be driven by the old fullscreen index. On exit, the blue selected item can
briefly appear at its old slot and then jump to its final slot after the filtered grid
state is applied.

The fix is not to delay filtering until exit. The fix is to keep the hidden grid
selection synchronized by path while fullscreen is open, so exiting fullscreen reveals
the already-final grid state.

This must also preserve the existing `Filter in fullscreen = false` behavior:
an image can be filtered out of the grid while still remaining in the fullscreen loop,
then later be labeled back into the filter before exit. In both directions, exiting
fullscreen should not reveal a visible selection jump or cell movement beyond the case
where the user exits immediately before the background grid update had time to finish.
