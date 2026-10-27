# dmgbuild settings for the AniGUI installer window.
#   dmgbuild -s packaging/dmg_settings.py -D app=dist/AniGUI.app \
#            -D background=build/dmg-background.tiff -D volicon=packaging/AniGUI.icns \
#            "AniGUI" AniGUI.dmg
# Positions must match packaging/make_dmg_background.py.
# `defines` is provided by dmgbuild when it executes this file.

import os.path

application = defines.get("app", "dist/AniGUI.app")  # noqa: F821
appname = os.path.basename(application)

format = "ULFO"                 # LZFSE-compressed, opens on macOS 10.11+
filesystem = "HFS+"
files = [application]  # no hide_extensions: its Finder flag breaks the strict signature check
symlinks = {"Applications": "/Applications"}

icon = defines.get("volicon")  # noqa: F821  (volume icon in Finder's sidebar)
background = defines.get("background")  # noqa: F821

window_rect = ((200, 140), (660, 400))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False
arrange_by = None
icon_size = 128
text_size = 13
icon_locations = {
    appname: (170, 190),
    "Applications": (490, 190),
}
