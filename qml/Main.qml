import QtQuick 2.12
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import io.thp.pyotherside 1.4
import "pages"

MainView {
    id: root
    applicationName: "snapshelf.giovix64"
    anchorToKeyboard: true
    width: units.gu(100)
    height: units.gu(75)

    // ------------------------------------------------------------- shared state
    property bool ready: false
    property var queue: []                // snap names waiting or running
    property string busyName: ""
    property real busyFrac: -1
    property string busyLabel: ""
    property var results: ({})            // name -> {ok, msg, kind} of the last finished action
    property int dataRevision: 0          // bumped after every action: pages reload
    property int updates: 0

    function isQueued(name) { return queue.indexOf(name) >= 0 }

    function levelColor(level) {
        switch (level) {
        case "gpu": return "#2f855a"
        case "good": return "#2b6cb0"
        case "no": return "#c53030"
        case "update": return "#6b46c1"
        case "devmode": return "#4a5568"
        default: return "#b7791f"
        }
    }
    function levelText(level) {
        switch (level) {
        case "gpu": return i18n.tr("GPU")
        case "good": return "core24"
        case "no": return i18n.tr("not supported")
        case "update": return i18n.tr("update")
        case "devmode": return "devmode"
        default: return i18n.tr("works")
        }
    }

    function toast(text) { toastLabel.text = text; toastBox.opacity = 1; toastTimer.restart() }

    // run fn() once the sudo password is known
    function withPassword(fn) {
        py.call("backend.has_password", [], function(has) {
            if (has) fn()
            else PopupUtils.open(passwordDialog, root, { "callback": fn })
        })
    }
    function run(kind, name, args) {
        withPassword(function() {
            py.call("backend.enqueue", [kind, name, args || []], function(ok) {
                if (!ok) toast(i18n.tr("%1 is already in the queue").arg(name))
            })
        })
    }
    function refreshAll() {
        withPassword(function() { py.call("backend.refresh_all", [], function(n) {
            if (n.length === 0) toast(i18n.tr("Everything is up to date"))
        }) })
    }
    function openApp(name) {
        py.call("backend.open_app", [name], function(id) {
            if (id) Qt.openUrlExternally("application:///" + id + ".desktop")
            else toast(i18n.tr("This snap has no graphical application"))
        })
    }
    function openDetail(name, title) { stack.push(detailPage, { "snapName": name, "snapTitle": title }) }
    function openSettings() { stack.push(settingsPage) }
    function reloadUpdates() { py.call("backend.updates_count", [], function(n) { root.updates = n }) }

    Python {
        id: py
        Component.onCompleted: {
            addImportPath(Qt.resolvedUrl("."))
            setHandler("progress", function(name, frac, label) {
                root.busyName = name; root.busyFrac = frac; root.busyLabel = label
            })
            setHandler("queue", function(names) {
                root.queue = names
                if (names.length === 0) root.busyName = ""
            })
            setHandler("done", function(name, kind, ok, msg) {
                var r = root.results; r[name] = { "ok": ok, "msg": msg, "kind": kind }; root.results = r
                if (root.busyName === name) root.busyName = ""
                root.dataRevision++
                root.reloadUpdates()
                root.toast((ok ? "✓ " : "✗ ") + name + ": " + msg)
            })
            importModule("backend", function() { root.ready = true; root.reloadUpdates() })
        }
        onError: { console.log("python error: " + traceback); root.toast(i18n.tr("Internal error, see the log")) }
    }

    PageStack {
        id: stack
        Component.onCompleted: push(browsePage)
    }
    // pages and dialogs are created in this context, so they can use `root` and `py`
    Component { id: browsePage; BrowsePage {} }
    Component { id: detailPage; DetailPage {} }
    Component { id: settingsPage; SettingsPage {} }
    Component { id: passwordDialog; PasswordDialog {} }
    Component {
        id: confirmDialog
        ConfirmDialog {}
    }

    // ------------------------------------------------------------- toast
    Rectangle {
        id: toastBox
        anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: units.gu(3) }
        width: Math.min(parent.width - units.gu(4), toastLabel.implicitWidth + units.gu(4))
        height: toastLabel.height + units.gu(2)
        radius: units.gu(1.5)
        color: theme.palette.normal.overlay
        border.color: theme.palette.normal.base
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 200 } }
        Label {
            id: toastLabel
            anchors.centerIn: parent
            width: Math.min(implicitWidth, root.width - units.gu(8))
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
        Timer { id: toastTimer; interval: 4500; onTriggered: toastBox.opacity = 0 }
        MouseArea { anchors.fill: parent; onClicked: toastBox.opacity = 0 }
    }
}
