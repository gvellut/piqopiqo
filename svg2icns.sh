#!/bin/zsh

APP_BUILD=.appBuild

function svg_to_icns(){
    local RESOLUTIONS=(
        16,16x16
        32,16x16@2x
        32,32x32
        64,32x32@2x
        128,128x128
        256,128x128@2x
        256,256x256
        512,256x256@2x
        512,512x512
        1024,512x512@2x
    )

    for SVG in $@; do
      BASE=$(basename "$SVG" | sed 's/\.[^\.]*$//')
        ICONSET="$BASE.iconset"
        ICONSET_DIR="./$APP_BUILD/icons/$ICONSET"
        mkdir -p "$ICONSET_DIR"
        for RES in ${RESOLUTIONS[@]}; do
            SIZE=$(echo $RES | cut -d, -f1)
            LABEL=$(echo $RES | cut -d, -f2)
            svg2png -w $SIZE -h $SIZE "$SVG" "$ICONSET_DIR"/icon_$LABEL.png
        done

        iconutil -c icns "$ICONSET_DIR"
    done
}

if [[ ${BASH_SOURCE[0]:-${(%):-%N}} == $0 ]]; then
    if [[ $# -eq 0 ]]; then
        echo "Usage: $0 file1.svg [file2.svg ...]"
        exit 1
    fi
    svg_to_icns "$@"
fi
