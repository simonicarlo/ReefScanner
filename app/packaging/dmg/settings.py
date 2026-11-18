# dmgbuild settings for ReefScanner.dmg, run by app/scripts/build_app.sh:
#
#   dmgbuild -s packaging/dmg/settings.py -D app=dist/ReefScanner.app \
#     -D background=packaging/dmg/background.tiff -D icon=packaging/icon/AppIcon.icns \
#     ReefScanner dist/ReefScanner.dmg
#
# The window shows the app on the left and Applications on the right, over
# background.tiff (drawn by make_background.py; the icon positions must agree).
# `defines` is provided by dmgbuild; it runs this file without `__file__`, so
# paths come in as defines rather than relative to here.
import os.path

application = defines["app"]  # noqa: F821
appname = os.path.basename(application)

format = "ULFO"  # LZFSE: smaller than UDZO, opens on macOS 10.11+
files = [application]
symlinks = {"Applications": "/Applications"}

# The disk shows the app's icon (the flat one; volumes don't use Assets.car).
icon = defines["icon"]  # noqa: F821

background = defines["background"]  # noqa: F821
# The window frame, title bar included. Taller than the layout needs, so it
# still fits when the user's Finder adds a tab bar and path bar.
window_rect = ((200, 120), (660, 440))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
show_icon_preview = False

icon_size = 128
text_size = 13
label_pos = "bottom"
icon_locations = {appname: (165, 140), "Applications": (495, 140)}
hide_extension = [appname]
