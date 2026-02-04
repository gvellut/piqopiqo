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
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


# Maps DB field -> list of EXIF fields to try (in order of preference)
EXIF_TO_DB_MAPPING = {
    DBFields.TITLE: ["XMP:Title", "IPTC:ObjectName"],
    DBFields.DESCRIPTION: [
        "XMP:Description",
        "IPTC:Caption-Abstract",
        "EXIF:UserComment",
    ],
    DBFields.LATITUDE: ["EXIF:GPSLatitude"],
    DBFields.LONGITUDE: ["EXIF:GPSLongitude"],
    DBFields.KEYWORDS: ["IPTC:Keywords", "XMP:Subject"],
    DBFields.TIME_TAKEN: ["EXIF:DateTimeOriginal"],
    DBFields.LABEL: ["XMP:Label"],
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
