import QtQuick 2.12
import Lomiri.Components 1.3

// A settings row with a switch. The owner keeps the state: bind `checked`, handle `toggled`.
ListItem {
    id: row
    property bool checked: false
    property string titleText
    property string subtitleText
    signal toggled(bool value)

    height: lay.height + (divider.visible ? divider.height : 0)
    onClicked: row.toggled(!row.checked)

    ListItemLayout {
        id: lay
        title.text: row.titleText
        subtitle.text: row.subtitleText
        subtitle.wrapMode: Text.WordWrap
        subtitle.maximumLineCount: 4
        Switch {
            SlotsLayout.position: SlotsLayout.Trailing
            checked: row.checked
            onClicked: row.toggled(checked)
        }
    }
}
