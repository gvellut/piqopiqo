Transition after flickr upload : 

For ex : Images with Label Approved transitioned to Label Uploaded , Label Rejected to Rejected*, Label Review to Rejected* : configurable one label to other label

Add a  line control in the Settings Panel > External/Tools tab > Flickr section : similar to the Interface tab > Map links : ie title with one line Label and button (that opens dialog) : "Transitions"
The label will have x rules (or No rule). Make it rule or rules (depending if 1 or more), not rule(s).
Button is Edit...
Popup : will have list of rules like the Map links with action buttons : The list will be "<label 1> to <label 2>". If too big for the width of the list use ellipsis.
Adding / editing a new rule will open a dialog with 2 listboxes one on top of the other like the Add Map Links with titles "From" and "To": list of labels defined in the application in both + small color swatch on the right side with the color defined in the setting. Also include No Label (leave empty swatch)
Validation must be : they must be filled and they are not the same in both. Also a label must only appear once in the From side in the list of rules so no ambiguity (so that validation must take into account the other existing rules)
Buttons Cancel OK. If not valid  cannot do OK. 

Possibly if similar enough abstract the Map Link dialog and reuse in both

usage : add at the end of a Flickr Upload tool session :
Checkbox below the summary Text field / paragraph at the end of a Flickr Upload session (state in settings_state so can be left unchecked or not in a row ; similar to the Copy SD Eject checkbox) : text  "Apply transitions"
If checked : Apply the transitions : they must apply all at the same time : that is if a rule is Label 1 to Label 2 and another rule is Label 2 to Label 3 : the images with Label 1 must not be transitioned to Label 3, just to Label 2. So find the images first for each rule then apply, not serially. Set the screen of the dialog to : label Applying x rules... + progress bar with no total / Cancel button ; when done : end screen dialog : total number of images whose state was changed (no need to detail for each rule ; but keep that data so can change my mind later) OK button focused
When exiting if transitions were applied : make sure to refresh the grid so filters are applied for the new labels of the images.



test if label renamed in settings. How do the rules behave?