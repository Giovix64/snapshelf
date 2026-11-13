import QtQuick 2.12
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

Dialog {
    id: dlg
    property var callback
    title: i18n.tr("Password")
    text: i18n.tr("Installing and removing snaps needs administrator rights. Enter your password " +
                  "(the screen-lock passcode). It is kept only in memory while Snapshelf is open.")

    TextField {
        id: pw
        echoMode: TextInput.Password
        placeholderText: i18n.tr("Password or passcode")
        inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
        onAccepted: ok.clicked()
        Component.onCompleted: forceActiveFocus()
    }
    Label {
        id: err
        visible: false
        text: i18n.tr("Wrong password")
        color: theme.palette.normal.negative
    }
    Button {
        id: ok
        text: i18n.tr("OK")
        color: theme.palette.normal.positive
        enabled: pw.text.length > 0 && !checking.running
        onClicked: {
            checking.running = true
            py.call("backend.set_password", [pw.text], function(good) {
                checking.running = false
                if (good) {
                    var f = dlg.callback
                    PopupUtils.close(dlg)
                    if (f) f()
                } else {
                    err.visible = true
                    pw.text = ""
                }
            })
        }
    }
    ActivityIndicator { id: checking; running: false; visible: running }
    Button { text: i18n.tr("Cancel"); onClicked: PopupUtils.close(dlg) }
}
