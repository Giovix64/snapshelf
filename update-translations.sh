#!/bin/sh
# Refresh po/snapshelf.giovix64.pot from the sources and merge it into every po/<lang>.po
set -e
cd "$(dirname "$0")"
xgettext --from-code=UTF-8 -L JavaScript --keyword=tr --keyword=tr:1,2 -o po/qml.pot qml/Main.qml qml/pages/*.qml qml/components/*.qml
xgettext --from-code=UTF-8 -L Python --keyword=_ -o po/py.pot qml/backend.py
msgcat po/qml.pot po/py.pot -o po/snapshelf.giovix64.pot && rm po/qml.pot po/py.pot
for po in po/*.po; do msgmerge -q -U --backup=none "$po" po/snapshelf.giovix64.pot; done
