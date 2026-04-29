Can you check 

The vertical space between :

                     FieldSpec(
                        key=UserSettingKey.PROTECT_NON_TEXT_METADATA,
                        label="Protect non-text metadata fields",
                        editor=EditorKind.BOOL,
                    ),
                    FieldSpec(
                        key=UserSettingKey.MAP_LINKS,
                        label="Map links",
                        editor=EditorKind.MAP_LINKS,
                    ),

is larger than the space between :

FieldSpec(
                        key=UserSettingKey.SHOW_DESCRIPTION_FIELD,
                        label="Show description field",
                        editor=EditorKind.BOOL,
                    ),
                    FieldSpec(
                        key=UserSettingKey.SHOW_HIDDEN_METADATA_FIELDS_IF_NOT_EMPTY,
                        label="Show hidden fields if not empty",
                        editor=EditorKind.BOOL,
                    ),
                    FieldSpec(
                        key=UserSettingKey.PROTECT_NON_TEXT_METADATA,
                        label="Protect non-text metadata fields",
                        editor=EditorKind.BOOL,
                    ),

once they are displayed in the settings panel.

Can you check why ? Is that because of the button ?
I would like to have the same space