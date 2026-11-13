import QtQuick 2.12
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

// Generic "are you sure?" dialog: PopupUtils.open(confirmDialog, root, {title, text, confirmText, callback})
Dialog {
    id: dlg
    property string confirmText: i18n.tr("OK")
    property bool destructive: true
    property var callback

    Button {
        text: dlg.confirmText
        color: dlg.destructive ? theme.palette.normal.negative : theme.palette.normal.positive
        onClicked: { var f = dlg.callback; PopupUtils.close(dlg); if (f) f() }
    }
    Button { text: i18n.tr("Cancel"); onClicked: PopupUtils.close(dlg) }
}
