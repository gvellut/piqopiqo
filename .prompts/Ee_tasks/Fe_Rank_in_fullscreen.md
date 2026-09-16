Full screen :

In the bottom left panel (with filename, label, date) : add dynamic rank in first place above the label : eg #2 in larger font.

Rank starts at 1

Rank : is the rank of the photo in the current fullscreen loop : 
- either one item is selected when going fullscreen : the visible photos in the grid are in the loop => rank in the grid of visible items
- if multiple selected when going fullscreen : rank in the list of photos in the list of selected / loop in fullscreen.
So rank displayed can vary depending on context (either filters, or selected items when going fullscreen) and must be determined when going fullscreen

New rank must be recomputed if photo removed eg ejected from the loop with \ (EJECT_FROM_LOOP) : so if #3 is removed : the next displayed will have #3, not #4 (and with a gap for #3).