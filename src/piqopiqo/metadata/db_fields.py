"""Constants for database fields, EXIF mappings, and display labels."""


class DBFields:
    """Database field names (column names in SQLite)."""

    FILE_PATH = "file_path"
    FILE_NAME = "file_name"
    TITLE = "title"
    DESCRIPTION = "description"
    LATITUDE = "latitude"
    LONGITUDE = "longitude"
    KEYWORDS = "keywords"
    TIME_TAKEN = "time_taken"
    LABEL = "label"
    ORIENTATION = "orientation"
    MANUAL_LENS_MAKE = "manual_lens_make"
    MANUAL_LENS_MODEL = "manual_lens_model"
    MANUAL_FOCAL_LENGTH = "manual_focal_length"
    MANUAL_FOCAL_LENGTH_35MM = "manual_focal_length_35mm"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"

    MANUAL_LENS_FIELDS = (
        MANUAL_LENS_MAKE,
        MANUAL_LENS_MODEL,
        MANUAL_FOCAL_LENGTH,
        MANUAL_FOCAL_LENGTH_35MM,
    )


# Maps DB field -> list of EXIF fields to try (in order of preference)
# Uses MWG (Metadata Working Group) composite tags where available
# See: https://exiftool.org/TagNames/MWG.html
EXIF_TO_DB_MAPPING = {
    DBFields.TITLE: ["XMP:Title", "IPTC:ObjectName"],
    DBFields.DESCRIPTION: ["Composite:Description"],  # MWG reads from EXIF/IPTC/XMP
    DBFields.LATITUDE: ["EXIF:GPSLatitude"],
    DBFields.LONGITUDE: ["EXIF:GPSLongitude"],
    DBFields.KEYWORDS: ["Composite:Keywords"],  # MWG reads from IPTC/XMP
    DBFields.TIME_TAKEN: ["EXIF:DateTimeOriginal"],
    DBFields.LABEL: ["XMP:Label"],
    DBFields.ORIENTATION: ["EXIF:Orientation"],
}
# Lens info fields are set in code: since some transformation is performed

# Maps DB field -> EXIF tag(s) for writing
# Uses MWG composite tags where available to write to multiple locations
# String value = single tag, list = write to multiple tags
DB_TO_EXIF_WRITE_MAPPING = {
    DBFields.TITLE: ["XMP:Title", "IPTC:ObjectName"],  # No MWG, write to both
    DBFields.DESCRIPTION: "MWG:Description",  # MWG writes to EXIF/IPTC/XMP
    DBFields.KEYWORDS: "MWG:Keywords",  # MWG writes to IPTC + XMP
    DBFields.LATITUDE: "EXIF:GPSLatitude",
    DBFields.LONGITUDE: "EXIF:GPSLongitude",
    DBFields.TIME_TAKEN: "EXIF:DateTimeOriginal",
    DBFields.LABEL: "XMP:Label",
    DBFields.ORIENTATION: "MWG:Orientation",
}

# GPS reference fields (special handling for lat/lon conversion)
GPS_REF_FIELDS = {
    DBFields.LATITUDE: "EXIF:GPSLatitudeRef",
    DBFields.LONGITUDE: "EXIF:GPSLongitudeRef",
}

# Maps DB field -> display label for the edit panel (without colon)
FIELD_DISPLAY_LABELS = {
    DBFields.TITLE: "Title",
    DBFields.DESCRIPTION: "Description",
    DBFields.LATITUDE: "Latitude",
    DBFields.LONGITUDE: "Longitude",
    DBFields.KEYWORDS: "Keywords",
    DBFields.TIME_TAKEN: "Time taken",
    DBFields.LABEL: "Label",
}

# Ordered list of editable fields (determines panel order)
EDITABLE_FIELDS = [
    DBFields.TITLE,
    DBFields.DESCRIPTION,
    DBFields.LATITUDE,
    DBFields.LONGITUDE,
    DBFields.KEYWORDS,
    DBFields.TIME_TAKEN,
    DBFields.LABEL,
]
