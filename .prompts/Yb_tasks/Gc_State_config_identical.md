
src/piqopiqo/ssf/settings_state.py
Remove StateDef : use SettingDef for both states and Setting ; Add the explicit group to SettingDef and use it in _user_setting_full_key
Also allow states to be defined using envvar (only AppState , no the Qt states)

>>>>>

Identique state ou config : config def sous classe de state def : ne pas séparer les 2 même API ; séparés dans le code mais même chose derrière

Merge the SEttingsGroup with StateGroup : keep name SettingsGroup (logical folder for saving in Settings)

changer le nombre de colonnes en State

currently state and settings src/piqopiqo/ssf/settings_state.py are separate (diff classes + supporting classes + code) but are logically the same thing : settings has to be updated in the Settings panel (+set with envvars) and State is just in the use of the app but save in the QSettings behind (different folder) + should be retrieved and updated the same. Can you verify if the 2 can be merged ?
- UserSettings def subclass State def : same API; => but rename UserSettings to ConfigSettings ; and State as Settings ; use Settings
- merge the key enum together : just subclasses : 
- No need for envvar loading for states (so no serializer / deserializer)
- Merge the SettingsGroup with StateGroup : keep name SettingsGroup (logical folder for saving in Settings)
- Keep a SettingsRegistry with both : add each (state or settings) at 2 places (not the same call for adding to the registry)
