import QtQuick 2.12
import Lomiri.Components 1.3

// One snap in a list (search results, installed, updates)
ListItem {
    id: item
    property var snap: ({})
    property bool showBadge: true
    readonly property bool running: root.busyName === snap.name
    readonly property bool queued: root.isQueued(snap.name)

    signal open()

    height: layout.height + (progress.visible ? progress.height + units.gu(1) : 0) + (divider.visible ? divider.height : 0)
    onClicked: open()

    ListItemLayout {
        id: layout
        title.text: snap.title + (snap.verified ? "  ✓" : "")
        subtitle.text: snap.summary
        summary.text: [snap.publisher, snap.version, snap.installed_size || "",
                       (snap.installed && !snap.update && item.showBadge ? i18n.tr("installed") : "")]
                      .filter(function(s) { return s }).join(" · ")

        LomiriShape {
            SlotsLayout.position: SlotsLayout.Leading
            width: units.gu(6); height: width
            aspect: LomiriShape.Flat
            backgroundColor: "transparent"
            sourceFillMode: LomiriShape.PreserveAspectFit
            source: iconImg.status === Image.Ready ? iconImg : null   // no texture until loaded
            Image {
                id: iconImg
                visible: false
                source: snap.icon ? (snap.icon.indexOf("/") === 0 ? "file://" + snap.icon : snap.icon) : ""
                sourceSize.width: 128
                asynchronous: true
            }
            Icon {
                anchors.centerIn: parent
                width: units.gu(4); height: width
                name: "package-x-generic-symbolic"
                visible: iconImg.status !== Image.Ready
            }
        }
        Badge {
            SlotsLayout.position: SlotsLayout.Trailing
            visible: item.showBadge && !item.queued
            color: root.levelColor(snap.level)
            text: root.levelText(snap.level)
        }
        ActivityIndicator {
            SlotsLayout.position: SlotsLayout.Trailing
            running: item.queued
            visible: running
        }
        ProgressionSlot {}
    }

    Column {
        id: progress
        visible: item.queued
        anchors { left: parent.left; right: parent.right; top: layout.bottom; leftMargin: units.gu(2); rightMargin: units.gu(2) }
        ProgressBar {
            width: parent.width
            height: units.dp(3)
            indeterminate: !item.running || root.busyFrac < 0
            minimumValue: 0; maximumValue: 1
            value: item.running && root.busyFrac >= 0 ? root.busyFrac : 0
        }
        Label {
            text: item.running ? root.busyLabel : i18n.tr("Waiting in the queue…")
            textSize: Label.XSmall
            elide: Text.ElideRight
            width: parent.width
        }
    }
}
