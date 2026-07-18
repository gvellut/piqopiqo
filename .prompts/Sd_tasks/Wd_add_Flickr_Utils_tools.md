Implement tools for piqopiqo : 
- /Users/guilhem/dev/projects/github/flickr_api_utils/flickr_api_utils/album.py : reorder : reorder albums on Flickr
- /Users/guilhem/dev/projects/github/flickr_api_utils/flickr_api_utils/photo.py : "find-replace" : edit / replace titles (or parts) or tags in Flickr
- /Users/guilhem/dev/projects/github/flickr_api_utils/flickr_api_utils/local.py : "find-replace-local". For that one, I do not want a direct port (ie that modifies EXIF tags). I want one that does the same as find-replace (the "find-replace-local" might have some deviations from the find-replace) but on the data storeed in the PiqoPiqo metadata database (SQLite) => do not edit or read EXIF


I want the tools to have a link in the menu : 
- the first 2 (Flickr related) : in a new Menu Flickr right of Tools. Move the Flickr upload tool to that. Keep that one as the first. Separate it from the other 2 with a bar
- The first 1 : Find replace local (call it Find & Replace) : below the existing Edit menu.

Have a suitable dialog flow : for inputs, progress showing, result summary. With OK Cancel button or other names. You can use as inputs similar to the ones the cli tools have (no need to do anything fancy). You can make things clearer as to what are replaced / take into account (for ex : find replace has something with find title => then only for those. replace the tags : Make the flow and intention clearer as to what are the conditions for the replacings and what happens)

For reorder : add the choice to Save existing order (done in case of a bug ; I have another tool to reset) as an application state (by default, saved) : if saved, save to the Support folder (same as the rest of the configs). Use a Runtime setting to know how many to keep around => by default, will be 3. Auto naming : Add the date in the name of the saved files. If more that the numbers to keep around, erase the older one.

For flickr tools, you will need Flickr login (follow what the Flicr Upload tool already does). 

Make sure to autosize the dialogs (no unnecessary empty space).

Put the code in the piqopiqo.tools module : one submodule (folder) for flickr tools  + one submodule (folder) for the edit tools (there will be other tools at some point but only find-replace for now)

If there are parts that can be reused (eg Flickr integration), have a module flickr_utils under tools. You can refactor flickr_upload to use those parts. Make sure the functionality does not have adverse effects.