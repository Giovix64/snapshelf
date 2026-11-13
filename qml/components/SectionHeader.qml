import QtQuick 2.12
import Lomiri.Components 1.3

// Title of a group of settings
Item {
    property alias text: label.text
    width: parent ? parent.width : 0
    height: units.gu(5)
    Label {
        id: label
        anchors { left: parent.left; bottom: parent.bottom; leftMargin: units.gu(2); bottomMargin: units.gu(0.5) }
        font.bold: true
        color: theme.palette.normal.backgroundSecondaryText
    }
}
