
Storing state in a more formal way

settings => option set by user to influence the program; settings screen : currently ignore for now : will be done later (starting with the Config values in src/piqopiqo/config.py)
state => choices made by the user in the course of using the software (eg. names, checkboxes, path, folder). They can be recorder and recalled later in the same context

Use Pyside6 QSettings for persistence and extraction
Use Native Format
Always use the type= argument in .value() to ensure your booleans stay booleans and your integers stay integers across app restarts.
For complex types (Dicts/Custom Objects maybe list ?): Use the JSON approach (parsed from strings / serialized to string), as QSettings doesn't handle nested Python dictionaries natively across all platforms.
Create local instances of QSettings (or the abstraction on top) to use
Try to set the values where they are changed by the user. 

Use a group "AppState" for the values for the state (another group later will use something else for the config)
Use lowerCamelCase for the individual keys (e.g., theme, fontSize) and UpperCamelCase for your groups (e.g., UI/, Network/).
Setup StrEnum for the different state names + for groups (different enum)

Setup a Global Info class for the value and use it before creaating the QSettings (so standard place)

QCoreApplication.setOrganizationName("MySoft")
QCoreApplication.setOrganizationDomain("mysoft.com")
QCoreApplication.setApplicationName("Star Runner") => already set in config.py : move it (not actually a config); update the references in other place since it is used for the about or some other places.


add --dyn (dynamic) option => to ignore saved state + do not write : for dev or testing. All in memory.
Make sure the abstraction on top of settings allows reading / writing in memory with dyn (no saving)

The abstraction needs to be able to set default values for the states + data types (or inferred from the default value). Data types can be the baic  Python types : str, int, float, dict, list, tuple or the Qt types. But also paths for example
Set to the QSettings when actually changed by the user while using the app (no copying beforehand)
If the default value is None (for ex : last folder or last name suffix): must not crash but be handled safely eg as equivalent to "".
Can be 2 different implements (dyn + standard) if simpler but the default values must be defined only once.
The same setup will be used for config (currently set in Python, with other things mixed in). So a single class for config + state (will both use QSettings) would be better. They will be different groups in the qsettings

Options to support in state :

- folder to use for the grid (last opend folder) : Already the former folder (state) in specific JSON stored there : remove reading and writing from it. Do not maintain compatibility (just completely ignore it after this change). The folder will be written in the settings
- data for Copy from SD : checkbox Eject (set or not), name suffix, Date spec 

Change the code to use the state where needed, and set it where needed

Also add state reading and writing for Qt widget / layout :

 # saveGeometry() returns a QByteArray with all position info
        settings.setValue("windowGeometry", self.saveGeometry())
        
        # saveState() returns a QByteArray with all layout info
        settings.setValue("windowState", self.saveState())

and restore it too when opening the app

+ take care of the splitters :
Right side: vertical splitter with edit panel and EXIF panel
Main horizontal splitter: grid | right panel(s)

save them when closing the application :
def closeEvent(self, event):

Put the Qt states in the same group as the custom app states. But put them in a subgroup name "Qt"