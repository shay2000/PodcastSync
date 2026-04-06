#!/bin/bash

set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <source-binary> <tools-root>"
    exit 1
fi

SOURCE_BIN="$1"
TOOLS_ROOT="$2"
BIN_DIR="$TOOLS_ROOT/bin"
LIB_DIR="$TOOLS_ROOT/lib"

mkdir -p "$BIN_DIR" "$LIB_DIR"

list_deps() {
    otool -L "$1" | tail -n +2 | awk '{print $1}'
}

rpaths_for() {
    otool -l "$1" | awk '
        $1 == "cmd" && $2 == "LC_RPATH" { in_rpath = 1; next }
        in_rpath && $1 == "path" { print $2; in_rpath = 0 }
    '
}

should_bundle() {
    case "$1" in
        /opt/homebrew/*|/usr/local/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

expand_special_path() {
    local dep="$1"
    local parent="$2"
    local parent_dir
    parent_dir="$(dirname "$parent")"

    case "$dep" in
        @loader_path/*)
            printf '%s\n' "$parent_dir/${dep#@loader_path/}"
            ;;
        @executable_path/*)
            printf '%s\n' "$parent_dir/${dep#@executable_path/}"
            ;;
        *)
            printf '%s\n' "$dep"
            ;;
    esac
}

resolve_dep() {
    local dep="$1"
    local parent="$2"
    local candidate

    candidate="$(expand_special_path "$dep" "$parent")"
    if [ -e "$candidate" ]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    if [[ "$dep" == @rpath/* ]]; then
        local rel_path="${dep#@rpath/}"
        while IFS= read -r rpath; do
            candidate="$(expand_special_path "$rpath" "$parent")/$rel_path"
            if [ -e "$candidate" ]; then
                printf '%s\n' "$candidate"
                return 0
            fi
        done < <(rpaths_for "$parent")
    fi

    return 1
}

bundle_library() {
    local src="$1"
    local base
    local dest

    base="$(basename "$src")"
    dest="$LIB_DIR/$base"

    if [ -f "$dest" ]; then
        return 0
    fi

    echo "    + lib $base"
    cp -fL "$src" "$dest"
    chmod u+w "$dest"
    install_name_tool -id "@loader_path/$base" "$dest"

    while IFS= read -r dep; do
        [ -n "$dep" ] || continue

        local resolved="$dep"
        if [[ "$dep" == @* ]]; then
            resolved="$(resolve_dep "$dep" "$src")" || continue
        fi

        if [ "$resolved" = "$src" ]; then
            continue
        fi

        if should_bundle "$resolved"; then
            bundle_library "$resolved"
            install_name_tool -change "$dep" "@loader_path/$(basename "$resolved")" "$dest"
        fi
    done < <(list_deps "$src")
}

bundle_binary() {
    local src="$1"
    local base
    local dest

    base="$(basename "$src")"
    dest="$BIN_DIR/$base"

    echo "  + tool $base"
    cp -fL "$src" "$dest"
    chmod u+w "$dest"

    while IFS= read -r dep; do
        [ -n "$dep" ] || continue

        local resolved="$dep"
        if [[ "$dep" == @* ]]; then
            resolved="$(resolve_dep "$dep" "$src")" || continue
        fi

        if should_bundle "$resolved"; then
            bundle_library "$resolved"
            install_name_tool -change "$dep" "@executable_path/../lib/$(basename "$resolved")" "$dest"
        fi
    done < <(list_deps "$src")

    chmod 755 "$dest"
}

bundle_binary "$SOURCE_BIN"
