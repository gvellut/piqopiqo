- When using the filter : for example clear filter, or filter on a label and maybe (but not sure) setting the folder : I see some delay after I click and the item on which I click changing. Make sure the feedback to the click is instatenous and that whatever action is being performed either happens in the background or at least after the feedback.

- Rearrange the User Setting tab : Grid / Display : 
    - rename it Interface
    - In the Grid group : leave only number of Columns
    - Put fullscreen Exit Behavior in own group : Fullscreen
    - Put Custom eXIF Fields in own section : EXIF Panel
    - Add a group (before EXIF Panel) : Metadata Panel
        - Add a check box : Show description field
            - process that option : if set to true (default): the description field is shown (like now). If set to false : hide it (in that case the description field in the metadata db is still there ; however since it cannot be edited, it will remain empty ; or to whatever the value was when importing the description from the images when the DB was filled). Nothing changes when saving the EXIF or uploading to Flickr (the description will be left out if never filled)