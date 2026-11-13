import QtQuick 2.12
import Lomiri.Components 1.3

// A system-check row: ok/warning icon, explanation and an optional fix button
ListItem {
    id: row
    property bool good: true
    property string titleText
    property string subtitleText
    property string actionText
    signal action()

    height: lay.height + (divider.visible ? divider.height : 0)

    ListItemLayout {
        id: lay
        title.text: row.titleText
        subtitle.text: row.subtitleText
        subtitle.wrapMode: Text.WordWrap
        subtitle.maximumLineCount: 5
        Icon {
            SlotsLayout.position: SlotsLayout.Leading
            width: units.gu(3); height: width
            name: row.good ? "ok" : "dialog-warning-symbolic"
            color: row.good ? theme.palette.normal.positive : theme.palette.normal.negative
        }
        Button {
            SlotsLayout.position: SlotsLayout.Trailing
            visible: !row.good && row.actionText !== ""
            text: row.actionText
            onClicked: row.action()
        }
    }
}
