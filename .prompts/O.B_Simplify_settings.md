Simplify the settings panel processing. It is too specific. What if I change the layout and it is not a spin but something else ?

Instead remove all the layout order specific handlers: just make sure 
- Enter on a text field does not cause the Save to fire
- The Save button can be blue or not or simply disabled (to indicate invalid) 
- The elements are not blue if never interacted with like the checkbox
- if tab change : no element is focused.

When going into the Labels + Shortcuts tab : if I have focused on a text field (eg the Cache Base Directory textfield) the Filter in fullscreen checkbox is blue

Use the pyqtauto skill to check yourself.