- in the settings panel in the Status Labels definition : The colors must not be a text field with Hex : it must be a color chooser.
- The shortcut selection for the labels allows the user to choose the same index multiple times. The boxes should have a validation failed indicators if the same has been entered multiple times (manually by editing the fied). The arrows increment and decrement should bypass the values that already exist. A new added label should not start at 1 but at the next available index. Also the number of status should be limited to 9 (number of possible shortcuts => there is no way other than the shortcuts to set them).
- The save button should not allow saving if therea are identical shortcuts (validation failed). 
- So define a validation for custom editors and rely on that


src/piqopiqo/settings_panel




- Do not  display the Hex value on the color. Make it a clickable square. Make it visibly a button.
- the validation should also fail if : the text of the status label is empty.
- Instead of Remove : make it a cross button (image / icon)
- Instead of the index field with increment / decrement (remnove this) : make the "Status label" text + color + x (remove) button drag and drop able + index (non editable) shown at the beginning of the line. The indices are the position (so up to the number of labels 1 to ...). Removing an item wth x moves up the next labels down in index. A drop move the other as well.
- Remove the validation for the index (implicitly set : will always be valid)
- Remove the "Status Labels" label (there is already a Status labels title for the box)

src/piqopiqo/settings_panel/status_labels_editor.py



Can you make the dragging better : the item being dragged needs to disappear from the list. or make it very transparent.
Also add an icon at the beginning of the line that indicates that the line is draggable and that also serves as the entry point (mouse press) for the drag (not the rest of the line)
If possible, also add  an indicator like a line that will shows where the drop will be (between 2 status label lines)


There is no indicator line for dropping at the top (not displayed)
Also instead of making it disappear : make the original line very transparent but all the lines stay at their position while dragging


The original status label row is not made transparent while dragging : it stays the same. Correct
Also the indicator line above the first row has smaller width than the others. Correct

The row is made transparrent OK. But the row is not being dragged. Only the indicator line is shown. Both must appear.
