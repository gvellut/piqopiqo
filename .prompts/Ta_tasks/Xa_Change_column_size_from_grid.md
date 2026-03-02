Set number of columns of grid directl;y from the grid :
Is a  User setting UserSettingKey.NUM_COLUMNS    currently present : in Setting panel : Interface  Grid. Remove it from there : only in the status bar
Add to the status bar : add a component :   - +  buttons to increment decrement number of columns + label (non editable) between that indicates the number chosen. Place that column number widget at the center of the status bar (and stays at center there if resized window)
Limit from 3 to 10 (add 2 runtime settings for min max limits)

Check issue with change column number (tested with the setting in Settings Panel) : 
![alt text](Screenshot 2026-03-02 at 14.08.04.png) ![alt text](Screenshot 2026-03-02 at 14.08.09.png) ![alt text](Screenshot 2026-03-02 at 14.11.10.png) ![alt text](Screenshot 2026-03-02 at 14.11.18.png)
Setting the value then going back to grid changes the layout of the images one way (ie number of columns seems ok ; but maybe not the number of rows) but moving the _right_splitter Qsplitter (vertical spliiter) with the right sidebar and changing the size of the grid widget completely changes the layout ie the number of rows changes. Getting back to the original spliter position (the position that was there when going back to the grid) from Settings does not change it back : so issue => should be coherent

Also add in status bar 
Add the number of selected items (next to the number of items) : 10 photos / x selected. Make it synced with the selection no matter the path (how the selection arrived to its state)
padding on the left and right of status bar : left : number of items ; right : the progress bar for loading a folder. Add a runtime setting for the padding value.
