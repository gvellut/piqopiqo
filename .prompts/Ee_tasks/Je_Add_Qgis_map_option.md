check the QGIS plugin /Users/guilhem/dev/projects/github/qgis_simple_remote_control It runs in QGIS 4 and launches a Qt socket server.
I want to add an option to include Qgis Remote Control in the list of maps. since it is not a HTTP server, make it a special opion : QGIS remote control in the settings below the x options defined of Map Links (use the same tabulation)
- in the settings :
    - Make it a checkbox + a Qt socket name field : by default qgis-remote-control (editable if checkbox checked). 
        - Plus a Edit mappings... button that shows a popup for mapping photo folder (relative to opened folder) to layer in QGIS : 
            - will have multiple entries mapping a string (folder name) to layer index (integer) or string label (name of a QGIS layer)
            - the popup can have a similar shape as the popup with the http templates : list of folder names + another  popup for addition or edition : with 2 fields : the folder name + a mapping field : either a string or an integer
                - you can create a reusable control and switch also the http template definition (that opens on the Edit...). At least the first popup.
    - change the The first line: It will have a wording x options defined :  including hte HTTP + the QGIS option (so no button)
    - put the current line below that one: it will be only for the HTTP templates
        - Change the Edit ... button to Edit HTTP templates... + change the text to x HTTP options
    - put the QGIS remote control related line below : so 3 lines in total.
- when the Qgis option is selected in the Map of hte metadata panel (or the button clicked if the only option is QGIS remote control):
    - open a socket client
    - first select features of the  QGIS layer (mapped from the  folder of the current photo based on the mapping in the setting ; or just the folder name  of the photo relative to the current opened folder is no mapping defined for it). Use as expression field "Name" == <photo base file name>.
    - second : zoomToSelection on the layer
    - put the qgis related code in a separate file so easy to review and change
- also for testing : add to /Users/guilhem/dev/projects/github/qgis_simple_remote_control  client_sample folder : a sub command that does the 2 combined and takes a base file name as param so I can do what your code does in command line.