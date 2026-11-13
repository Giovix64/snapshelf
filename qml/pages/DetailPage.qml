import QtQuick 2.12
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import "../components"

Page {
    id: dp
    property string snapName
    property string snapTitle
    property var d: ({})
    property bool loading: true
    property var compatSupport: ({ "available": false })
    property int channelIndex: 0
    readonly property bool queued: root.isQueued(snapName)
    readonly property bool running: root.busyName === snapName
    readonly property var lastResult: root.results[snapName]

    function load() {
        loading = true
        py.call("backend.info", [snapName], function(res) {
            d = res; loading = false
            channelIndex = 0
            if (res.installed && res.channels) {
                for (var i = 0; i < res.channels.length; i++)
                    if (res.channels[i].name === res.installed_channel
                        || "latest/" + res.installed_channel === res.channels[i].name) channelIndex = i
            }
        })
    }
    function confirm(title, text, confirmText, fn) {
        PopupUtils.open(confirmDialog, root, { "title": title, "text": text, "confirmText": confirmText, "callback": fn })
    }
    Component.onCompleted: {
        load()
        py.call("backend.compat_support", [], function(s) { dp.compatSupport = s })
    }
    Connections { target: root; function onDataRevisionChanged() { dp.load() } }

    header: PageHeader {
        id: dh
        title: dp.d.title || dp.snapTitle
        trailingActionBar.actions: [
            Action {
                iconName: "external-link"; text: i18n.tr("Open in the Snap Store website")
                onTriggered: Qt.openUrlExternally("https://snapcraft.io/" + dp.snapName)
            }
        ]
    }

    ActivityIndicator { anchors.centerIn: parent; running: dp.loading && !dp.d.name; visible: running }

    Flickable {
        anchors { top: dh.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height + units.gu(4)
        clip: true
        visible: !!dp.d.name || !!dp.d.error

        Column {
            id: col
            x: units.gu(2); y: units.gu(2)
            width: parent.width - units.gu(4)
            spacing: units.gu(1.5)

            Label {
                visible: !!dp.d.error
                text: dp.d.error || ""
                color: theme.palette.normal.negative
                wrapMode: Text.WordWrap; width: parent.width
            }

            // ------------------------------------------------ title block
            Row {
                spacing: units.gu(2)
                width: parent.width
                LomiriShape {
                    width: units.gu(11); height: width
                    aspect: LomiriShape.Flat
                    backgroundColor: "transparent"
                    sourceFillMode: LomiriShape.PreserveAspectFit
                    source: bigIcon.status === Image.Ready ? bigIcon : null
                    Image { id: bigIcon; visible: false; source: dp.d.icon || ""; sourceSize.width: 256; asynchronous: true }
                }
                Column {
                    width: parent.width - units.gu(13)
                    spacing: units.gu(0.5)
                    Label { text: dp.d.title || ""; textSize: Label.Large; wrapMode: Text.WordWrap; width: parent.width }
                    Label {
                        text: (dp.d.publisher || "") + (dp.d.verified ? "  ✓ " + i18n.tr("verified") : "")
                        color: theme.palette.normal.backgroundSecondaryText
                    }
                    Label { text: dp.d.summary || ""; wrapMode: Text.WordWrap; width: parent.width }
                }
            }

            // ------------------------------------------------ compatibility
            Rectangle {
                width: parent.width; height: compatCol.height + units.gu(2); radius: units.gu(1)
                color: root.levelColor(dp.d.level)
                Column {
                    id: compatCol
                    x: units.gu(1.5); y: units.gu(1); width: parent.width - units.gu(3)
                    Label { text: dp.d.compat || ""; color: "white"; font.bold: true; wrapMode: Text.WordWrap; width: parent.width }
                    Repeater {
                        model: dp.d.notes || []
                        Label { text: "• " + modelData; color: "white"; textSize: Label.Small; wrapMode: Text.WordWrap; width: compatCol.width }
                    }
                }
            }

            // ------------------------------------------------ channel
            OptionSelector {
                id: channelSel
                visible: (dp.d.channels || []).length > 1
                width: parent.width
                text: i18n.tr("Channel")
                selectedIndex: dp.channelIndex
                onSelectedIndexChanged: dp.channelIndex = selectedIndex
                model: (dp.d.channels || []).map(function(c) {
                    return c.label + "  ·  " + c.version + (c.size ? "  ·  " + c.size : "") + (c.released ? "  ·  " + c.released : "")
                })
            }

            // ------------------------------------------------ actions
            Flow {
                width: parent.width
                spacing: units.gu(1.5)
                enabled: !dp.queued

                Button {
                    visible: !dp.d.installed && dp.d.level !== "no" && !dp.d.error
                    color: theme.palette.normal.positive
                    text: dp.d.gpu ? i18n.tr("Install (with GPU)") : i18n.tr("Install")
                    onClicked: {
                        var ch = (dp.d.channels || [])[dp.channelIndex]
                        root.run("install", dp.snapName, [ch ? ch.name : "", dp.d.gpu])
                    }
                }
                Button {
                    visible: !!dp.d.installed && dp.d.has_apps
                    color: theme.palette.normal.positive
                    text: i18n.tr("Open")
                    onClicked: root.openApp(dp.snapName)
                }
                Button {
                    visible: !!dp.d.update
                    color: theme.palette.normal.focus
                    text: i18n.tr("Update")
                    onClicked: root.run("refresh", dp.snapName, [])
                }
                Button {
                    readonly property var ch: (dp.d.channels || [])[dp.channelIndex]
                    visible: !!dp.d.installed && !!ch && ch.name !== dp.d.installed_channel
                             && "latest/" + dp.d.installed_channel !== ch.name
                    text: i18n.tr("Switch to %1").arg(ch ? ch.label : "")
                    onClicked: root.run("switch", dp.snapName, [ch.name])
                }
                Button {
                    visible: !!dp.d.installed && dp.d.gpu && !dp.d.gpu_connected
                    text: i18n.tr("Connect GPU")
                    onClicked: root.run("gpu", dp.snapName, [])
                }
                Button {
                    visible: !!dp.d.installed
                    color: theme.palette.normal.negative
                    text: i18n.tr("Remove")
                    onClicked: dp.confirm(i18n.tr("Remove %1?").arg(dp.d.title), i18n.tr("The application and its data will be removed."),
                                          i18n.tr("Remove"), function() { root.run("remove", dp.snapName, []) })
                }
            }

            // ------------------------------------------------ progress / result
            Column {
                visible: dp.queued
                width: parent.width
                spacing: units.gu(0.5)
                ProgressBar {
                    width: parent.width
                    indeterminate: !dp.running || root.busyFrac < 0
                    minimumValue: 0; maximumValue: 1
                    value: dp.running && root.busyFrac >= 0 ? root.busyFrac : 0
                }
                Label {
                    text: dp.running ? root.busyLabel : i18n.tr("Waiting in the queue…")
                    textSize: Label.Small; wrapMode: Text.WordWrap; width: parent.width
                }
            }
            Label {
                visible: !dp.queued && !!dp.lastResult
                text: dp.lastResult ? dp.lastResult.msg : ""
                color: dp.lastResult && dp.lastResult.ok ? theme.palette.normal.positive : theme.palette.normal.negative
                wrapMode: Text.WordWrap; width: parent.width
            }

            // ------------------------------------------------ installed options
            Column {
                visible: !!dp.d.installed && dp.d.has_apps
                width: parent.width
                ListItem {
                    height: pinRow.height
                    onClicked: pinSwitch.clicked()
                    ListItemLayout {
                        id: pinRow
                        title.text: i18n.tr("Show in the launcher")
                        subtitle.text: i18n.tr("Pin the app to the Lomiri sidebar")
                        Switch {
                            id: pinSwitch
                            SlotsLayout.position: SlotsLayout.Trailing
                            checked: !!dp.d.pinned
                            onClicked: py.call("backend.pin", [dp.snapName, !dp.d.pinned], function(state) {
                                dp.d = Object.assign({}, dp.d, { "pinned": state })
                            })
                        }
                    }
                }
                ListItem {
                    height: compatRow.height
                    enabled: dp.compatSupport.available
                    onClicked: compatSwitch.clicked()
                    ListItemLayout {
                        id: compatRow
                        title.text: i18n.tr("Compatibility mode (X11 + Turnip)")
                        subtitle.text: dp.compatSupport.available
                                       ? i18n.tr("For apps that open as an empty grey window: run them in landscape X11 with the Mesa Turnip GPU driver")
                                       : dp.compatSupport.reason || ""
                        subtitle.maximumLineCount: 3
                        subtitle.wrapMode: Text.WordWrap
                        Switch {
                            id: compatSwitch
                            SlotsLayout.position: SlotsLayout.Trailing
                            checked: !!dp.d.compat_mode
                            onClicked: py.call("backend.set_compat_mode", [dp.snapName, !dp.d.compat_mode], function(r) {
                                dp.d = Object.assign({}, dp.d, { "compat_mode": r.enabled })
                                if (!r.ok && r.msg) root.toast(r.msg)
                            })
                        }
                    }
                }
            }

            // ------------------------------------------------ facts
            Grid {
                columns: 2
                columnSpacing: units.gu(2)
                rowSpacing: units.gu(0.5)
                Repeater {
                    model: [
                        [i18n.tr("Version"), dp.d.installed ? dp.d.installed_version + (dp.d.update ? "  →  " + dp.d.version : "") : dp.d.version],
                        [i18n.tr("Channel"), dp.d.installed ? dp.d.installed_channel : ""],
                        [i18n.tr("Download size"), dp.d.size],
                        [i18n.tr("Base"), dp.d.base],
                        [i18n.tr("Confinement"), dp.d.confinement + (dp.d.installed_devmode ? " (devmode)" : "")],
                        [i18n.tr("GPU"), dp.d.gpu ? (dp.d.installed ? (dp.d.gpu_connected ? i18n.tr("connected") : i18n.tr("not connected")) : i18n.tr("supported")) : i18n.tr("no")],
                        [i18n.tr("License"), dp.d.license]
                    ].filter(function(r) { return !!r[1] }).reduce(function(a, r) { return a.concat(r) }, [])
                    Label {
                        text: modelData
                        font.bold: index % 2 === 0
                        textSize: Label.Small
                        color: index % 2 === 0 ? theme.palette.normal.backgroundSecondaryText : theme.palette.normal.backgroundText
                    }
                }
            }

            // ------------------------------------------------ screenshots
            ListView {
                visible: (dp.d.screenshots || []).length > 0
                width: parent.width; height: visible ? units.gu(32) : 0
                orientation: ListView.Horizontal
                spacing: units.gu(1)
                clip: true
                model: dp.d.screenshots || []
                delegate: Image {
                    height: units.gu(32)
                    width: status === Image.Ready ? height * implicitWidth / Math.max(1, implicitHeight) : height * 1.6
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    sourceSize.height: 640
                    source: modelData
                    ActivityIndicator { anchors.centerIn: parent; running: parent.status === Image.Loading; visible: running }
                    MouseArea { anchors.fill: parent; onClicked: Qt.openUrlExternally(modelData) }
                }
            }

            Label { text: dp.d.description || ""; wrapMode: Text.WordWrap; width: parent.width; textFormat: Text.PlainText }
            Label {
                visible: !!dp.d.website
                text: "<a href=\"" + dp.d.website + "\">" + dp.d.website + "</a>"
                linkColor: theme.palette.normal.activity
                onLinkActivated: Qt.openUrlExternally(link)
            }
        }
    }
}
