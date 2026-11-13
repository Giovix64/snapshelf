import QtQuick 2.12
import Lomiri.Components 1.3

// Small coloured label: compatibility level, "update", "devmode"…
Rectangle {
    property alias text: label.text
    implicitWidth: label.implicitWidth + units.gu(2)
    implicitHeight: units.gu(3)
    radius: units.gu(1)
    Label {
        id: label
        anchors.centerIn: parent
        color: "white"
        textSize: Label.Small
    }
}
